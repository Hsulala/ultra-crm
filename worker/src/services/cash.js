// 班次交接現金對帳（對應 app/services/cash_service.py）。
//   應有現金 = 期初現金 + 區間內現金收款 + 現金收入異動 − 現金支出異動
//   差額     = 實點 − 應有
// 區間用資料的 created_at（系統寫入時間）切：(interval_start, closed_at]。金額一律用「分」計算。
import { HttpError } from '../lib/http.js';
import { addDays, dayStartUtc, nowMs, nowUtc, parseInstant, taipeiDate, taipeiParts, taipeiToday } from '../lib/time.js';
import { fromCents, toCents } from '../lib/money.js';
import { SHIFT_LABELS } from './people.js';
import { pyDumps } from '../lib/pyjson.js';

export class CashError extends HttpError { constructor(msg) { super(400, msg); } }

const NOW_SQL = "strftime('%Y-%m-%dT%H:%M:%f000Z','now')";
const FLOAT_KEY = 'cash_float';
export const SHIFT_ORDER = ['morning', 'afternoon', 'evening'];
const SHIFT_END_HOUR = { morning: 13, afternoon: 18, evening: 22 };
export const DENOMINATIONS = [2000, 1000, 500, 200, 100, 50, 10, 5, 1];
const MAX_COUNT_PER_DENOMINATION = 100000;
export const CASH_METHOD_ALIASES = ['現金', 'cash'];
const STANDARD_PAYMENT_METHODS = ['現金', '匯款', '信用卡', 'linepay'];
export const MOVEMENT_TYPE_LABELS = { petty_cash: '零用金支出', refund: '現金退費', coach_advance: '代墊／找零給教練', advance_return: '教練歸還代墊' };
const MOVEMENT_DIRECTIONS = { petty_cash: 'out', refund: 'out', coach_advance: 'out', advance_return: 'in' };

// 付款方式去空白、不分大小寫後是「現金」或「cash」才算現金（SQLite 的 lower 只轉英文，中文本來就沒有大小寫）
export const IS_CASH_SQL = "lower(trim(payment_method)) IN ('現金', 'cash')";
const isCash = (method) => CASH_METHOD_ALIASES.includes(String(method ?? '').trim().toLowerCase());

export function currentShift(ms = nowMs()) {
  const { hour } = taipeiParts(ms);
  if (hour < SHIFT_END_HOUR.morning) return 'morning';
  if (hour < SHIFT_END_HOUR.afternoon) return 'afternoon';
  return 'evening';
}

// ---------- 零用金設定 ----------
export async function getCashFloat(db) {
  const row = await db.first('SELECT value FROM app_settings WHERE key = ?', FLOAT_KEY);
  return row ? fromCents(toCents(row.value)) : null;
}

export async function setCashFloat(db, amount) {
  const cents = toCents(amount);
  if (cents < 0) throw new CashError('固定零用金不能是負數');
  const text = (cents / 100).toFixed(2); // 原本存 str(Decimal)，例如 '3000.00'
  await db.run(`INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = ${NOW_SQL}`, FLOAT_KEY, text);
  return fromCents(cents);
}

// ---------- 區間與金額 ----------
export const latestActiveClosing = (db) => db.first('SELECT * FROM cash_closings WHERE voided_at IS NULL ORDER BY closed_at DESC, id DESC LIMIT 1');

async function openInterval(db, businessDate) {
  const prev = await latestActiveClosing(db);
  if (prev) return [prev.closed_at, toCents(prev.remaining_cash)];
  const flt = await getCashFloat(db);
  if (flt === null) throw new CashError('請店長先在「對帳」頁設定每天固定留在抽屜的零用金，才能開始結帳');
  return [dayStartUtc(businessDate), toCents(flt)];
}

const cashSalesCents = async (db, start, end) =>
  Number(await db.value(`SELECT coalesce(CAST(round(sum(amount * 100)) AS INTEGER), 0) FROM revenue_details WHERE created_at > ? AND created_at <= ? AND ${IS_CASH_SQL}`, start, end));

