// 對應 binding_service、schedule_service、item_catalog_service、venue_coach_service、admin_account_service
import { HttpError } from '../lib/http.js';
import { hashPassword } from '../lib/auth.js';
import { isoUtc, monthBounds, nowMs, nowUtc, parseInstant } from '../lib/time.js';
import { linkRichMenu, unlinkRichMenu } from '../lib/line.js';

const NOW_SQL = "strftime('%Y-%m-%dT%H:%M:%f000Z','now')";
export const ADMIN_ROLE_LABELS = { super_admin: '超級管理者', manager: '店長', front_desk: '櫃檯', coach: '教練' };
export const ITEM_CATEGORIES = ['service', 'venue_rental', 'membership', 'beverage', 'coaching', 'custom'];
export const SHIFT_LABELS = { morning: '早班 09:00-13:00', afternoon: '中班 13:00-18:00', evening: '晚班 18:00-22:00' };

// ---------- 綁定碼 ----------
const BINDING_CODE_TTL_MINUTES = 30;
export class BindingError extends HttpError { constructor(msg) { super(400, msg); } }

function randomCode() {
  const n = crypto.getRandomValues(new Uint32Array(1))[0] % 1_000_000;
  return String(n).padStart(6, '0');
}

// 學員分類（role 都是 student）：
//   student       學員：有店內正職教練的課程合約
//   membership    會員：沒有店內教練課，但有會籍起訖日
//   venue_student 場租學生：只跟場租教練上課 → 不能綁定 LINE
export const MEMBER_KIND_SQL = `CASE WHEN m.role = 'coach' THEN 'coach'
  WHEN EXISTS (SELECT 1 FROM contract_members cm JOIN contracts c ON c.id = cm.contract_id WHERE cm.member_id = m.id AND c.coach_id IS NOT NULL) THEN 'student'
  WHEN m.membership_start_date IS NOT NULL OR m.membership_active_until IS NOT NULL THEN 'membership'
  WHEN EXISTS (SELECT 1 FROM contract_members cm JOIN contracts c ON c.id = cm.contract_id WHERE cm.member_id = m.id AND c.venue_coach_id IS NOT NULL) THEN 'venue_student'
  ELSE 'student' END`;
export const memberKind = async (db, memberId) => (await db.first(`SELECT ${MEMBER_KIND_SQL} AS kind FROM members m WHERE m.id = ?`, memberId))?.kind ?? null;
export const VENUE_STUDENT_MSG = '場租學生不提供 LINE 綁定';

export async function generateBindingCode(db, { memberId = null, venueCoachId = null, createdByAdminId = null }) {
  if (memberId != null && await memberKind(db, memberId) === 'venue_student') throw new BindingError(VENUE_STUDENT_MSG);
  if ((memberId == null) === (venueCoachId == null)) throw new BindingError('member_id 跟 venue_coach_id 必須恰好指定一個');
  const target = memberId != null ? ['member_id', memberId] : ['venue_coach_id', venueCoachId];
  const expires = isoUtc(new Date(nowMs() + BINDING_CODE_TTL_MINUTES * 60_000));
  // 同一個對象還有其他有效碼就先作廢，再建新的（同一批寫入）
  const [, inserted] = await db.batch([
    db.prep(`UPDATE binding_codes SET status = 'revoked', updated_at = ${NOW_SQL} WHERE status = 'active' AND ${target[0]} = ?`, [target[1]]),
    db.prep(`INSERT INTO binding_codes (code, member_id, venue_coach_id, status, expires_at, created_by_admin_id) VALUES (?, ?, ?, 'active', ?, ?) RETURNING *`,
      [randomCode(), memberId, venueCoachId, expires, createdByAdminId]),
  ]);
  return inserted.results[0];
}

export const bindingCodeOut = (b) => ({ code: b.code, status: b.status, expires_at: b.expires_at });

