// 後台（對應 app/routers/admin/*.py）。權限規則照原本：require_role 列出的角色＋super_admin。
import { Hono } from 'hono';
import { currentAdmin, requireRole, verifyPassword } from '../lib/auth.js';
import { HttpError, fail, parseBody, pathId, queryParam, readJson } from '../lib/http.js';
import { clearSession, writeSession } from '../lib/session.js';
import { addDays, isDate, monthBounds, monthWeeks, nowMs, pad, taipeiParts, taipeiToday } from '../lib/time.js';
import { fromCents, money } from '../lib/money.js';
import { pyDumps, PyFloat } from '../lib/pyjson.js';
import { render } from '../render.js';
import { buildDayGrid, bookingOut, cancelBooking, cancelVenueBooking, createBooking, createVenueBooking } from '../services/bookings.js';
import { activeContractsForCoach, contractOut, createClassRecord, createContract, membersForContract, membersForContracts } from '../services/contracts.js';
import {
  ADMIN_ROLE_LABELS, ITEM_CATEGORIES, adminAccountOut, assignShift, bindingCodeOut, createAdminAccount, generateBindingCode,
  itemOut, itemsGrouped, listActiveItems, listVenueCoaches, publishMonth, removeScheduleEntry, scheduleOut, venueCoachOut,
} from '../services/people.js';
import { CATEGORY_LABELS, coachClassCounts, createRevenueEntry, dailySummary, monthlyEntries, monthlySummary, paymentMethodSuggestions, revenueOut } from '../services/revenue.js';
import * as cash from '../services/cash.js';
import { runImport } from '../services/legacy.js';
import { unlinkRichMenu } from '../lib/line.js';

const NOW_SQL = "strftime('%Y-%m-%dT%H:%M:%f000Z','now')";
export const admin = new Hono();

// 品項價格在頁面 JSON 裡是 Python float（1500.0）
const itemsJson = async (db) => {
  const grouped = await itemsGrouped(db);
  for (const list of Object.values(grouped)) for (const it of list) it.price = it.price === null ? null : new PyFloat(it.price);
  return pyDumps(grouped);
};

// ---------- 登入 ----------
admin.get('/login', (c) => render(c, 'admin/login.html', { denied: Boolean(Number(c.req.query('denied') ?? 0)), error: null }));

admin.post('/login', async (c) => {
  const form = await c.req.parseBody().catch(() => ({}));
  const username = typeof form.username === 'string' ? form.username : null;
  const password = typeof form.password === 'string' ? form.password : null;
  if (username === null || password === null) fail(422, [{ type: 'missing', loc: ['body', username === null ? 'username' : 'password'], msg: 'Field required' }]);
  const user = await c.get('db').first('SELECT * FROM admin_users WHERE username = ? LIMIT 1', username);
  if (!user || !user.is_active || !(await verifyPassword(password, user.password_hash))) {
    return render(c, 'admin/login.html', { denied: false, error: '帳號或密碼錯誤' }, 401);
  }
  await writeSession(c, c.env.SESSION_SECRET_KEY, { admin_user_id: user.id });
  return c.redirect('/admin', 303);
});

admin.post('/logout', (c) => { clearSession(c); return c.redirect('/admin/login', 303); });

// ---------- 總覽 ----------
export async function dashboard(c) {
  const user = await currentAdmin(c);
  const db = c.get('db');
  const today = taipeiToday();
  const d = c.req.query('d');
  if (d !== undefined && d !== '' && !isDate(d)) fail(500, 'Internal Server Error');
  const target = d ? d : today;
  const p = taipeiParts(nowMs());
  const canWork = ['manager', 'front_desk', 'super_admin'].includes(user.role);
  // 彼此無關的查詢同時送出
  const [daily, monthly, courseCount, venueCount, cashCents, grid, venueRows, entries, itemsJs, payments, shiftStatus] = await Promise.all([
    dailySummary(db, today),
    monthlySummary(db, p.year, p.month),
    db.value("SELECT count(*) FROM bookings WHERE slot_date = ? AND status <> 'cancelled'", today),
    db.value("SELECT count(*) FROM venue_bookings WHERE slot_date = ? AND status <> 'cancelled'", today),
    db.value(`SELECT coalesce(CAST(round(sum(amount * 100)) AS INTEGER), 0) FROM revenue_details WHERE entry_date = ? AND ${cash.IS_CASH_SQL}`, today),
    buildDayGrid(db, target),
    db.all('SELECT id, name FROM venue_rental_coaches WHERE is_active = 1 ORDER BY name, id'),
    canWork ? db.all('SELECT * FROM revenue_details WHERE entry_date = ? ORDER BY id DESC', today) : null,
    canWork ? itemsJson(db) : null,
    canWork ? paymentMethodSuggestions(db) : null,
    canWork ? cash.dayStatus(db, today) : null,
  ]);
  const todayBookings = Number(courseCount) + Number(venueCount);
  const todayCash = Number(cashCents) / 100;
  const contractOptions = Object.fromEntries(grid.columns.map((col) => [String(col.coach_id), col.contract_options]));
  const venueOptions = venueRows.map((v) => ({ id: v.id, name: v.name }));
  const workbench = canWork ? {
    today,
    items_by_category_json: itemsJs,
    payment_method_suggestions: payments,
    today_entries: entries.slice(0, 8),
    today_entry_count: entries.length,
    category_labels: CATEGORY_LABELS,
    shift_status: shiftStatus,
    current_shift: cash.currentShift(),
  } : {};
  return render(c, 'admin/dashboard.html', {
    current_user: user, active: 'dashboard', can_work: canWork, ...workbench,
    today_revenue: daily.total, month_revenue: monthly.total, today_booking_count: todayBookings, today_cash_sales: todayCash,
    target_date: target, prev_date: addDays(target, -1), next_date: addDays(target, 1), is_today: target === today,
    hours: grid.hours, columns: grid.columns, venue_columns: grid.venue_columns, pilates_cells: grid.pilates_cells,
    contract_options_json: pyDumps(contractOptions), venue_coach_options_json: pyDumps(venueOptions), pilates_contract_options_json: pyDumps(grid.pilates_contract_options),
  });
}

