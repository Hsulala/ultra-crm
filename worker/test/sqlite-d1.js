// 本機與測試用：用 Node 內建的 SQLite（node:sqlite）模擬 Cloudflare D1 的 binding（prepare / bind / all / batch）。
// 正式環境不會用到這個檔案。
import { DatabaseSync } from 'node:sqlite';

export function createSqliteBinding(file = ':memory:') {
  // exec：整份 SQL（migration）
  const sqlite = new DatabaseSync(file);
  sqlite.exec('PRAGMA foreign_keys = ON');
  const run = (sql, params) => {
    const stmt = sqlite.prepare(sql);
    if (stmt.columns().length) {
      // RETURNING 也走這裡：要用 all() 取回列，同時算出異動筆數
      const before = sqlite.prepare('SELECT total_changes() AS n').get().n;
      const results = stmt.all(...params);
      const changes = sqlite.prepare('SELECT total_changes() AS n').get().n - before;
      return { results, meta: { changes, last_row_id: Number(sqlite.prepare('SELECT last_insert_rowid() AS n').get().n) } };
    }
    const info = stmt.run(...params);
    return { results: [], meta: { changes: Number(info.changes), last_row_id: Number(info.lastInsertRowid) } };
  };
  const statement = (sql, params = []) => ({
    sql,
    params,
    bind: (...values) => statement(sql, values),
    all: async () => run(sql, params),
    first: async () => run(sql, params).results[0] ?? null,
    raw: async () => run(sql, params).results.map((r) => Object.values(r)),
    run: async () => run(sql, params),
  });
  return {
    prepare: (sql) => statement(sql),
    async batch(statements) {
      sqlite.exec('BEGIN');
      try {
        const out = statements.map((s) => run(s.sql, s.params));
        sqlite.exec('COMMIT');
        return out;
      } catch (error) {
        sqlite.exec('ROLLBACK');
        throw error;
      }
    },
    exec: async (sql) => { sqlite.exec(sql); return { count: 0 }; },
    close: () => sqlite.close(),
    sqlite,
  };
}