export async function redeemBindingCode(db, env, { code, lineUserId }) {
  const binding = await db.first("SELECT * FROM binding_codes WHERE code = ? AND status = 'active' ORDER BY created_at DESC, id DESC LIMIT 1", code);
  if (!binding) throw new BindingError('綁定碼不存在或已失效，請跟店家索取新的綁定碼');
  if (parseInstant(binding.expires_at) < nowMs()) {
    await db.run(`UPDATE binding_codes SET status = 'expired', updated_at = ${NOW_SQL} WHERE id = ?`, binding.id);
    throw new BindingError('綁定碼已過期，請跟店家重新產生一組');
  }
  if (binding.member_id != null && await memberKind(db, binding.member_id) === 'venue_student') throw new BindingError(VENUE_STUDENT_MSG);
  const now = nowUtc();
  const table = binding.member_id != null ? 'members' : 'venue_rental_coaches';
  const targetId = binding.member_id ?? binding.venue_coach_id;
  let results;
  try {
    results = await db.batch([
      db.prep(`UPDATE binding_codes SET status = 'used', used_at = ?, updated_at = ${NOW_SQL} WHERE id = ?`, [now, binding.id]),
      db.prep(`UPDATE ${table} SET line_user_id = ?, updated_at = ${NOW_SQL} WHERE id = ? RETURNING *`, [lineUserId, targetId]),
    ]);
  } catch (error) {
    if (/UNIQUE constraint failed/.test(error.message)) throw new BindingError('這個 LINE 帳號已經綁定過其他身分');
    throw error;
  }
  const target = results[1].results[0];
  // 學員 → 學員版；會員（只買會籍）→ 會籍學員版；教練 → 教練版；場租教練 → 場租教練版
  const menuRole = binding.member_id != null ? await memberKind(db, target.id) : 'venue_coach';
  const menu = richMenuIdForRole(env, menuRole);
  if (menu) await linkRichMenu(env, lineUserId, menu);
  return { target, role: binding.member_id != null ? target.role : null };
}

// 角色 → 圖文選單（原本讀 settings.line_rich_menu_id_*，目前都沒設定，所以不會切換）
function richMenuIdForRole(env, role) {
  const key = { null: 'LINE_RICH_MENU_ID_DEFAULT', student: 'LINE_RICH_MENU_ID_MEMBER', membership: 'LINE_RICH_MENU_ID_MEMBERSHIP', coach: 'LINE_RICH_MENU_ID_COACH', venue_coach: 'LINE_RICH_MENU_ID_VENUE_COACH' }[String(role)];
  return key ? env[key] || null : null;
}

export async function unbindMember(db, env, memberId) {
  const member = await db.first('SELECT * FROM members WHERE id = ?', memberId);
  if (!member || !member.line_user_id) return;
  await db.run(`UPDATE members SET line_user_id = NULL, role = NULL, updated_at = ${NOW_SQL} WHERE id = ?`, memberId);
  await unlinkRichMenu(env, member.line_user_id);
}

export async function expireStaleCodes(db) {
  const meta = await db.run(`UPDATE binding_codes SET status = 'expired', updated_at = ${NOW_SQL} WHERE status = 'active' AND expires_at < ?`, nowUtc());
  return meta.changes ?? 0;
}

// ---------- 排班 ----------
export class ScheduleError extends HttpError { constructor(msg, status = 400) { super(status, msg); } }

export async function assignShift(db, { work_date: workDate, shift, coach_id: coachId, admin_user_id: adminUserId }) {
  if ((coachId == null) === (adminUserId == null)) throw new ScheduleError('coach_id 跟 admin_user_id 必須恰好指定一個');
  try {
    return await db.first("INSERT INTO schedules (work_date, shift, coach_id, admin_user_id, status) VALUES (?, ?, ?, ?, 'draft') RETURNING *", workDate, shift, coachId, adminUserId);
  } catch (error) {
    if (/CHECK constraint failed/.test(error.message)) throw new ScheduleError('班次不正確');
    if (/FOREIGN KEY constraint failed/.test(error.message)) throw new ScheduleError('找不到這位人員');
    throw error;
  }
}

export async function removeScheduleEntry(db, id) {
  const meta = await db.run('DELETE FROM schedules WHERE id = ?', id);
  if (!meta.changes) throw new ScheduleError('找不到這筆排班', 404);
}

export async function publishMonth(db, year, month) {
  const [start, end] = monthBounds(year, month);
  const meta = await db.run(`UPDATE schedules SET status = 'published', updated_at = ${NOW_SQL} WHERE work_date >= ? AND work_date < ? AND status = 'draft'`, start, end);
  return meta.changes ?? 0;
}

export async function publishedSchedule(db, year, month) {
  const [start, end] = monthBounds(year, month);
  return db.all("SELECT * FROM schedules WHERE work_date >= ? AND work_date < ? AND status = 'published' ORDER BY work_date, shift, id", start, end);
}

export async function submitUnavailability(db, { coachId, targetMonth, entries }) {
  const now = nowUtc();
  const statements = [db.prep('DELETE FROM coach_unavailabilities WHERE coach_id = ? AND target_month = ?', [coachId, targetMonth])];
  for (const e of entries) {
    statements.push(db.prep('INSERT INTO coach_unavailabilities (coach_id, target_month, unavailable_date, shift, note, submitted_at) VALUES (?, ?, ?, ?, ?, ?)',
      [coachId, targetMonth, e.unavailable_date, e.shift, e.note ?? null, now]));
  }
  try { await db.batch(statements); } catch (error) {
    if (/CHECK constraint failed/.test(error.message)) throw new ScheduleError('班次不正確');
    throw error;
  }
  return entries.length;
}