// ---------- 帳號 ----------
admin.get('/accounts/page', async (c) => {
  const user = await requireRole(c, 'super_admin');
  const accounts = await c.get('db').all('SELECT * FROM admin_users ORDER BY created_at DESC, id DESC');
  return render(c, 'admin/accounts.html', { current_user: user, active: 'accounts', accounts, role_labels: ADMIN_ROLE_LABELS });
});
admin.post('/accounts', async (c) => {
  await requireRole(c, 'super_admin');
  const p = parseBody(await readJson(c), { username: 'str', password: 'str', role: 'str', linked_member_id: 'int?' });
  return c.json(adminAccountOut(await createAdminAccount(c.get('db'), p)));
});
admin.post('/accounts/:id/deactivate', async (c) => {
  const user = await requireRole(c, 'super_admin');
  const id = pathId(c, 'id');
  if (id === user.id) fail(400, '不能停用自己的帳號');
  const meta = await c.get('db').run(`UPDATE admin_users SET is_active = 0, updated_at = ${NOW_SQL} WHERE id = ?`, id);
  if (!meta.changes) fail(404, '找不到這個帳號');
  return c.json({ status: 'success' });
});
admin.post('/accounts/:id/activate', async (c) => {
  await requireRole(c, 'super_admin');
  const meta = await c.get('db').run(`UPDATE admin_users SET is_active = 1, updated_at = ${NOW_SQL} WHERE id = ?`, pathId(c, 'id'));
  if (!meta.changes) fail(404, '找不到這個帳號');
  return c.json({ status: 'success' });
});

// ---------- 約課 ----------
admin.post('/bookings', async (c) => {
  await currentAdmin(c);
  const db = c.get('db');
  const p = parseBody(await readJson(c), { coach_id: 'int?', contract_id: 'int', slot_date: 'date', slot_start_time: 'time' });
  const contract = await db.first('SELECT * FROM contracts WHERE id = ?', p.contract_id);
  if (!contract) fail(404, '找不到合約');
  const b = await createBooking(db, { coachId: p.coach_id, contractId: p.contract_id, slotDate: p.slot_date, slotTime: p.slot_start_time, area: contract.course_type, createdById: p.coach_id });
  return c.json(bookingOut(b));
});
admin.post('/bookings/:id/cancel', async (c) => {
  await currentAdmin(c);
  return c.json(bookingOut(await cancelBooking(c.get('db'), pathId(c, 'id'))));
});
admin.post('/venue-bookings', async (c) => {
  await currentAdmin(c);
  const p = parseBody(await readJson(c), { venue_coach_id: 'int', customer_name: 'str', party_size: ['int', 1], area: ['str', 'strength'], slot_date: 'date', slot_start_time: 'time', slot_number: 'int', customer_phone: 'str?' });
  const b = await createVenueBooking(c.get('db'), p);
  return c.json({ status: 'success', id: b.id });
});
admin.post('/venue-bookings/:id/cancel', async (c) => {
  await currentAdmin(c);
  await cancelVenueBooking(c.get('db'), pathId(c, 'id'));
  return c.json({ status: 'success' });
});

// ---------- 會員 ----------
const PAGE_SIZE = 50;
const memberOut = (m) => ({ id: m.id, member_no: m.member_no, name: m.name, role: m.role, membership_start_date: m.membership_start_date, membership_active_until: m.membership_active_until });

