// LIFF API（對應 app/routers/liff_api/*.py）與 LINE webhook、內部排程端點。
import { Hono } from 'hono';
import { currentMember, currentVenueCoach, lineUserId, requireMemberRole } from '../lib/auth.js';
import { fail, parseBody, queryParam, readJson } from '../lib/http.js';
import { verifySignature } from '../lib/line.js';
import { taipeiToday } from '../lib/time.js';
import { bookingOut, bookingsForCoach, createBooking, createVenueBooking, venueBookingOut } from '../services/bookings.js';
import { activeContractsForCoach, classRecordsForMember, contractsForMember, createClassRecord, membersForContract, membersForContracts } from '../services/contracts.js';
import { MEMBER_KIND_SQL, expireStaleCodes, publishedSchedule, redeemBindingCode, scheduleOut, submitUnavailability } from '../services/people.js';

export const liff = new Hono();

liff.post('/binding/redeem', async (c) => {
  const p = parseBody(await readJson(c), { code: 'str' });
  const lineId = await lineUserId(c);
  const { target } = await redeemBindingCode(c.get('db'), c.env, { code: p.code, lineUserId: lineId });
  return c.json({ status: 'success', role: target.role || 'venue_coach', name: target.name });
});

liff.get('/contracts/mine', async (c) => {
  const member = await requireMemberRole(c, 'student');
  const db = c.get('db');
  const out = [];
  for (const x of await contractsForMember(db, member.id)) {
    let coachName;
    if (x.coach_id != null) coachName = (await db.first('SELECT name FROM members WHERE id = ?', x.coach_id))?.name ?? '未知教練';
    else { const v = await db.first('SELECT name FROM venue_rental_coaches WHERE id = ?', x.venue_coach_id); coachName = v ? `${v.name}（場租）` : '未知教練'; }
    const members = await membersForContract(db, x.id);
    out.push({
      id: x.id, contract_no: x.contract_no, coach_id: x.coach_id, coach_name: coachName, course_type: x.course_type, purchase_date: x.purchase_date,
      total_sessions: x.total_sessions, used_sessions: x.used_sessions, remaining_sessions: x.total_sessions - x.used_sessions, expiry_date: x.expiry_date,
      status: x.status, is_shared: members.length > 1, shared_with_names: members.filter((m) => m.id !== member.id).map((m) => m.name),
    });
  }
  return c.json(out);
});

const recordOut = (r, coachName) => ({ id: r.id, contract_id: r.contract_id, actual_teaching_coach_id: r.actual_teaching_coach_id, coach_name: coachName, class_date: r.class_date, content_summary: r.content_summary });

liff.get('/class-records/mine', async (c) => {
  const member = await requireMemberRole(c, 'student');
  const db = c.get('db');
  const out = [];
  for (const r of await classRecordsForMember(db, member.id, 5)) {
    const coach = await db.first('SELECT name FROM members WHERE id = ?', r.actual_teaching_coach_id);
    out.push(recordOut(r, coach ? coach.name : '未知教練'));
  }
  return c.json(out);
});

liff.get('/class-records/active-contracts', async (c) => {
  const coach = await requireMemberRole(c, 'coach');
  const db = c.get('db');
  // 只列還有剩餘堂數的合約；學員一次查回（匯入的舊資料一位教練有數百份合約，逐份查會超過 Cloudflare 每次請求的查詢上限）
  const rows = (await activeContractsForCoach(db, coach.id)).filter((x) => x.total_sessions > x.used_sessions);
  const members = await membersForContracts(db, rows.map((x) => x.id));
  rows.sort((a, b) => (b.purchase_date || '').localeCompare(a.purchase_date || '') || b.id - a.id);
  return c.json(rows.map((x) => ({
    contract_id: x.id, contract_no: x.contract_no, course_type: x.course_type, purchase_date: x.purchase_date,
    student_names: (members.get(x.id) ?? []).map((m) => m.name), remaining_sessions: x.total_sessions - x.used_sessions,
  })));
});

// 會員卡：櫃台用眼睛看（畫面有即時時鐘與動畫，截圖會看得出來）
liff.get('/membership-card', async (c) => {
  const member = await requireMemberRole(c, 'student');
  const today = taipeiToday();
  const until = member.membership_active_until;
  return c.json({
    name: member.name, member_no: member.member_no, card_no: member.membership_card_no ?? null,
    start: member.membership_start_date ?? null, until: until ?? null, today,
    active: !!until && until >= today && (!member.membership_start_date || member.membership_start_date <= today),
  });
});

// 目前登入的 LINE 帳號綁到誰（綁定頁、教練預約頁用）
liff.get('/me', async (c) => {
  const lineId = await lineUserId(c);
  const db = c.get('db');
  const m = await db.first(`SELECT m.id, m.name, m.role, m.membership_active_until, (${MEMBER_KIND_SQL}) AS kind FROM members m WHERE m.line_user_id = ? AND m.is_active = 1 LIMIT 1`, lineId);
  if (m) return c.json({ bound: true, kind: m.kind, id: m.id, name: m.name, role: m.role, membership_active_until: m.membership_active_until ?? null });
  const v = await db.first('SELECT id, name FROM venue_rental_coaches WHERE line_user_id = ? AND is_active = 1 LIMIT 1', lineId);
  if (v) return c.json({ bound: true, kind: 'venue_coach', id: v.id, name: v.name, role: 'venue_coach' });
  return c.json({ bound: false });
});