async function movementTotalsCents(db, start, end) {
  const rows = await db.all(`SELECT direction, coalesce(CAST(round(sum(amount * 100)) AS INTEGER), 0) AS c FROM cash_movements
    WHERE created_at > ? AND created_at <= ? AND voided_at IS NULL GROUP BY direction`, start, end);
  const t = Object.fromEntries(rows.map((r) => [r.direction, Number(r.c)]));
  return [t.in ?? 0, t.out ?? 0];
}

// ---------- 結帳 ----------
export function parseDenominations(raw) {
  const allowed = new Set(DENOMINATIONS.map(String));
  const clean = {};
  let total = 0;
  for (const [key0, count] of Object.entries(raw ?? {})) {
    const key = String(key0);
    if (!allowed.has(key)) throw new CashError(`不支援的面額：${key}`);
    if (typeof count === 'boolean' || (typeof count === 'number' && !Number.isInteger(count))) throw new CashError('張數必須是整數');
    const n = typeof count === 'number' ? count : (/^\s*-?\d+\s*$/.test(String(count)) ? Number(count) : NaN);
    if (!Number.isInteger(n)) throw new CashError('張數必須是整數');
    if (n < 0 || n > MAX_COUNT_PER_DENOMINATION) throw new CashError('張數必須介於 0 到 100000');
    if (n) { clean[key] = n; total += Number(key) * n; }
  }
  return [clean, total * 100];
}

export async function createClosing(db, { businessDate, shift, denominations, collectedAmount, note, closedById }) {
  if (!(shift in SHIFT_LABELS)) throw new CashError('班次不正確');
  if (businessDate > taipeiToday()) throw new CashError('不能替未來的日期結帳');
  const [countedMap, counted] = parseDenominations(denominations);
  const collected = toCents(collectedAmount);
  if (collected < 0) throw new CashError('收走金額不能是負數');
  if (collected > counted) throw new CashError('收走金額不能大於實點金額');
  const already = await db.first('SELECT id FROM cash_closings WHERE business_date = ? AND shift = ? AND voided_at IS NULL LIMIT 1', businessDate, shift);
  if (already) throw new CashError('這個班次已經結過帳了；如果點錯，請店長作廢後重新結帳');

  const closedAt = nowUtc();
  const [start, opening] = await openInterval(db, businessDate);
  const sales = await cashSalesCents(db, start, closedAt);
  const [mIn, mOut] = await movementTotalsCents(db, start, closedAt);
  const expected = opening + sales + mIn - mOut;
  const flt = await getCashFloat(db);
  try {
    return await db.first(`INSERT INTO cash_closings (business_date, shift, interval_start, closed_at, opening_cash, cash_sales, movements_in, movements_out,
        expected_cash, counted_cash, denominations, variance, collected_amount, remaining_cash, cash_float_snapshot, note, closed_by_id)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING *`,
    businessDate, shift, start, closedAt, fromCents(opening), fromCents(sales), fromCents(mIn), fromCents(mOut), fromCents(expected), fromCents(counted),
    pyDumps(countedMap), fromCents(counted - expected), fromCents(collected), fromCents(counted - collected), flt ?? 0,
    String(note ?? '').trim() || null, closedById);
  } catch (error) {
    if (/UNIQUE constraint failed/.test(error.message)) throw new CashError('這個班次已經結過帳了；如果點錯，請店長作廢後重新結帳');
    throw error;
  }
}

export const varianceStatus = (c) => { const v = toCents(c.variance); return v === 0 ? 'balanced' : v < 0 ? 'short' : 'over'; };
const floatMismatch = (c) => toCents(c.collected_amount) > 0 && toCents(c.remaining_cash) !== toCents(c.cash_float_snapshot);

/** 用現在的帳重算同一個區間，跟結帳當下的快照比對 */
export async function recomputeLive(db, c) {
  const [sales, [mIn, mOut]] = await Promise.all([cashSalesCents(db, c.interval_start, c.closed_at), movementTotalsCents(db, c.interval_start, c.closed_at)]);
  const expected = toCents(c.opening_cash) + sales + mIn - mOut;
  const delta = expected - toCents(c.expected_cash);
  return { cash_sales: fromCents(sales), movements_in: fromCents(mIn), movements_out: fromCents(mOut), expected_cash: fromCents(expected), changed: Math.abs(delta) >= 1, delta: fromCents(delta) };
}