admin.get('/members/page', async (c) => {
  const user = await requireRole(c, 'manager', 'front_desk');
  const db = c.get('db');
  const q = c.req.query('q') ?? null;
  let page = queryParam(c, 'page', 'int', 1);
  const where = q ? 'WHERE name LIKE ?1 OR member_no LIKE ?1' : '';
  const args = q ? [`%${q}%`] : [];
  const total = Number(await db.value(`SELECT count(*) FROM members ${where}`, ...args));
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  page = Math.min(Math.max(page, 1), pages);
  const members = await db.all(`SELECT * FROM members ${where} ORDER BY created_at DESC, id DESC LIMIT ${PAGE_SIZE} OFFSET ${(page - 1) * PAGE_SIZE}`, ...args);
  return render(c, 'admin/members.html', { current_user: user, active: 'members', members, q: q ?? '', page, pages, total });
});
admin.post('/members', async (c) => {
  await requireRole(c, 'manager', 'front_desk');
  const db = c.get('db');
  const p = parseBody(await readJson(c), { member_no: 'str', name: 'str', role: 'str', membership_start_date: 'date?', membership_active_until: 'date?' });
  if (!['student', 'coach'].includes(p.role)) fail(400, 'role 必須是 student 或 coach');
  if (await db.first('SELECT id FROM members WHERE member_no = ?', p.member_no)) fail(400, '會員編號已存在');
  const m = await db.first('INSERT INTO members (member_no, name, role, membership_start_date, membership_active_until) VALUES (?, ?, ?, ?, ?) RETURNING *',
    p.member_no, p.name, p.role, p.membership_start_date, p.membership_active_until);
  return c.json(memberOut(m));
});
admin.post('/members/:id/membership', async (c) => {
  await requireRole(c, 'manager', 'front_desk');
  const id = pathId(c, 'id');
  const p = parseBody(await readJson(c), { membership_start_date: 'date?', membership_active_until: 'date?' });
  const m = await c.get('db').first(`UPDATE members SET membership_start_date = ?, membership_active_until = ?, updated_at = ${NOW_SQL} WHERE id = ? RETURNING *`, p.membership_start_date, p.membership_active_until, id);
  if (!m) fail(404, '找不到會員');
  return c.json(memberOut(m));
});
admin.post('/members/:id/binding-code', async (c) => {
  const user = await requireRole(c, 'manager', 'front_desk');
  const id = pathId(c, 'id');
  const db = c.get('db');
  if (!await db.first('SELECT id FROM members WHERE id = ?', id)) fail(404, '找不到會員');
  return c.json(bindingCodeOut(await generateBindingCode(db, { memberId: id, createdByAdminId: user.id })));
});

// 解除 LINE 綁定：只清掉 LINE 帳號、選單退回通用版；身分（學員／教練）不變，之後可以再發綁定碼
admin.post('/members/:id/unbind', async (c) => {
  await requireRole(c, 'manager', 'front_desk');
  const db = c.get('db');
  const m = await db.first('SELECT id, line_user_id FROM members WHERE id = ?', pathId(c, 'id'));
  if (!m) fail(404, '找不到會員');
  if (m.line_user_id) {
    await db.run(`UPDATE members SET line_user_id = NULL, updated_at = ${NOW_SQL} WHERE id = ?`, m.id);
    await unlinkRichMenu(c.env, m.line_user_id);
  }
  return c.json({ status: 'success' });
});

// ---------- 合約 ----------
const VIEW_LABELS = { open: '還有剩餘堂數', done: '已上完', refunded: '已退費', all: '全部' };

admin.get('/contracts/page', async (c) => {
  const user = await requireRole(c, 'manager', 'front_desk');
  const db = c.get('db');
  let view = c.req.query('view') ?? 'open';
  if (!(view in VIEW_LABELS)) view = 'open';
  const course = c.req.query('course') ?? '';
  let page = queryParam(c, 'page', 'int', 1);
  const q = (c.req.query('q') ?? '').trim();

  const cond = [];
  const args = [];
  if (view === 'open') cond.push("c.status <> 'refunded' AND c.used_sessions < c.total_sessions");
  else if (view === 'done') cond.push("c.status <> 'refunded' AND c.used_sessions >= c.total_sessions");
  else if (view === 'refunded') cond.push("c.status = 'refunded'");
  if (course === 'strength' || course === 'pilates') { cond.push('c.course_type = ?'); args.push(course); }
  if (q) {
    cond.push(`(c.contract_no LIKE ? OR c.id IN (SELECT cm.contract_id FROM contract_members cm JOIN members m ON m.id = cm.member_id WHERE m.name LIKE ?)
      OR c.coach_id IN (SELECT id FROM members WHERE role = 'coach' AND name LIKE ?) OR c.venue_coach_id IN (SELECT id FROM venue_rental_coaches WHERE name LIKE ?))`);
    const like = `%${q}%`;
    args.push(like, like, like, like);
  }
  const where = cond.length ? `WHERE ${cond.join(' AND ')}` : '';
  const total = Number(await db.value(`SELECT count(*) FROM contracts c ${where}`, ...args));
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  page = Math.min(Math.max(page, 1), pages);
  const contracts = await db.all(`SELECT c.* FROM contracts c ${where} ORDER BY c.purchase_date DESC, c.id DESC LIMIT ${PAGE_SIZE} OFFSET ${(page - 1) * PAGE_SIZE}`, ...args);

  const ids = contracts.map((x) => x.id);
  const [coachRows, venueRows, students, sessionRows, studentList, venueCoaches] = await Promise.all([
    db.all("SELECT * FROM members WHERE role = 'coach' ORDER BY id"),
    db.all('SELECT id, name FROM venue_rental_coaches'),
    membersForContracts(db, ids),
    ids.length ? db.all(`SELECT * FROM contract_sessions WHERE contract_id IN (${ids.map(() => '?').join(',')}) ORDER BY session_no, id`, ...ids) : [],
    db.all("SELECT * FROM members WHERE role = 'student' ORDER BY name, id"),
    db.all('SELECT * FROM venue_rental_coaches WHERE is_active = 1 ORDER BY id'),
  ]);
  const coachNames = new Map(coachRows.map((m) => [m.id, m.name]));
  const venueNames = new Map(venueRows.map((v) => [v.id, v.name]));
  const sessions = new Map(ids.map((id) => [id, []]));
  for (const s of sessionRows) sessions.get(s.contract_id).push(s);
  const rows = contracts.map((x) => {
    const coachName = x.coach_id != null ? (coachNames.get(x.coach_id) ?? '未知') : `${venueNames.get(x.venue_coach_id) ?? '未知'}（場租）`;
    const list = sessions.get(x.id) ?? [];
    const dated = list.map((s) => s.session_date).filter(Boolean).sort();
    return {
      id: x.id, contract_no: x.contract_no, student_names: (students.get(x.id) ?? []).map((m) => m.name).join('、'), coach_name: coachName,
      course_type: x.course_type, status: x.status, total_sessions: x.total_sessions, used_sessions: x.used_sessions, purchase_date: x.purchase_date,
      expiry_date: x.expiry_date, unit_price: Number(x.unit_price), note: x.note, sessions: list, last_session: dated.length ? dated[dated.length - 1] : null,
    };
  });
  return render(c, 'admin/contracts.html', {
    current_user: user, active: 'contracts', contracts: rows, coaches: coachRows, venue_coaches: venueCoaches, students: studentList,
    q, view, course, view_labels: VIEW_LABELS, page, pages, total,
  });
});

