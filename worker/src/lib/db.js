// D1 小工具：參數一律用 ? 綁定；布林轉 0/1、undefined 轉 NULL。
// D1 沒有跨多個請求的交易：要「一起成功或一起失敗」的寫入用 batch()（整批原子）。

export class DbError extends Error {}

const param = (v) => (v === undefined ? null : typeof v === 'boolean' ? (v ? 1 : 0) : v);

export function wrap(binding) {
  const prep = (sql, params = []) => binding.prepare(sql).bind(...params.map(param));
  return {
    binding,
    prep,
    async all(sql, ...params) { return (await prep(sql, params).all()).results ?? []; },
    async first(sql, ...params) { return (await prep(sql, params).first()) ?? null; },
    async value(sql, ...params) {
      const row = await prep(sql, params).first();
      return row ? Object.values(row)[0] : null;
    },
    async run(sql, ...params) { return (await prep(sql, params).run()).meta ?? {}; },
    /** 新增一列並回傳新的 id */
    async insert(table, row) {
      const cols = Object.keys(row);
      const meta = (await prep(`INSERT INTO ${table} (${cols.join(', ')}) VALUES (${cols.map(() => '?').join(', ')})`, cols.map((c) => row[c])).run()).meta;
      return Number(meta.last_row_id);
    },
    async batch(statements) { return statements.length ? binding.batch(statements) : []; },
    /** 多個查詢一次送出（一趟來回）：many([[sql, ...params], …]) → [rows, rows, …] */
    async many(queries) {
      if (!queries.length) return [];
      const results = await binding.batch(queries.map(([sql, ...params]) => prep(sql, params)));
      return results.map((r) => r.results ?? []);
    },
  };
}

export const insertStmt = (db, table, row) => {
  const cols = Object.keys(row);
  return db.prep(`INSERT INTO ${table} (${cols.join(', ')}) VALUES (${cols.map(() => '?').join(', ')})`, cols.map((c) => row[c]));
};

export const placeholders = (n) => Array.from({ length: n }, () => '?').join(', ');

/** 依 id 分組：[{k, ...}] → Map(k → [rows]) */
export function groupBy(rows, key) {
  const map = new Map();
  for (const row of rows) {
    const k = row[key];
    if (!map.has(k)) map.set(k, []);
    map.get(k).push(row);
  }
  return map;
}

export const isUniqueError = (e) => /UNIQUE constraint failed/i.test(String(e?.message ?? e));