export async function setNote(db, id, user, note) {
  const c = await db.first('SELECT * FROM cash_closings WHERE id = ?', id);
  if (!c || c.voided_at) throw new CashError('找不到這筆結帳');
  const isManager = ['manager', 'super_admin'].includes(user.role);
  if (!isManager && (c.closed_by_id !== user.id || c.note)) throw new CashError('沒有權限修改說明');
  const text = String(note ?? '').trim();
  if (!text) throw new CashError('說明不能是空白');
  await db.run(`UPDATE cash_closings SET note = ?, updated_at = ${NOW_SQL} WHERE id = ?`, text, id);
}

export async function reviewClosing(db, id, userId, note) {
  const c = await db.first('SELECT * FROM cash_closings WHERE id = ?', id);
  if (!c || c.voided_at) throw new CashError('找不到這筆結帳');
  await db.run(`UPDATE cash_closings SET reviewed_at = ?, reviewed_by_id = ?, review_note = ?, updated_at = ${NOW_SQL} WHERE id = ?`, nowUtc(), userId, String(note ?? '').trim() || null, id);
}

export async function voidClosing(db, id, userId, reason) {
  const c = await db.first('SELECT * FROM cash_closings WHERE id = ?', id);
  if (!c) throw new CashError('找不到這筆結帳');
  if (c.voided_at) throw new CashError('這筆結帳已經作廢了');
  const why = String(reason ?? '').trim();
  if (!why) throw new CashError('作廢必須填寫原因');
  const latest = await latestActiveClosing(db);
  if (!latest || latest.id !== c.id) throw new CashError('只能作廢最新的一筆結帳（之後的結帳是接在它後面算的）');
  await db.run(`UPDATE cash_closings SET voided_at = ?, voided_by_id = ?, void_reason = ?, updated_at = ${NOW_SQL} WHERE id = ?`, nowUtc(), userId, why, id);
}

// ---------- 現金異動 ----------
export async function createMovement(db, { entryDate, movementType, amount, counterparty, description, enteredById }) {
  if (!(movementType in MOVEMENT_DIRECTIONS)) throw new CashError('異動類型不正確');
  const cents = toCents(amount);
  if (cents <= 0) throw new CashError('金額必須大於 0');
  const desc = String(description ?? '').trim();
  if (!desc) throw new CashError('請填寫用途或原因（日後查帳要用）');
  if (entryDate > taipeiToday()) throw new CashError('日期不能是未來');
  return db.first(`INSERT INTO cash_movements (entry_date, movement_type, direction, amount, counterparty, description, entered_by_id)
    VALUES (?, ?, ?, ?, ?, ?, ?) RETURNING *`, entryDate, movementType, MOVEMENT_DIRECTIONS[movementType], fromCents(cents), String(counterparty ?? '').trim() || null, desc, enteredById);
}

export async function voidMovement(db, id, userId, reason) {
  const m = await db.first('SELECT * FROM cash_movements WHERE id = ?', id);
  if (!m) throw new CashError('找不到這筆異動');
  if (m.voided_at) throw new CashError('這筆異動已經作廢了');
  const why = String(reason ?? '').trim();
  if (!why) throw new CashError('作廢必須填寫原因');
  await db.run(`UPDATE cash_movements SET voided_at = ?, voided_by_id = ?, void_reason = ?, updated_at = ${NOW_SQL} WHERE id = ?`, nowUtc(), userId, why, id);
}

export const movementsForDate = (db, date) => db.all('SELECT * FROM cash_movements WHERE entry_date = ? ORDER BY created_at DESC, id DESC', date);

export async function counterpartySuggestions(db) {
  const coaches = (await db.all("SELECT name FROM members WHERE role = 'coach' ORDER BY id")).map((r) => r.name);
  const venue = (await db.all('SELECT name FROM venue_rental_coaches WHERE is_active = 1 ORDER BY id')).map((r) => r.name);
  return [...new Set([...coaches, ...venue])];
}

export async function usernames(db) {
  return Object.fromEntries((await db.all('SELECT id, username FROM admin_users')).map((u) => [u.id, u.username]));
}