admin.post('/contracts', async (c) => {
  await requireRole(c, 'manager', 'front_desk');
  const db = c.get('db');
  const p = parseBody(await readJson(c), {
    coach_id: 'int?', venue_coach_id: 'int?', member_ids: ['intList', () => []], course_type: ['str', 'strength'], purchase_date: 'date', unit_price: 'float',
    total_sessions: 'int', contract_no: 'str?', status: ['str', 'active'], expiry_date: 'date?', new_student_name: 'str?', new_student_phone: 'str?',
  });
  if ((p.coach_id == null) === (p.venue_coach_id == null)) fail(400, '請選擇一位教練');
  if (p.coach_id != null) {
    const coach = await db.first('SELECT * FROM members WHERE id = ?', p.coach_id);
    if (!coach || coach.role !== 'coach') fail(400, 'coach_id 不是有效的教練');
  } else if (!await db.first('SELECT id FROM venue_rental_coaches WHERE id = ?', p.venue_coach_id)) fail(400, 'venue_coach_id 不是有效的場租教練');
  if (p.member_ids.length) {
    const unique = [...new Set(p.member_ids)];
    const found = Number(await db.value(`SELECT count(*) FROM members WHERE id IN (${unique.map(() => '?').join(',')})`, ...unique));
    if (found !== unique.length) fail(400, 'member_ids 裡有不存在的會員');
  }
  if (!p.member_ids.length && !p.new_student_name) fail(400, '請至少選一位既有學員，或填新學員姓名');
  return c.json(contractOut(await createContract(db, p)));
});

// ---------- 紀錄課程 ----------
admin.get('/class-records/page', async (c) => {
  const user = await currentAdmin(c);
  const db = c.get('db');
  const coaches = await db.all("SELECT * FROM members WHERE role = 'coach' ORDER BY id");
  let selected;
  if (user.role === 'coach') {
    if (!user.linked_member_id) fail(400, '這個教練帳號尚未連結對應的會員資料，請聯絡店長設定');
    selected = user.linked_member_id;
  } else selected = queryParam(c, 'coach_id', 'int', null) || (coaches[0]?.id ?? null);
  const activeContracts = [];
  const recent = [];
  if (selected) {
    const list = await activeContractsForCoach(db, selected);
    const students = await membersForContracts(db, list.map((x) => x.id));
    for (const x of list) activeContracts.push({ contract_id: x.id, contract_no: x.contract_no, student_names: (students.get(x.id) ?? []).map((m) => m.name).join('、'), remaining_sessions: x.total_sessions - x.used_sessions });
    const records = await db.all('SELECT * FROM class_records WHERE actual_teaching_coach_id = ? ORDER BY class_date DESC, id DESC LIMIT 10', selected);
    const rs = await membersForContracts(db, [...new Set(records.map((r) => r.contract_id))]);
    for (const r of records) recent.push({ class_date: r.class_date, student_names: (rs.get(r.contract_id) ?? []).map((m) => m.name).join('、'), content_summary: r.content_summary });
  }
  return render(c, 'admin/class_records.html', {
    current_user: user, active: 'class-records', coaches, selected_coach_id: selected, is_coach_locked: user.role === 'coach',
    active_contracts: activeContracts, recent_records: recent, today: taipeiToday(),
  });
});
admin.post('/class-records', async (c) => {
  const user = await currentAdmin(c);
  const db = c.get('db');
  const p = parseBody(await readJson(c), { coach_id: 'int', contract_id: 'int', class_date: 'str', content_summary: 'str' });
  if (user.role === 'coach' && user.linked_member_id !== p.coach_id) fail(403, '只能記錄自己的課程');
  if (!await db.first('SELECT id FROM contracts WHERE id = ?', p.contract_id)) fail(404, '找不到合約');
  if (!Number(await db.value('SELECT count(*) FROM contract_members WHERE contract_id = ?', p.contract_id))) fail(400, '這份合約沒有任何學員，無法記錄課程');
  if (!isDate(p.class_date)) fail(500, 'Internal Server Error');
  try {
    const r = await createClassRecord(db, { contract_id: p.contract_id, actual_teaching_coach_id: p.coach_id, class_date: p.class_date, content_summary: p.content_summary, logged_by_id: p.coach_id });
    return c.json({ status: 'success', id: r.id });
  } catch (error) {
    if (/FOREIGN KEY constraint failed/.test(error.message)) fail(400, '找不到這位教練');
    throw error;
  }
});