liff.post('/class-records', async (c) => {
  const coach = await requireMemberRole(c, 'coach');
  const db = c.get('db');
  const p = parseBody(await readJson(c), { contract_id: 'int', class_date: 'date', content_summary: 'str' });
  if (!await db.first('SELECT id FROM contracts WHERE id = ?', p.contract_id)) fail(404, '找不到合約');
  if (!Number(await db.value('SELECT count(*) FROM contract_members WHERE contract_id = ?', p.contract_id))) fail(400, '這份合約沒有任何學員，無法記錄課程');
  const r = await createClassRecord(db, { contract_id: p.contract_id, actual_teaching_coach_id: coach.id, class_date: p.class_date, content_summary: p.content_summary, logged_by_id: coach.id });
  return c.json(recordOut(r, coach.name));
});

liff.get('/bookings/mine', async (c) => {
  const coach = await requireMemberRole(c, 'coach');
  const db = c.get('db');
  const rows = await bookingsForCoach(db, coach.id);
  const members = await membersForContracts(db, [...new Set(rows.map((b) => b.contract_id))]);
  const trials = await db.all("SELECT * FROM trial_bookings WHERE coach_id = ? AND status = 'booked' ORDER BY slot_date, slot_start_time", coach.id);
  // 合約預約＋體驗課，依日期時間排序；student_names / kind 給「我的預約」頁顯示
  const out = [
    ...rows.map((b) => ({ ...bookingOut(b), kind: 'booking', student_names: (members.get(b.contract_id) ?? []).map((m) => m.name) })),
    ...trials.map((t) => ({ id: t.id, coach_id: t.coach_id, contract_id: null, slot_date: t.slot_date, slot_start_time: t.slot_start_time, area: t.area, status: t.status, kind: 'trial', student_names: [t.customer_name] })),
  ].sort((a, b) => (a.slot_date + a.slot_start_time).localeCompare(b.slot_date + b.slot_start_time));
  return c.json(out);
});

liff.post('/bookings', async (c) => {
  const member = await currentMember(c);
  const db = c.get('db');
  const p = parseBody(await readJson(c), { coach_id: 'int', contract_id: 'int', slot_date: 'date', slot_start_time: 'time', area: 'str' });
  if (member.role === 'student' && !await db.first('SELECT 1 FROM contract_members WHERE contract_id = ? AND member_id = ?', p.contract_id, member.id)) fail(403, '這不是您的合約，無法約課');
  const b = await createBooking(db, { coachId: p.coach_id, contractId: p.contract_id, slotDate: p.slot_date, slotTime: p.slot_start_time, area: p.area, createdById: member.id });
  return c.json(bookingOut(b));
});

liff.post('/schedule/unavailability', async (c) => {
  const coach = await requireMemberRole(c, 'coach');
  const body = await readJson(c);
  const head = parseBody(body, { target_month: 'date' });
  if (!Array.isArray(body?.entries)) fail(422, [{ type: 'list_type', loc: ['body', 'entries'], msg: 'Input should be a valid list' }]);
  const entries = body.entries.map((e, i) => {
    try { return parseBody(e, { unavailable_date: 'date', shift: 'str', note: 'str?' }); } catch (error) {
      if (Array.isArray(error.detail)) error.detail = error.detail.map((d) => ({ ...d, loc: ['body', 'entries', i, ...d.loc.slice(1)] }));
      throw error;
    }
  });
  const count = await submitUnavailability(c.get('db'), { coachId: coach.id, targetMonth: head.target_month, entries });
  return c.json({ status: 'success', count });
});

liff.get('/schedule', async (c) => {
  await requireMemberRole(c, 'coach');
  const year = queryParam(c, 'year', 'int'); const month = queryParam(c, 'month', 'int');
  if (year === null || month === null) fail(422, [['year', year], ['month', month]].filter(([, v]) => v === null).map(([k]) => ({ type: 'missing', loc: ['query', k], msg: 'Field required', input: null })));
  if (month < 1 || month > 12) fail(500, 'Internal Server Error');
  return c.json((await publishedSchedule(c.get('db'), year, month)).map(scheduleOut));
});

liff.post('/venue-bookings', async (c) => {
  const coach = await currentVenueCoach(c);
  const p = parseBody(await readJson(c), { customer_name: 'str', customer_phone: 'str?', party_size: ['int', 1], slot_date: 'date', slot_start_time: 'time', area: ['str', 'strength'] });
  const b = await createVenueBooking(c.get('db'), { ...p, venue_coach_id: coach.id, slot_number: null });
  return c.json(venueBookingOut(b));
});

// ---------- LINE webhook：目前只驗簽（事件處理尚未實作，與原本相同）----------
export const lineWebhook = new Hono();
lineWebhook.post('/webhook', async (c) => {
  const body = new Uint8Array(await c.req.arrayBuffer());
  const ok = await verifySignature(c.env.LINE_CHANNEL_SECRET, body, c.req.header('X-Line-Signature') ?? '');
  if (!ok) return c.json({ detail: '簽章驗證失敗' }, 401);
  return c.json({ status: 'ok' });
});

// ---------- 內部排程端點（原本給 Railway Cron 用；Cloudflare 上改用 Cron Triggers，這裡保留相容）----------
export const internal = new Hono();
internal.post('/cron/daily', async (c) => {
  const secret = c.req.header('x-internal-secret');
  if (secret === undefined) return c.json({ detail: [{ type: 'missing', loc: ['header', 'x-internal-secret'], msg: 'Field required' }] }, 422);
  if (!c.env.INTERNAL_CRON_SECRET || secret !== c.env.INTERNAL_CRON_SECRET) return c.json({ detail: '密鑰錯誤' }, 401);
  return c.json({ status: 'ok' });
});

