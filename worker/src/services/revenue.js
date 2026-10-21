// 對應 app/services/revenue_service.py
import { monthBounds } from '../lib/time.js';
import { fromCents, money, toCents } from '../lib/money.js';

export const CATEGORY_LABELS = { service: '服務', venue_rental: '場租', membership: '會籍', beverage: '飲料', coaching: '教練課', custom: '自訂項目' };
const COMMON_PAYMENT_METHODS = ['現金', '匯款', '信用卡', 'LinePay'];

// SQLite 的 sum 是浮點數；轉成分再加總，避免 0.1 + 0.2 這類誤差
const sumCents = "CAST(round(sum(amount * 100)) AS INTEGER)";

export async function createRevenueEntry(db, p) {
  return db.first(`INSERT INTO revenue_details (entry_date, item_category, item_name, coach_id, content, payment_method, remittance_last5, amount, contract_id, entered_by_id)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING *`,
  p.entry_date, p.item_category, p.item_name, p.coach_id ?? null, p.content ?? null, p.payment_method, p.remittance_last5 ?? null, money(p.amount), p.contract_id ?? null, p.entered_by_id);
}

export const revenueOut = (r) => ({
  id: r.id, entry_date: r.entry_date, item_category: r.item_category, item_name: r.item_name, coach_id: r.coach_id,
  payment_method: r.payment_method, remittance_last5: r.remittance_last5, amount: Number(r.amount),
});

const byCategory = (rows) => Object.fromEntries(rows.map((r) => [r.item_category, fromCents(r.c)]));
const total = (obj) => fromCents(Object.values(obj).reduce((s, v) => s + toCents(v), 0));

export async function dailySummary(db, date) {
  const rows = await db.all(`SELECT item_category, ${sumCents} AS c FROM revenue_details WHERE entry_date = ? GROUP BY item_category ORDER BY item_category`, date);
  const cats = byCategory(rows);
  return { entry_date: date, by_category: cats, total: total(cats) };
}

export async function monthlySummary(db, year, month) {
  const [start, end] = monthBounds(year, month);
  const [catRows, days] = await Promise.all([
    db.all(`SELECT item_category, ${sumCents} AS c FROM revenue_details WHERE entry_date >= ? AND entry_date < ? GROUP BY item_category ORDER BY item_category`, start, end),
    db.all(`SELECT entry_date, ${sumCents} AS c FROM revenue_details WHERE entry_date >= ? AND entry_date < ? GROUP BY entry_date ORDER BY entry_date`, start, end),
  ]);
  const cats = byCategory(catRows);
  return { year, month, by_category: cats, by_day: Object.fromEntries(days.map((d) => [d.entry_date, fromCents(d.c)])), total: total(cats) };
}

/** 教練帶課堂數：課程紀錄算實際帶課教練；舊「課堂報表」匯入的上課紀錄算合約登記的店內教練 */
export async function coachClassCounts(db, year, month) {
  const [start, end] = monthBounds(year, month);
  const rows = await db.all(`SELECT cr.actual_teaching_coach_id AS coach_id, c.course_type, count(cr.id) AS n
    FROM class_records cr JOIN contracts c ON c.id = cr.contract_id
    WHERE cr.class_date >= ? AND cr.class_date < ? GROUP BY cr.actual_teaching_coach_id, c.course_type ORDER BY cr.actual_teaching_coach_id, c.course_type`, start, end);
  const legacy = await db.all(`SELECT c.coach_id, c.course_type, count(s.id) AS n
    FROM contract_sessions s JOIN contracts c ON c.id = s.contract_id
    WHERE c.coach_id IS NOT NULL AND s.session_date >= ? AND s.session_date < ? GROUP BY c.coach_id, c.course_type ORDER BY c.coach_id, c.course_type`, start, end);
  const byCoach = new Map();
  for (const r of [...rows, ...legacy]) {
    if (!byCoach.has(r.coach_id)) byCoach.set(r.coach_id, { strength: 0, pilates: 0 });
    byCoach.get(r.coach_id)[r.course_type] += r.n;
  }
  return [...byCoach].map(([coachId, c]) => ({ coach_id: coachId, strength_count: c.strength, pilates_count: c.pilates }));
}

export async function monthlyEntries(db, year, month) {
  const [start, end] = monthBounds(year, month);
  return db.all('SELECT * FROM revenue_details WHERE entry_date >= ? AND entry_date < ? ORDER BY entry_date DESC, id DESC', start, end);
}

export async function paymentMethodSuggestions(db) {
  const used = (await db.all("SELECT payment_method FROM revenue_details WHERE payment_method IS NOT NULL AND payment_method <> '' GROUP BY payment_method ORDER BY min(id)")).map((r) => r.payment_method);
  return [...new Set([...used, ...COMMON_PAYMENT_METHODS])];
}