// ---------- 排班 ----------
const SHIFT_ORDER = ['morning', 'afternoon', 'evening'];
const SHIFT_SHORT = { morning: '早', afternoon: '中', evening: '晚' };

admin.get('/schedule/page', async (c) => {
  const user = await requireRole(c, 'manager', 'front_desk');
  const db = c.get('db');
  const today = taipeiToday();
  const year = queryParam(c, 'year', 'int', null) || Number(today.slice(0, 4));
  const month = queryParam(c, 'month', 'int', null) || Number(today.slice(5, 7));
  if (month < 1 || month > 12) fail(500, 'Internal Server Error');
  const [start, end] = monthBounds(year, month);
  const entries = await db.all('SELECT * FROM schedules WHERE work_date >= ? AND work_date < ? ORDER BY work_date, shift, id', start, end);
  const coachNames = new Map((await db.all("SELECT id, name FROM members WHERE role = 'coach'")).map((m) => [m.id, m.name]));
  const adminNames = new Map((await db.all('SELECT id, username FROM admin_users WHERE is_active = 1')).map((a) => [a.id, a.username]));
  const byDay = {};
  for (const e of entries) {
    const assignee = e.coach_id ? coachNames.get(e.coach_id) : adminNames.get(e.admin_user_id);
    (byDay[e.work_date] ??= []).push({ id: e.id, shift_short: SHIFT_SHORT[e.shift] ?? e.shift, shift: e.shift, assignee: assignee || '未知', coach_id: e.coach_id, admin_user_id: e.admin_user_id, status: e.status });
  }
  for (const list of Object.values(byDay)) list.sort((a, b) => (SHIFT_ORDER.includes(a.shift) ? SHIFT_ORDER.indexOf(a.shift) : 99) - (SHIFT_ORDER.includes(b.shift) ? SHIFT_ORDER.indexOf(b.shift) : 99));
  const weeks = monthWeeks(year, month).map((week) => week.map((day) => ({ date: day, day: Number(day.slice(8)), in_month: Number(day.slice(5, 7)) === month, is_today: day === today, entries: byDay[day] ?? [] })));
  const coaches = await db.all("SELECT * FROM members WHERE role = 'coach' ORDER BY id");
  const staff = await db.all('SELECT * FROM admin_users WHERE is_active = 1 ORDER BY username, id');
  return render(c, 'admin/schedule.html', {
    current_user: user, active: 'schedule', today, year, month, weeks, coaches,
    prev_year: month === 1 ? year - 1 : year, prev_month: month === 1 ? 12 : month - 1, next_year: month === 12 ? year + 1 : year, next_month: month === 12 ? 1 : month + 1,
    schedule_by_day_json: pyDumps(byDay), coaches_json: pyDumps(coaches.map((x) => ({ id: x.id, name: x.name }))), staff_json: pyDumps(staff.map((a) => ({ id: a.id, name: a.username }))),
  });
});
admin.get('/schedule', async (c) => {
  await requireRole(c, 'manager', 'front_desk');
  const year = queryParam(c, 'year', 'int'); const month = queryParam(c, 'month', 'int');
  if (year === null || month === null) fail(422, [['year', year], ['month', month]].filter(([, v]) => v === null).map(([k]) => ({ type: 'missing', loc: ['query', k], msg: 'Field required', input: null })));
  const [start, end] = monthBounds(year, month);
  return c.json((await c.get('db').all('SELECT * FROM schedules WHERE work_date >= ? AND work_date < ? ORDER BY work_date, shift, id', start, end)).map(scheduleOut));
});
admin.post('/schedule', async (c) => {
  await requireRole(c, 'manager');
  const p = parseBody(await readJson(c), { work_date: 'date', shift: 'str', coach_id: 'int?', admin_user_id: 'int?' });
  return c.json(scheduleOut(await assignShift(c.get('db'), p)));
});
admin.post('/schedule/publish', async (c) => {
  await requireRole(c, 'manager');
  const p = parseBody(await readJson(c), { year: 'int', month: 'int' });
  if (p.month < 1 || p.month > 12) fail(500, 'Internal Server Error');
  return c.json({ status: 'success', published_count: await publishMonth(c.get('db'), p.year, p.month) });
});
admin.post('/schedule/:id/remove', async (c) => {
  await requireRole(c, 'manager');
  await removeScheduleEntry(c.get('db'), pathId(c, 'id'));
  return c.json({ status: 'success' });
});

