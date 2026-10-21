// 錯誤與輸入驗證：回應格式比照原本的 FastAPI（前端都是讀 body.detail）。
//   業務錯誤：{"detail": "訊息"}（400/403/404…）
//   欄位格式錯誤：422 {"detail": [{"type", "loc", "msg"}]}（前端只看是不是陣列）
import { isDate, normalizeTime, normalizeInstant } from './time.js';

export class HttpError extends Error {
  constructor(status, detail, headers = {}) { super(typeof detail === 'string' ? detail : 'error'); this.status = status; this.detail = detail; this.headers = headers; }
}

export const fail = (status, detail) => { throw new HttpError(status, detail); };
export const redirect = (location, status = 303) => new Response(null, { status, headers: { location } });

/** 讀 JSON 請求內容；不是 JSON 就回 422（FastAPI 的行為） */
export async function readJson(c) {
  try {
    const text = await c.req.text();
    return text ? JSON.parse(text) : undefined;
  } catch {
    throw new HttpError(422, [{ type: 'json_invalid', loc: ['body'], msg: 'JSON decode error' }]);
  }
}

// ---- 欄位規則（對應 pydantic 的型別轉換）----
const MISSING = Symbol('missing');
const MESSAGES = {
  int: 'Input should be a valid integer, unable to parse string as an integer',
  float: 'Input should be a valid number, unable to parse string as a number',
  str: 'Input should be a valid string',
  date: 'Input should be a valid date',
  time: 'Input should be in a valid time format',
  bool: 'Input should be a valid boolean',
};
const bad = (loc, type, msg, input) => ({ type, loc, msg, input });

const kinds = {
  str(v) { return typeof v === 'string' ? v : MISSING; },
  int(v) {
    if (typeof v === 'boolean') return v ? 1 : 0;
    if (typeof v === 'number' && Number.isInteger(v)) return v;
    if (typeof v === 'number' && Number.isFinite(v) && v === Math.trunc(v)) return v;
    if (typeof v === 'string' && /^\s*-?\d+\s*$/.test(v)) return Number(v);
    return MISSING;
  },
  float(v) {
    if (typeof v === 'boolean') return v ? 1 : 0;
    if (typeof v === 'number' && Number.isFinite(v)) return v;
    if (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v))) return Number(v);
    return MISSING;
  },
  bool(v) {
    if (typeof v === 'boolean') return v;
    if (v === 0 || v === 1) return Boolean(v);
    if (typeof v === 'string' && /^(true|false|1|0|yes|no|on|off)$/i.test(v)) return /^(true|1|yes|on)$/i.test(v);
    return MISSING;
  },
  date(v) { return isDate(v) ? v : (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(v) && isDate(v.slice(0, 10)) && /T00:00(:00(\.0+)?)?Z?$/.test(v) ? v.slice(0, 10) : MISSING); },
  time(v) { return typeof v === 'string' ? normalizeTime(v) ?? MISSING : MISSING; },
  datetime(v) { return typeof v === 'string' ? normalizeInstant(v) ?? MISSING : MISSING; },
  intList(v) {
    if (!Array.isArray(v)) return MISSING;
    const out = v.map((x) => kinds.int(x));
    return out.includes(MISSING) ? MISSING : out;
  },
  dict(v) { return v && typeof v === 'object' && !Array.isArray(v) ? v : MISSING; },
};

/**
 * schema：{ 欄位: 'int' | 'int?' | ['float', 預設值] ... }；結尾 ? 代表可為 null（預設 null）。
 * 回傳轉好型別的物件；有錯一次回 422 列出全部。
 */
export function parseBody(body, schema) {
  const errors = [];
  const out = {};
  if (!body || typeof body !== 'object' || Array.isArray(body)) {
    throw new HttpError(422, [bad(['body'], 'model_attributes_type', 'Input should be a valid dictionary or object to extract fields from')]);
  }
  for (const [field, rule] of Object.entries(schema)) {
    let [kind, dflt] = Array.isArray(rule) ? rule : [rule, MISSING];
    const optional = kind.endsWith('?');
    if (optional) { kind = kind.slice(0, -1); if (dflt === MISSING) dflt = null; }
    const raw = body[field];
    if (raw === undefined) {
      if (dflt === MISSING) errors.push(bad(['body', field], 'missing', 'Field required', body));
      else out[field] = typeof dflt === 'function' ? dflt() : dflt;
      continue;
    }
    if (raw === null && optional) { out[field] = null; continue; }
    const value = kinds[kind](raw);
    if (value === MISSING) errors.push(bad(['body', field], `${kind}_parsing`, MESSAGES[kind] ?? `Input should be a valid ${kind}`, raw));
    else out[field] = value;
  }
  if (errors.length) throw new HttpError(422, errors);
  return out;
}

/** 查詢字串參數（對應 FastAPI 的 Optional[int] 等）；格式不對回 422 */
export function queryParam(c, name, kind = 'str', dflt = null) {
  const raw = c.req.query(name);
  if (raw === undefined || (raw === '' && kind !== 'str')) return dflt;
  const value = kinds[kind](raw);
  if (value === MISSING) throw new HttpError(422, [bad(['query', name], `${kind}_parsing`, MESSAGES[kind] ?? `Input should be a valid ${kind}`, raw)]);
  return value;
}

/** 路徑上的數字 id；不是數字回 422（FastAPI 的 int path 參數） */
export function pathId(c, name) {
  const raw = c.req.param(name);
  if (!/^-?\d+$/.test(raw ?? '')) throw new HttpError(422, [bad(['path', name], 'int_parsing', MESSAGES.int, raw)]);
  return Number(raw);
}
