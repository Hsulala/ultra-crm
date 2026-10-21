// 遠端管理介面（對應 app/routers/remote.py）：給店家總覽呼叫，格式與其他店一致。
//   GET /api/remote/stats?month=YYYY-MM、GET /api/remote/config、GET /api/remote/backup（需寫入金鑰）
// 金鑰 REMOTE_READ_KEY／REMOTE_WRITE_KEY（各至少 32 字元）；都沒設時整組回 404。
import { Hono } from 'hono';
import { monthBounds, nowUtc, taipeiParts, nowMs, pad } from '../lib/time.js';

const SYSTEM = 'gym';
const MIN_KEY = 32;
const fails = new Map(); // ip → 失敗時間（同一個 isolate 內）

const good = (k) => typeof k === 'string' && k.length >= MIN_KEY;
async function same(a, b) {
  const [x, y] = await Promise.all([a, b].map((s) => crypto.subtle.digest('SHA-256', new TextEncoder().encode(s))));
  const u = new Uint8Array(x); const v = new Uint8Array(y);
  let d = 0; for (let i = 0; i < u.length; i += 1) d |= u[i] ^ v[i];
  return d === 0;
}

const err = (c, status, error) => c.json({ error }, status);

export const remote = new Hono();

remote.use('*', async (c, next) => {
  const { REMOTE_READ_KEY: read, REMOTE_WRITE_KEY: write } = c.env;
  if (!good(read) && !good(write)) return err(c, 404, '找不到這個功能');
  const ip = c.req.header('cf-connecting-ip') ?? '?';
  const now = Date.now();
  if (fails.size > 1000) fails.clear();
  const recent = (fails.get(ip) ?? []).filter((t) => now - t < 300_000);
  fails.set(ip, recent);
  if (recent.length >= 10) return err(c, 429, '嘗試次數過多，請 5 分鐘後再試');
  const header = c.req.header('authorization') ?? '';
  const token = header.startsWith('Bearer ') && !header.slice(7).includes(' ') ? header.slice(7) : null;
  let role = null;
  if (token) {
    if (good(write) && await same(token, write)) role = 'write';
    else if (good(read) && await same(token, read)) role = 'read';
  }
  if (!role) { recent.push(now); return err(c, 401, '金鑰不正確'); }
  c.set('remoteRole', role);
  return next();
});

remote.get('/stats', async (c) => {
  const p = taipeiParts(nowMs());
  const month = c.req.query('month') ?? `${p.year}-${pad(p.month)}`;
  if (!/^\d{4}-\d{2}$/.test(month) || Number(month.slice(5)) < 1 || Number(month.slice(5)) > 12) return err(c, 400, '月份格式不正確');
  try {
    const db = c.get('db');
    const [start, end] = monthBounds(Number(month.slice(0, 4)), Number(month.slice(5)));
    const count = async (table) => {
      const rows = await db.all(`SELECT status, count(*) AS n FROM ${table} WHERE slot_date >= ? AND slot_date < ? GROUP BY status`, start, end);
      const all = rows.reduce((s, r) => s + r.n, 0);
      const cancelled = rows.find((r) => r.status === 'cancelled')?.n ?? 0;
      return [all - cancelled, cancelled];
    };
    const [courseTotal, courseCancelled] = await count('bookings');
    const [venueTotal, venueCancelled] = await count('venue_bookings');
    const newContracts = await db.value('SELECT count(*) FROM contracts WHERE purchase_date >= ? AND purchase_date < ?', start, end);
    const revenue = await db.value('SELECT coalesce(CAST(round(sum(amount * 100)) AS INTEGER), 0) FROM revenue_details WHERE entry_date >= ? AND entry_date < ?', start, end);
    return c.json({
      system: SYSTEM,
      month,
      bookings: { total: courseTotal, cancelled: courseCancelled },
      gym: { courseBookings: courseTotal, courseCancelled, venueBookings: venueTotal, venueCancelled, newContracts: Number(newContracts), revenue: Number(revenue) / 100 },
    });
  } catch (error) {
    console.error('[remote] 統計錯誤', error);
    return err(c, 500, '店家系統發生錯誤');
  }
});

remote.get('/config', (c) => c.json({ system: SYSTEM, modules: {} }));

// 金額欄位照原本 Decimal 的樣子輸出（'1500.00'），布林輸出 true/false，JSON 欄位輸出物件
const NUMERIC = new Set(['unit_price', 'amount', 'default_price', 'opening_cash', 'cash_sales', 'movements_in', 'movements_out', 'expected_cash', 'counted_cash', 'variance', 'collected_amount', 'remaining_cash', 'cash_float_snapshot']);
const BOOL = new Set(['is_active']);
const JSONCOL = new Set(['denominations']);

remote.get('/backup', async (c) => {
  if (c.get('remoteRole') !== 'write') return err(c, 403, '下載備份需要寫入金鑰');
  try {
    const db = c.get('db');
    const names = (await db.all("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '_cf_%' AND name NOT IN ('d1_migrations', 'import_guard') ORDER BY name")).map((r) => r.name);
    const tables = {};
    for (const name of names) {
      const rows = await db.all(`SELECT * FROM "${name.replace(/"/g, '""')}"`);
      tables[name] = rows.map((row) => Object.fromEntries(Object.entries(row).map(([k, v]) => {
        if (v === null) return [k, v];
        if (NUMERIC.has(k)) return [k, Number(v).toFixed(2)];
        if (BOOL.has(k)) return [k, v === 1];
        if (JSONCOL.has(k)) { try { return [k, JSON.parse(v)]; } catch { return [k, v]; } }
        return [k, v];
      })));
    }
    return c.json({ system: SYSTEM, exportedAt: nowUtc(), tables }, 200, { 'Cache-Control': 'no-store' });
  } catch (error) {
    console.error('[remote] 備份錯誤', error);
    return err(c, 500, '店家系統發生錯誤');
  }
});