// ---------- 場租教練 ----------
admin.get('/venue-coaches/page', async (c) => {
  const user = await requireRole(c, 'manager', 'front_desk');
  return render(c, 'admin/venue_coaches.html', { current_user: user, active: 'venue-coaches', coaches: await listVenueCoaches(c.get('db')) });
});
admin.post('/venue-coaches', async (c) => {
  await requireRole(c, 'manager', 'front_desk');
  const p = parseBody(await readJson(c), { name: 'str', phone: 'str?' });
  return c.json(venueCoachOut(await c.get('db').first('INSERT INTO venue_rental_coaches (name, phone) VALUES (?, ?) RETURNING *', p.name.trim(), p.phone)));
});
admin.post('/venue-coaches/:id', async (c) => {
  await requireRole(c, 'manager', 'front_desk');
  const id = pathId(c, 'id');
  const p = parseBody(await readJson(c), { name: 'str', phone: 'str?' });
  const v = await c.get('db').first(`UPDATE venue_rental_coaches SET name = ?, phone = ?, updated_at = ${NOW_SQL} WHERE id = ? RETURNING *`, p.name.trim(), p.phone, id);
  if (!v) fail(404, '找不到場租教練');
  return c.json(venueCoachOut(v));
});
for (const [action, active] of [['deactivate', 0], ['activate', 1]]) {
  admin.post(`/venue-coaches/:id/${action}`, async (c) => {
    await requireRole(c, 'manager', 'front_desk');
    const meta = await c.get('db').run(`UPDATE venue_rental_coaches SET is_active = ?, updated_at = ${NOW_SQL} WHERE id = ?`, active, pathId(c, 'id'));
    if (!meta.changes) fail(404, '找不到場租教練');
    return c.json({ status: 'success' });
  });
}
admin.post('/venue-coaches/:id/binding-code', async (c) => {
  const user = await requireRole(c, 'manager', 'front_desk');
  const id = pathId(c, 'id');
  const db = c.get('db');
  if (!await db.first('SELECT id FROM venue_rental_coaches WHERE id = ?', id)) fail(404, '找不到場租教練');
  return c.json(bindingCodeOut(await generateBindingCode(db, { venueCoachId: id, createdByAdminId: user.id })));
});

admin.post('/venue-coaches/:id/unbind', async (c) => {
  await requireRole(c, 'manager', 'front_desk');
  const db = c.get('db');
  const v = await db.first('SELECT id, line_user_id FROM venue_rental_coaches WHERE id = ?', pathId(c, 'id'));
  if (!v) fail(404, '找不到場租教練');
  if (v.line_user_id) {
    await db.run(`UPDATE venue_rental_coaches SET line_user_id = NULL, updated_at = ${NOW_SQL} WHERE id = ?`, v.id);
    await unlinkRichMenu(c.env, v.line_user_id);
  }
  return c.json({ status: 'success' });
});

// ---------- 營收 ----------
admin.get('/revenue/page', async (c) => {
  const user = await requireRole(c, 'manager');
  const db = c.get('db');
  const today = taipeiToday();
  const ty = Number(today.slice(0, 4)); const tm = Number(today.slice(5, 7));
  let year = queryParam(c, 'year', 'int', null); let month = queryParam(c, 'month', 'int', null);
  const ym = c.req.query('ym');
  if (ym && /^\d{4}-\d{2}$/.test(ym)) { year = Number(ym.slice(0, 4)); month = Number(ym.slice(5)); }
  if (!year || !month || month < 1 || month > 12 || year > ty || (year === ty && month > tm)) { year = ty; month = tm; }
  const isCurrent = year === ty && month === tm;
  const prevYm = month === 1 ? [year - 1, 12] : [year, month - 1];
  const nextYm = isCurrent ? null : (month === 12 ? [year + 1, 1] : [year, month + 1]);
  const tab = c.req.query('tab') ?? 'today';
  const [performance, coachRows, daily, monthly, todayEntries, monthEntries, itemsJs, payments] = await Promise.all([
    coachClassCounts(db, year, month), db.all("SELECT id, name FROM members WHERE role = 'coach'"), dailySummary(db, today), monthlySummary(db, year, month),
    db.all('SELECT * FROM revenue_details WHERE entry_date = ? ORDER BY id DESC', today), monthlyEntries(db, year, month), itemsJson(db), paymentMethodSuggestions(db),
  ]);
  const coachNames = new Map(coachRows.map((m) => [m.id, m.name]));
  return render(c, 'admin/revenue.html', {
    current_user: user, active: 'revenue', today, year, month, ym_value: `${pad(year, 4)}-${pad(month)}`,
    month_label: `${year - 1911} 年 ${month} 月`, is_current_month: isCurrent, prev_ym: prevYm, next_ym: nextYm,
    initial_tab: tab === 'month' || !isCurrent ? 'month' : 'today',
    daily, monthly,
    coach_performance: performance.map((r) => ({ coach_name: coachNames.get(r.coach_id) ?? '未知', strength_count: r.strength_count, pilates_count: r.pilates_count })),
    today_entries: todayEntries, month_entries: monthEntries, category_labels: CATEGORY_LABELS,
    items_by_category_json: itemsJs, payment_method_suggestions: payments,
  });
});
admin.post('/revenue', async (c) => {
  const user = await requireRole(c, 'manager', 'front_desk');
  const p = parseBody(await readJson(c), {
    entry_date: 'date', item_category: 'str', item_name: 'str', payment_method: 'str', amount: 'float',
    coach_id: 'int?', content: 'str?', contract_id: 'int?', remittance_last5: 'str?',
  });
  const last5 = String(p.remittance_last5 ?? '').trim();
  if (last5 && !/^\d{5}$/.test(last5)) fail(422, [{ type: 'value_error', loc: ['body', 'remittance_last5'], msg: 'Value error, 匯款末五碼必須是 5 位數字' }]);
  try {
    const r = await createRevenueEntry(c.get('db'), { ...p, remittance_last5: last5 || null, entered_by_id: user.id });
    return c.json(revenueOut(r));
  } catch (error) {
    if (/CHECK constraint failed/.test(error.message)) fail(500, 'Internal Server Error');
    if (/FOREIGN KEY constraint failed/.test(error.message)) fail(400, '教練或合約不存在');
    throw error;
  }
});
admin.get('/revenue/daily-summary', async (c) => {
  await requireRole(c, 'manager');
  const d = c.req.query('date');
  if (d === undefined) fail(422, [{ type: 'missing', loc: ['query', 'date'], msg: 'Field required', input: null }]);
  if (!isDate(d)) fail(500, 'Internal Server Error');
  return c.json(await dailySummary(c.get('db'), d));
});
admin.get('/revenue/monthly-summary', async (c) => {
  await requireRole(c, 'manager');
  const year = queryParam(c, 'year', 'int'); const month = queryParam(c, 'month', 'int');
  if (year === null || month === null) fail(422, [['year', year], ['month', month]].filter(([, v]) => v === null).map(([k]) => ({ type: 'missing', loc: ['query', k], msg: 'Field required', input: null })));
  if (month < 1 || month > 12) fail(500, 'Internal Server Error');
  return c.json(await monthlySummary(c.get('db'), year, month));
});
admin.get('/revenue/coach-performance', async (c) => {
  await requireRole(c, 'manager');
  const year = queryParam(c, 'year', 'int'); const month = queryParam(c, 'month', 'int');
  if (year === null || month === null) fail(422, [['year', year], ['month', month]].filter(([, v]) => v === null).map(([k]) => ({ type: 'missing', loc: ['query', k], msg: 'Field required', input: null })));
  if (month < 1 || month > 12) fail(500, 'Internal Server Error');
  return c.json(await coachClassCounts(c.get('db'), year, month));
});