// ---------- 明細與總覽 ----------
export async function closingDetail(db, c) {
  const start = c.interval_start;
  const end = c.closed_at;
  const sales = await db.all(`SELECT * FROM revenue_details WHERE created_at > ? AND created_at <= ? AND ${IS_CASH_SQL} ORDER BY created_at, id`, start, end);
  const saleRows = sales.map((e) => ({ entry: e, created_local: e.created_at, backfilled: e.entry_date !== taipeiDate(e.created_at) }));
  const movements = await db.all('SELECT * FROM cash_movements WHERE created_at > ? AND created_at <= ? ORDER BY created_at, id', start, end);
  const endMs = parseInstant(end);
  const movementRows = movements.map((m) => ({ movement: m, created_local: m.created_at, voided_after_close: Boolean(m.voided_at && parseInstant(m.voided_at) > endMs) }));
  const methodRows = await db.all('SELECT payment_method, count(id) AS n FROM revenue_details WHERE created_at > ? AND created_at <= ? GROUP BY payment_method ORDER BY payment_method', start, end);
  const other = {};
  for (const r of methodRows) if (!isCash(r.payment_method)) other[r.payment_method] = r.n;
  const nonstandard = Object.keys(other).filter((m) => !STANDARD_PAYMENT_METHODS.includes(String(m ?? '').trim().toLowerCase())).sort();
  return { sale_rows: saleRows, movement_rows: movementRows, non_cash_methods: other, nonstandard_methods: nonstandard, live: await recomputeLive(db, c), float_mismatch: floatMismatch(c) };
}

export async function dayStatus(db, date) {
  const rows = await db.all('SELECT * FROM cash_closings WHERE business_date = ? AND voided_at IS NULL', date);
  const byShift = Object.fromEntries(rows.map((r) => [r.shift, r]));
  return Object.fromEntries(SHIFT_ORDER.map((s) => [s, byShift[s] ?? null]));
}

export async function overview(db, startDate, endDate) {
  const closings = await db.all('SELECT * FROM cash_closings WHERE business_date >= ? AND business_date <= ? AND voided_at IS NULL ORDER BY business_date DESC, closed_at', startDate, endDate);
  const byDay = new Map();
  for (const c of closings) { if (!byDay.has(c.business_date)) byDay.set(c.business_date, {}); byDay.get(c.business_date)[c.shift] = c; }
  const revenueDays = new Set((await db.all('SELECT DISTINCT entry_date FROM revenue_details WHERE entry_date >= ? AND entry_date <= ?', startDate, endDate)).map((r) => r.entry_date));

  const now = taipeiParts(nowMs());
  const today = taipeiToday();
  const days = [];
  let short = 0; let over = 0; let unbalanced = 0; let missing = 0; let changed = 0; let unreviewed = 0;
  // 每一筆結帳的重算同時送出（一個月約 90 筆，逐筆查會很慢）
  const lives = new Map(await Promise.all(closings.map(async (c) => [c.id, await recomputeLive(db, c)])));
  for (let d = endDate; d >= startDate; d = addDays(d, -1)) {
    if (!byDay.has(d) && !revenueDays.has(d)) continue;
    const shifts = {};
    for (const shift of SHIFT_ORDER) {
      const c = byDay.get(d)?.[shift];
      if (c) {
        const live = lives.get(c.id);
        const v = toCents(c.variance);
        if (v < 0) short += -v; else if (v > 0) over += v;
        if (v !== 0) { unbalanced += 1; if (!c.reviewed_at) unreviewed += 1; }
        if (live.changed) changed += 1;
        shifts[shift] = { closing: c, status: varianceStatus(c), live_changed: live.changed };
      } else {
        const due = d < today || (d === today && now.hour >= SHIFT_END_HOUR[shift]);
        const isMissing = revenueDays.has(d) && due;
        if (isMissing) missing += 1;
        shifts[shift] = { closing: null, status: isMissing ? 'missing' : 'none', live_changed: false };
      }
    }
    days.push({ date: d, shifts });
  }
  return { days, total_short: fromCents(short), total_over: fromCents(over), unbalanced_count: unbalanced, missing_count: missing, changed_count: changed, unreviewed_count: unreviewed };
}
