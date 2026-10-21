// 日期與時間：資料庫一律存 UTC（'YYYY-MM-DDTHH:MM:SS.ffffffZ'，固定六位小數，字串比較＝時間比較），
// 畫面與「今天」一律以台北時間（UTC+8，台灣沒有日光節約時間）計算，對應原本 cash_service 的 TAIPEI。
const TAIPEI_MS = 8 * 3600_000;

export const pad = (n, w = 2) => String(n).padStart(w, '0');

/** Date → 資料庫時間字串（六位小數；JS 只有毫秒，後三位補 0） */
export function isoUtc(date) {
  return date.toISOString().replace(/\.(\d{3})Z$/, '.$1000Z');
}

let clock = () => Date.now(); // 測試可固定時間
export const setClock = (fn) => { clock = fn ?? (() => Date.now()); };
export const nowMs = () => clock();
export const nowUtc = () => isoUtc(new Date(nowMs()));

/** 任何來源的時間（資料庫字串、PostgreSQL 備份的 +00:00、沒有時區的 SQLite 字串）→ 毫秒 */
export function parseInstant(value) {
  if (value == null || value === '') return null;
  if (value instanceof Date) return value.getTime();
  let s = String(value).trim().replace(' ', 'T');
  if (!/(Z|[+-]\d{2}:?\d{2})$/.test(s)) s += 'Z'; // 沒有時區＝UTC（原本 as_utc 的做法）
  // 微秒：JS 只吃到毫秒
  s = s.replace(/(\.\d{3})\d+/, '$1');
  const ms = Date.parse(s);
  return Number.isNaN(ms) ? null : ms;
}

/** 任何來源的時間 → 資料庫格式（保留原本的微秒） */
export function normalizeInstant(value) {
  if (value == null || value === '') return null;
  const ms = parseInstant(value);
  if (ms == null) return null;
  const micro = /\.(\d{1,6})/.exec(String(value))?.[1];
  const base = new Date(ms).toISOString().slice(0, 19);
  const frac = micro ? micro.padEnd(6, '0') : String(new Date(ms).getUTCMilliseconds()).padStart(3, '0') + '000';
  // 時區不是 UTC 時，毫秒以下的位數仍屬於同一個瞬間，直接沿用
  return `${base}.${frac}Z`;
}

/** 台北時間的各個欄位 */
export function taipeiParts(value) {
  const ms = typeof value === 'number' ? value : parseInstant(value);
  if (ms == null) return null;
  const d = new Date(ms + TAIPEI_MS);
  return { year: d.getUTCFullYear(), month: d.getUTCMonth() + 1, day: d.getUTCDate(), hour: d.getUTCHours(), minute: d.getUTCMinutes(), second: d.getUTCSeconds() };
}

export const taipeiDate = (value) => { const p = taipeiParts(value); return p ? `${p.year}-${pad(p.month)}-${pad(p.day)}` : null; };
export const taipeiToday = () => taipeiDate(nowMs());

/** 台北某一天 00:00 → 資料庫時間字串 */
export const dayStartUtc = (ymd) => isoUtc(new Date(Date.parse(`${ymd}T00:00:00+08:00`)));

/** strftime 的子集合（%Y %m %d %H %M %S），以台北時間格式化，對應原本 templating 的 tpe 篩選器 */
export function formatTaipei(value, fmt = '%m/%d %H:%M') {
  const p = taipeiParts(value);
  if (!p) return '-';
  return fmt.replace(/%([YmdHMS])/g, (_, k) => ({ Y: p.year, m: pad(p.month), d: pad(p.day), H: pad(p.hour), M: pad(p.minute), S: pad(p.second) }[k]));
}

// ---- 純日期（'YYYY-MM-DD'）----
export const isDate = (s) => typeof s === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(s) && !Number.isNaN(Date.parse(`${s}T00:00:00Z`)) && new Date(`${s}T00:00:00Z`).toISOString().slice(0, 10) === s;
export function addDays(ymd, n) {
  const d = new Date(`${ymd}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}
export const ymd = (y, m, d) => `${pad(y, 4)}-${pad(m)}-${pad(d)}`;
export function monthBounds(year, month) {
  const start = ymd(year, month, 1);
  const end = month === 12 ? ymd(year + 1, 1, 1) : ymd(year, month + 1, 1);
  return [start, end];
}
export const weekdayMon0 = (s) => (new Date(`${s}T00:00:00Z`).getUTCDay() + 6) % 7; // 週一 = 0

/** 對應 Python calendar.Calendar(firstweekday=0).monthdatescalendar：整週（週一開頭）的日期 */
export function monthWeeks(year, month) {
  const first = ymd(year, month, 1);
  const [, next] = monthBounds(year, month);
  const last = addDays(next, -1);
  let cur = addDays(first, -weekdayMon0(first));
  const end = addDays(last, 6 - weekdayMon0(last));
  const weeks = [];
  while (cur <= end) {
    const week = [];
    for (let i = 0; i < 7; i += 1) { week.push(cur); cur = addDays(cur, 1); }
    weeks.push(week);
  }
  return weeks;
}

// ---- 時間（'HH:MM:SS'）----
export function normalizeTime(value) {
  const m = /^(\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?$/.exec(String(value ?? '').trim());
  if (!m) return null;
  const [h, mi, s] = [Number(m[1]), Number(m[2]), Number(m[3] ?? 0)];
  if (h > 23 || mi > 59 || s > 59) return null;
  return `${pad(h)}:${pad(mi)}:${pad(s)}`;
}