// ---------- 品項設定 ----------
admin.get('/settings/items/page', async (c) => {
  const user = await requireRole(c, 'manager');
  return render(c, 'admin/settings_items.html', { current_user: user, active: 'settings', items: await listActiveItems(c.get('db')), category_labels: CATEGORY_LABELS });
});
admin.post('/settings/items', async (c) => {
  await requireRole(c, 'manager');
  const p = parseBody(await readJson(c), { item_category: 'str', item_name: 'str', default_price: 'float?' });
  if (!ITEM_CATEGORIES.includes(p.item_category)) fail(400, 'item_category 不合法');
  return c.json(itemOut(await c.get('db').first('INSERT INTO item_catalog_entries (item_category, item_name, default_price) VALUES (?, ?, ?) RETURNING *', p.item_category, p.item_name, p.default_price === null ? null : money(p.default_price))));
});
admin.post('/settings/items/:id', async (c) => {
  await requireRole(c, 'manager');
  const id = pathId(c, 'id');
  const p = parseBody(await readJson(c), { item_name: 'str?', default_price: 'float?' });
  const db = c.get('db');
  const cur = await db.first('SELECT * FROM item_catalog_entries WHERE id = ?', id);
  if (!cur) fail(404, '找不到這個品項');
  const row = await db.first(`UPDATE item_catalog_entries SET item_name = ?, default_price = ?, updated_at = ${NOW_SQL} WHERE id = ? RETURNING *`,
    p.item_name ?? cur.item_name, p.default_price === null ? null : money(p.default_price), id);
  return c.json(itemOut(row));
});
admin.post('/settings/items/:id/deactivate', async (c) => {
  await requireRole(c, 'manager');
  const meta = await c.get('db').run(`UPDATE item_catalog_entries SET is_active = 0, updated_at = ${NOW_SQL} WHERE id = ?`, pathId(c, 'id'));
  if (!meta.changes) fail(404, '找不到這個品項');
  return c.json({ status: 'success' });
});

// ---------- 現金對帳 ----------
const OPERATOR = ['manager', 'front_desk'];
const isManagerRole = (u) => ['manager', 'super_admin'].includes(u.role);