export const scheduleOut = (s) => ({ id: s.id, work_date: s.work_date, shift: s.shift, coach_id: s.coach_id, admin_user_id: s.admin_user_id, status: s.status });

// ---------- 品項目錄 ----------
export class ItemError extends HttpError { constructor(msg, status = 400) { super(status, msg); } }

export const listActiveItems = (db) => db.all('SELECT * FROM item_catalog_entries WHERE is_active = 1 ORDER BY item_category, item_name, id');

export async function itemsGrouped(db) {
  const grouped = Object.fromEntries(ITEM_CATEGORIES.map((c) => [c, []]));
  for (const item of await listActiveItems(db)) {
    (grouped[item.item_category] ??= []).push({ id: item.id, name: item.item_name, price: item.default_price != null ? Number(item.default_price) : null });
  }
  return grouped;
}

export const itemOut = (i) => ({ id: i.id, item_category: i.item_category, item_name: i.item_name, default_price: i.default_price != null ? Number(i.default_price) : null });

// ---------- 場租教練 ----------
export const listVenueCoaches = (db) => db.all('SELECT * FROM venue_rental_coaches ORDER BY is_active DESC, name, id');
export const venueCoachOut = (v) => ({ id: v.id, name: v.name, phone: v.phone, is_active: Boolean(v.is_active) });

// ---------- 後台帳號 ----------
export async function createAdminAccount(db, { username, password, role, linked_member_id: linkedMemberId }) {
  if (!(role in ADMIN_ROLE_LABELS)) throw new HttpError(400, '角色不正確');
  if (!username || !password) throw new HttpError(400, '帳號密碼不可空白');
  if (await db.first('SELECT id FROM admin_users WHERE username = ?', username)) throw new HttpError(400, '帳號已存在');
  const hash = await hashPassword(password);
  try {
    return await db.first('INSERT INTO admin_users (username, password_hash, role, is_active, linked_member_id) VALUES (?, ?, ?, 1, ?) RETURNING *', username, hash, role, linkedMemberId ?? null);
  } catch (error) {
    if (/UNIQUE constraint failed/.test(error.message)) throw new HttpError(400, '帳號已存在');
    if (/FOREIGN KEY constraint failed/.test(error.message)) throw new HttpError(400, '連結的會員不存在');
    throw error;
  }
}

export const adminAccountOut = (u) => ({ id: u.id, username: u.username, role: u.role, is_active: Boolean(u.is_active), linked_member_id: u.linked_member_id });

/** 第一次開機：沒有任何後台帳號時，用 ADMIN_BOOTSTRAP_USERNAME/PASSWORD 建第一個超級管理者（對應 scripts/bootstrap_admin.py） */
export async function bootstrapAdmin(db, env) {
  const username = env.ADMIN_BOOTSTRAP_USERNAME;
  const password = env.ADMIN_BOOTSTRAP_PASSWORD;
  if (!username || !password) return;
  if ((await db.value('SELECT count(*) FROM admin_users')) > 0) {
    await db.run(`UPDATE admin_users SET role = 'super_admin', updated_at = ${NOW_SQL} WHERE username = ? AND role <> 'super_admin'`, username);
    return;
  }
  await db.run("INSERT OR IGNORE INTO admin_users (username, password_hash, role, is_active) VALUES (?, ?, 'super_admin', 1)", username, await hashPassword(password));
}


/**
 * 每天台北 00:10 執行：只買會籍（沒有店內教練課）的會員，會籍迄日已過 → 解除 LINE 綁定、選單退回通用版。
 * 有教練課的學員不動（還要看課程）。沒有緩衝期；續約後由櫃台重新發綁定碼。
 */
export async function unbindExpiredMemberships(db, env, today) {
  const rows = await db.all(`SELECT m.id, m.name, m.line_user_id FROM members m
    WHERE m.line_user_id IS NOT NULL AND m.membership_active_until IS NOT NULL AND m.membership_active_until < ?
      AND (${MEMBER_KIND_SQL}) = 'membership'`, today);
  for (const m of rows) {
    await db.run(`UPDATE members SET line_user_id = NULL, updated_at = ${NOW_SQL} WHERE id = ? AND line_user_id = ?`, m.id, m.line_user_id);
    await unlinkRichMenu(env, m.line_user_id);
  }
  if (rows.length) console.log(`會籍到期自動解除綁定 ${rows.length} 位：${rows.map((m) => m.name).join('、')}`);
  return rows.length;
}
