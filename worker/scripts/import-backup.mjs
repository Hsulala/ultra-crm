// 把店家總覽下載的 Ultra 備份（/api/remote/backup 的 JSON，Railway PostgreSQL 版或本版都可以）轉成 D1 的 SQL。
//   node scripts/import-backup.mjs 備份.json --sql out.sql     產生 SQL（再用 wrangler d1 execute ultra-crm --remote --file out.sql）
//   node scripts/import-backup.mjs 備份.json --rehearse        在本機 SQLite 建表、匯入、逐表比對
// 匯入前 D1 必須是剛套用 migrations 的空資料庫。
import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { normalizeInstant } from '../src/lib/time.js';

// 依外鍵順序（被參照的先寫）
export const TABLES = ['members', 'venue_rental_coaches', 'admin_users', 'binding_codes', 'contracts', 'contract_members', 'contract_sessions', 'class_records',
  'coach_unavailabilities', 'schedules', 'notification_logs', 'item_catalog_entries', 'revenue_details', 'bookings', 'venue_bookings', 'app_settings', 'cash_movements', 'cash_closings'];
const SKIP = new Set(['alembic_version', 'd1_migrations', 'import_guard']);
const DATETIME = new Set(['created_at', 'updated_at', 'expires_at', 'used_at', 'submitted_at', 'sent_at', 'interval_start', 'closed_at', 'reviewed_at', 'voided_at']);
const NUMERIC = new Set(['unit_price', 'amount', 'default_price', 'opening_cash', 'cash_sales', 'movements_in', 'movements_out', 'expected_cash', 'counted_cash', 'variance', 'collected_amount', 'remaining_cash', 'cash_float_snapshot']);
const BOOL = new Set(['is_active']);
const JSONCOL = new Set(['denominations']);
const TIME = new Set(['slot_start_time']);

export function convert(column, value) {
  if (value === null || value === undefined) return null;
  if (DATETIME.has(column)) return normalizeInstant(value);
  if (NUMERIC.has(column)) return Number(value);
  if (BOOL.has(column)) return value === true || value === 1 || value === 'true' ? 1 : 0;
  if (JSONCOL.has(column)) return typeof value === 'string' ? value : JSON.stringify(value);
  if (TIME.has(column)) { const m = /^(\d{2}):(\d{2})(?::(\d{2}))?/.exec(String(value)); return m ? `${m[1]}:${m[2]}:${m[3] ?? '00'}` : value; }
  if (typeof value === 'object') throw new Error(`${column} 是無法匯入的格式`);
  return value;
}

const lit = (v) => (v === null ? 'NULL' : typeof v === 'number' ? (Number.isFinite(v) ? String(v) : 'NULL') : `'${String(v).replace(/'/g, "''")}'`);

export function toStatements(backup) {
  const tables = backup.tables ?? {};
  const unknown = Object.keys(tables).filter((t) => !TABLES.includes(t) && !SKIP.has(t));
  if (unknown.length) throw new Error(`備份裡有不認得的資料表：${unknown.join('、')}`);
  const out = [];
  for (const table of TABLES) {
    const rows = tables[table] ?? [];
    if (!rows.length) continue;
    const cols = Object.keys(rows[0]);
    const head = `INSERT INTO ${table} (${cols.join(', ')}) VALUES `;
    let parts = []; let size = head.length;
    for (const row of rows) {
      const v = `(${cols.map((c) => lit(convert(c, row[c]))).join(', ')})`;
      if (parts.length && size + v.length > 90_000) { out.push(`${head}${parts.join(', ')};`); parts = []; size = head.length; }
      parts.push(v); size += v.length + 2;
    }
    if (parts.length) out.push(`${head}${parts.join(', ')};`);
  }
  return out;
}

/** 逐表比對：筆數相同，每一列每個欄位都相同（時間比到微秒、金額比到分） */
export function compare(backup, readTable) {
  const report = [];
  const norm = (table, row) => JSON.stringify(Object.keys(row).sort().map((c) => {
    const v = convert(c, row[c]);
    return [c, NUMERIC.has(c) && v !== null ? Math.round(v * 100) : v];
  }));
  for (const table of TABLES) {
    const src = (backup.tables?.[table] ?? []).map((r) => norm(table, r)).sort();
    const dst = readTable(table).map((r) => norm(table, r)).sort();
    const dstSet = new Set(dst); const srcSet = new Set(src);
    const missing = src.filter((r) => !dstSet.has(r));
    const extra = dst.filter((r) => !srcSet.has(r));
    report.push({ table, source: src.length, target: dst.length, missing: missing.length, extra: extra.length, sample: missing[0] ?? extra[0] ?? null });
  }
  return report;
}

export function migrationsSql() {
  const dir = join(import.meta.dirname, '..', 'migrations');
  return readdirSync(dir).filter((f) => f.endsWith('.sql')).sort().map((f) => readFileSync(join(dir, f), 'utf8')).join('\n');
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [file, flag, outFile] = process.argv.slice(2);
  if (!file) { console.error('用法：node scripts/import-backup.mjs 備份.json --sql out.sql | --rehearse'); process.exit(1); }
  const backup = JSON.parse(readFileSync(file, 'utf8'));
  const statements = toStatements(backup);
  if (flag === '--sql') {
    writeFileSync(outFile, `${statements.join('\n')}\n`);
    console.error(`已產生 ${statements.length} 個指令：${outFile}`);
  } else {
    const { DatabaseSync } = await import('node:sqlite');
    const db = new DatabaseSync(':memory:');
    db.exec('PRAGMA foreign_keys = ON');
    db.exec(migrationsSql());
    for (const s of statements) db.exec(s);
    const report = compare(backup, (t) => db.prepare(`SELECT * FROM ${t}`).all());
    for (const r of report) console.log(`${r.table.padEnd(24)} 原 ${String(r.source).padStart(6)} 筆、匯入後 ${String(r.target).padStart(6)} 筆、缺 ${r.missing}、多 ${r.extra}${r.sample ? `\n  例：${r.sample.slice(0, 300)}` : ''}`);
    const fk = db.prepare('PRAGMA foreign_key_check').all();
    if (fk.length) console.log(`外鍵檢查有 ${fk.length} 筆問題`, fk.slice(0, 5));
    if (report.some((r) => r.missing || r.extra) || fk.length) process.exit(2);
    console.log('比對完成：每張表、每一列都相同');
  }
}