admin.get('/cash/page', async (c) => {
  const user = await requireRole(c, ...OPERATOR);
  const db = c.get('db');
  const today = taipeiToday();
  const isManager = isManagerRole(user);
  const [dayStatus, movements, counterparties, cashFloat, users, overview] = await Promise.all([
    cash.dayStatus(db, today), cash.movementsForDate(db, today), cash.counterpartySuggestions(db), cash.getCashFloat(db), cash.usernames(db),
    isManager ? cash.overview(db, addDays(today, -29), today) : null,
  ]);
  return render(c, 'admin/cash.html', {
    current_user: user, active: 'cash', is_manager: isManager, today, current_shift: cash.currentShift(),
    day_status: dayStatus, today_movements: movements, counterparty_suggestions: counterparties, cash_float: cashFloat,
    denominations: cash.DENOMINATIONS, users, overview,
  });
});
admin.post('/cash/closings', async (c) => {
  const user = await requireRole(c, ...OPERATOR);
  const p = parseBody(await readJson(c), { business_date: 'date', shift: 'str', denominations: ['dict', () => ({})], collected_amount: ['float', 0], note: 'str?' });
  for (const [k, v] of Object.entries(p.denominations)) {
    if (!(typeof v === 'number' && Number.isInteger(v)) && !(typeof v === 'string' && /^\s*-?\d+\s*$/.test(v))) fail(422, [{ type: 'int_parsing', loc: ['body', 'denominations', k], msg: 'Input should be a valid integer' }]);
  }
  const closing = await cash.createClosing(c.get('db'), { businessDate: p.business_date, shift: p.shift, denominations: p.denominations, collectedAmount: p.collected_amount, note: p.note, closedById: user.id });
  return c.json({ id: closing.id });
});
admin.get('/cash/closings/:id/page', async (c) => {
  const user = await requireRole(c, ...OPERATOR);
  const db = c.get('db');
  const closing = await db.first('SELECT * FROM cash_closings WHERE id = ?', pathId(c, 'id'));
  if (!closing) fail(404, '找不到這筆結帳');
  const isManager = isManagerRole(user);
  if (!isManager && closing.closed_by_id !== user.id) fail(403, '沒有權限');
  closing.denominations = JSON.parse(closing.denominations || '{}');
  const rows = Object.entries(closing.denominations).map(([d, n]) => [Number(d), n]).sort((a, b) => b[0] - a[0] || b[1] - a[1]);
  return render(c, 'admin/cash_closing.html', {
    current_user: user, active: 'cash', is_manager: isManager, closing, status: cash.varianceStatus(closing),
    detail: await cash.closingDetail(db, closing), denomination_rows: rows, users: await cash.usernames(db),
    can_add_note: isManager || (closing.closed_by_id === user.id && !closing.note),
  });
});
admin.post('/cash/closings/:id/note', async (c) => {
  const user = await requireRole(c, ...OPERATOR);
  const id = pathId(c, 'id');
  const p = parseBody(await readJson(c), { note: 'str' });
  await cash.setNote(c.get('db'), id, user, p.note);
  return c.json({ ok: true });
});
admin.post('/cash/closings/:id/review', async (c) => {
  const user = await requireRole(c, 'manager');
  const id = pathId(c, 'id');
  const p = parseBody(await readJson(c), { note: 'str?' });
  await cash.reviewClosing(c.get('db'), id, user.id, p.note);
  return c.json({ ok: true });
});
admin.post('/cash/closings/:id/void', async (c) => {
  const user = await requireRole(c, 'manager');
  const id = pathId(c, 'id');
  const p = parseBody(await readJson(c), { reason: 'str' });
  await cash.voidClosing(c.get('db'), id, user.id, p.reason);
  return c.json({ ok: true });
});
admin.post('/cash/movements', async (c) => {
  const user = await requireRole(c, ...OPERATOR);
  const p = parseBody(await readJson(c), { entry_date: 'date', movement_type: 'str', amount: 'float', counterparty: 'str?', description: 'str' });
  const m = await cash.createMovement(c.get('db'), { entryDate: p.entry_date, movementType: p.movement_type, amount: p.amount, counterparty: p.counterparty, description: p.description, enteredById: user.id });
  return c.json({ id: m.id });
});
admin.post('/cash/movements/:id/void', async (c) => {
  const user = await requireRole(c, 'manager');
  const id = pathId(c, 'id');
  const p = parseBody(await readJson(c), { reason: 'str' });
  await cash.voidMovement(c.get('db'), id, user.id, p.reason);
  return c.json({ ok: true });
});
admin.post('/cash/settings/float', async (c) => {
  await requireRole(c, 'manager');
  const p = parseBody(await readJson(c), { amount: 'float' });
  return c.json({ cash_float: await cash.setCashFloat(c.get('db'), p.amount) });
});

// ---------- 匯入舊資料 ----------
admin.get('/legacy-import/page', async (c) => {
  const user = await requireRole(c, 'super_admin');
  const db = c.get('db');
  const current = {
    members: Number(await db.value('SELECT count(id) FROM members')),
    contracts: Number(await db.value('SELECT count(id) FROM contracts')),
    revenue: Number(await db.value('SELECT count(id) FROM revenue_details')),
    imported: (await db.all('SELECT DISTINCT import_batch FROM members WHERE import_batch IS NOT NULL ORDER BY import_batch')).map((r) => r.import_batch),
  };
  return render(c, 'admin/legacy_import.html', { current_user: user, active: 'legacy-import', current });
});
admin.post('/legacy-import', async (c) => {
  await requireRole(c, 'super_admin');
  const form = await c.req.parseBody();
  const file = form.bundle;
  if (!file || typeof file === 'string') fail(422, [{ type: 'missing', loc: ['body', 'bundle'], msg: 'Field required' }]);
  let bytes = new Uint8Array(await file.arrayBuffer());
  if (bytes[0] === 0x1f && bytes[1] === 0x8b) bytes = new Uint8Array(await new Response(new Blob([bytes]).stream().pipeThrough(new DecompressionStream('gzip'))).arrayBuffer());
  let data;
  try { data = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)); } catch { fail(400, '檔案不是匯入用的 JSON'); }
  const commit = (form.mode ?? 'dryrun') === 'commit';
  if (commit && String(form.confirm ?? '').trim() !== '匯入') fail(400, '正式匯入前請在確認欄輸入「匯入」兩個字');
  const p = taipeiParts(nowMs());
  const batch = `legacy-${p.year}${pad(p.month)}${pad(p.day)}-${pad(p.hour)}${pad(p.minute)}`;
  const clear = /^(true|1|on|yes)$/i.test(String(form.clear_existing ?? 'false'));
  const report = await runImport(c.get('db'), data, { batch, clearExisting: clear, commit });
  report.issue_samples = (data.issues ?? []).slice(0, 300);
  return c.json(report);
});

// 原本的錯誤處理：HttpError → {"detail": …}；303 轉回登入頁
export function errorResponse(error) {
  if (error instanceof HttpError) {
    return new Response(JSON.stringify({ detail: error.detail }), { status: error.status, headers: { 'content-type': 'application/json', ...error.headers } });
  }
  return null;
}

export { fromCents };
