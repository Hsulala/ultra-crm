// 對應 app/services/booking_service.py、capacity_service.py、venue_booking_service.py
import { HttpError } from '../lib/http.js';
import { pad } from '../lib/time.js';

export class BookingError extends HttpError { constructor(msg, status = 400) { super(status, msg); } }

// 08:00 ~ 21:00，跟現行紙本班表範圍一致
export const DAY_GRID_HOURS = Array.from({ length: 14 }, (_, i) => `${pad(8 + i)}:00:00`);
const SHIFT_SHORT_LABELS = { morning: '早', afternoon: '中', evening: '晚' };
export const PILATES_CAPACITY = 4;
const VENUE_SLOT_NUMBERS = [1, 2, 3];

export async function contractUnitCount(db, contractId) {
  const n = await db.value('SELECT count(*) FROM contract_members WHERE contract_id = ?', contractId);
  return n >= 2 ? 2 : 1;
}

/** 這個時段已用掉的皮拉提斯名額（1對2 合約佔 2 個） */
export async function pilatesUsage(db, slotDate, slotTime) {
  // 體驗課每人佔 1 個名額
  return db.value(`SELECT coalesce(sum(CASE WHEN (SELECT count(*) FROM contract_members cm WHERE cm.contract_id = b.contract_id) >= 2 THEN 2 ELSE 1 END), 0)
    + (SELECT count(*) FROM trial_bookings t WHERE t.area = 'pilates' AND t.slot_date = ?1 AND t.slot_start_time = ?2 AND t.status = 'booked')
    FROM bookings b WHERE b.area = 'pilates' AND b.slot_date = ?1 AND b.slot_start_time = ?2 AND b.status = 'booked'`, slotDate, slotTime);
}

/**
 * 約課。coach_id 沒填就跟著合約的教練走（皮拉提斯合約可能是場租教練開的）。
 * 名額檢查與寫入放在同一個指令裡（INSERT … SELECT … WHERE 名額夠），D1 一次只執行一個寫入，所以不會超賣——
 * 取代原本 PostgreSQL 的 advisory lock。
 */
export async function createBooking(db, { contractId, slotDate, slotTime, area, createdById = null, coachId = null }) {
  if (!['strength', 'pilates'].includes(area)) throw new BookingError('area 必須是 strength 或 pilates');
  const contract = await db.first('SELECT * FROM contracts WHERE id = ?', contractId);
  if (!contract || contract.status !== 'active') throw new BookingError('找不到有效（進行中）的合約');

  let venueCoachId = null;
  if (coachId == null) { coachId = contract.coach_id; venueCoachId = contract.venue_coach_id; }

  const existing = coachId != null
    ? await db.first("SELECT id FROM bookings WHERE coach_id = ? AND slot_date = ? AND slot_start_time = ? AND status = 'booked' LIMIT 1", coachId, slotDate, slotTime)
    : await db.first("SELECT id FROM bookings WHERE venue_coach_id = ? AND slot_date = ? AND slot_start_time = ? AND status = 'booked' LIMIT 1", venueCoachId, slotDate, slotTime);
  if (existing) throw new BookingError('這位教練在這個時段已經有其他預約了');
  if (coachId != null && await db.first("SELECT id FROM trial_bookings WHERE coach_id = ? AND slot_date = ? AND slot_start_time = ? AND status = 'booked' LIMIT 1", coachId, slotDate, slotTime)) {
    throw new BookingError('這位教練在這個時段已經有體驗課了');
  }

  let units = 0;
  if (area === 'pilates') {
    units = await contractUnitCount(db, contractId);
    const used = await pilatesUsage(db, slotDate, slotTime);
    if (used + units > PILATES_CAPACITY) throw new BookingError(`該時段皮拉提斯名額已滿（目前 ${used}/${PILATES_CAPACITY}，還需要 ${units} 個名額）`);
  }

  const capacityGuard = area === 'pilates'
    ? `AND (SELECT coalesce(sum(CASE WHEN (SELECT count(*) FROM contract_members cm WHERE cm.contract_id = b.contract_id) >= 2 THEN 2 ELSE 1 END), 0)
         FROM bookings b WHERE b.area = 'pilates' AND b.slot_date = ?4 AND b.slot_start_time = ?5 AND b.status = 'booked')
       + (SELECT count(*) FROM trial_bookings t WHERE t.area = 'pilates' AND t.slot_date = ?4 AND t.slot_start_time = ?5 AND t.status = 'booked') + ${units} <= ${PILATES_CAPACITY}`
    : '';
  let row;
  try {
    row = await db.first(`INSERT INTO bookings (coach_id, venue_coach_id, contract_id, slot_date, slot_start_time, area, status, created_by_id)
      SELECT ?1, ?2, ?3, ?4, ?5, ?6, 'booked', ?7 WHERE 1 = 1 ${capacityGuard} RETURNING *`,
    coachId, venueCoachId, contractId, slotDate, slotTime, area, createdById);
  } catch (error) {
    if (/UNIQUE constraint failed/.test(error.message)) throw new BookingError('這位教練在這個時段已經有其他預約了');
    throw error;
  }
  if (!row) {
    const used = await pilatesUsage(db, slotDate, slotTime);
    throw new BookingError(`該時段皮拉提斯名額已滿（目前 ${used}/${PILATES_CAPACITY}，還需要 ${units} 個名額）`);
  }
  return row;
}

export async function cancelBooking(db, id) {
  const row = await db.first("UPDATE bookings SET status = 'cancelled', updated_at = strftime('%Y-%m-%dT%H:%M:%f000Z','now') WHERE id = ? RETURNING *", id);
  if (!row) throw new BookingError('找不到這筆預約', 404);
  return row;
}


// ---- 體驗課 ----
export const TRIAL_FEES = { strength: 500, pilates: 900 };
const TRIAL_ITEM = { strength: 'PT體驗', pilates: 'PL體驗' };

/**
 * 體驗課：不需要合約。佔用教練時段（皮拉提斯另佔 1 個名額），同時記一筆體驗費營收（日期＝上課日）。
 * 營收與預約放在同一個 batch，一起成功或一起失敗。
 */
export async function createTrialBooking(db, p) {
  const area = p.area;
  if (!TRIAL_FEES[area]) throw new BookingError('課程類型必須是重訓或皮拉提斯');
  const name = String(p.customer_name ?? '').trim();
  if (!name) throw new BookingError('請填體驗者姓名');
  const coach = await db.first("SELECT id, name FROM members WHERE id = ? AND role = 'coach' AND is_active = 1", p.coach_id);
  if (!coach) throw new BookingError('請選擇店內教練');
  const busy = await db.first(`SELECT 1 FROM bookings WHERE coach_id = ?1 AND slot_date = ?2 AND slot_start_time = ?3 AND status = 'booked'
    UNION ALL SELECT 1 FROM trial_bookings WHERE coach_id = ?1 AND slot_date = ?2 AND slot_start_time = ?3 AND status = 'booked' LIMIT 1`, coach.id, p.slot_date, p.slot_start_time);
  if (busy) throw new BookingError(`${coach.name} 在這個時段已經有預約了`);
  if (area === 'pilates') {
    const used = await pilatesUsage(db, p.slot_date, p.slot_start_time);
    if (used + 1 > PILATES_CAPACITY) throw new BookingError(`該時段皮拉提斯名額已滿（目前 ${used}/${PILATES_CAPACITY}）`);
  }
  const fee = p.fee == null ? TRIAL_FEES[area] : Number(p.fee);
  const payment = String(p.payment_method ?? '').trim() || '現金';
  const phone = String(p.customer_phone ?? '').trim() || null;
  try {
    const out = await db.batch([
      db.prep(`INSERT INTO revenue_details (entry_date, item_category, item_name, coach_id, coach_name, customer_name, content, payment_method, amount, entered_by_id)
        VALUES (?, 'coaching', ?, ?, ?, ?, ?, ?, ?, ?)`, [p.slot_date, TRIAL_ITEM[area], coach.id, coach.name, name, phone ? `體驗課（電話 ${phone}）` : '體驗課', payment, fee, p.admin_id]),
      db.prep(`INSERT INTO trial_bookings (coach_id, area, slot_date, slot_start_time, customer_name, customer_phone, fee, revenue_id, created_by_admin_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, last_insert_rowid(), ?) RETURNING *`, [coach.id, area, p.slot_date, p.slot_start_time, name, phone, fee, p.admin_id]),
    ]);
    return out[1].results[0];
  } catch (error) {
    if (/UNIQUE constraint failed/.test(error.message)) throw new BookingError(`${coach.name} 在這個時段已經有體驗課了`);
    throw error;
  }
}

/** 取消體驗課：連同體驗費營收一起刪；那天現金已交班結帳的話營收保留，請手動沖銷 */
export async function cancelTrialBooking(db, id) {
  const t = await db.first("SELECT * FROM trial_bookings WHERE id = ? AND status = 'booked'", id);
  if (!t) throw new BookingError('找不到這筆體驗課', 404);
  const rev = t.revenue_id ? await db.first('SELECT * FROM revenue_details WHERE id = ?', t.revenue_id) : null;
  const locked = rev && /現金/.test(rev.payment_method) && await db.first('SELECT 1 FROM cash_closings WHERE business_date = ? LIMIT 1', rev.entry_date);
  const stmts = [db.prep("UPDATE trial_bookings SET status = 'cancelled', updated_at = strftime('%Y-%m-%dT%H:%M:%f000Z','now') WHERE id = ?", [t.id])];
  if (rev && !locked) stmts.unshift(db.prep('DELETE FROM revenue_details WHERE id = ?', [rev.id]));
  await db.batch(stmts);
  return { revenue_removed: !!(rev && !locked) };
}

export const bookingsForCoach = (db, coachId) =>
  db.all("SELECT * FROM bookings WHERE coach_id = ? AND status = 'booked' ORDER BY slot_date, slot_start_time, id", coachId);

export const bookingOut = (b) => ({
  id: b.id, coach_id: b.coach_id, venue_coach_id: b.venue_coach_id, contract_id: b.contract_id,
  slot_date: b.slot_date, slot_start_time: b.slot_start_time, area: b.area, status: b.status,
});

// ---- 場租 ----
export async function createVenueBooking(db, p) {
  const area = p.area ?? 'strength';
  if (area !== 'strength') throw new BookingError('場租教練只租一樓重訓區，area 只能是 strength');
  if (![1, 2].includes(p.party_size)) throw new BookingError('party_size 只能是 1 或 2');
  const booked = new Set((await db.all("SELECT slot_number FROM venue_bookings WHERE slot_date = ? AND slot_start_time = ? AND status = 'booked'", p.slot_date, p.slot_start_time)).map((r) => r.slot_number));
  let slot = p.slot_number ?? null;
  if (slot == null) {
    const free = VENUE_SLOT_NUMBERS.filter((n) => !booked.has(n));
    if (!free.length) throw new BookingError(`這個時段場租名額已滿（${VENUE_SLOT_NUMBERS.length}/${VENUE_SLOT_NUMBERS.length}）`);
    slot = free[0];
  } else {
    if (!VENUE_SLOT_NUMBERS.includes(slot)) throw new BookingError('slot_number 只能是 1、2 或 3');
    if (booked.has(slot)) throw new BookingError('這個檔期剛剛已經被約走了，請重新整理頁面');
  }
  try {
    return await db.first(`INSERT INTO venue_bookings (venue_coach_id, customer_name, customer_phone, party_size, slot_date, slot_start_time, slot_number, area, status)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'booked') RETURNING *`,
    p.venue_coach_id, p.customer_name, p.customer_phone ?? null, p.party_size, p.slot_date, p.slot_start_time, slot, area);
  } catch (error) {
    if (/UNIQUE constraint failed/.test(error.message)) throw new BookingError('這個檔期剛剛已經被約走了，請重新整理頁面');
    if (/FOREIGN KEY constraint failed/.test(error.message)) throw new BookingError('找不到這位場租教練');
    throw error;
  }
}

export async function cancelVenueBooking(db, id) {
  const row = await db.first("UPDATE venue_bookings SET status = 'cancelled', updated_at = strftime('%Y-%m-%dT%H:%M:%f000Z','now') WHERE id = ? RETURNING *", id);
  if (!row) throw new BookingError('找不到這筆預約', 404);
  return row;
}

export const venueBookingOut = (b) => ({
  id: b.id, venue_coach_id: b.venue_coach_id, customer_name: b.customer_name, customer_phone: b.customer_phone, party_size: b.party_size,
  slot_date: b.slot_date, slot_start_time: b.slot_start_time, slot_number: b.slot_number, area: b.area, status: b.status,
});

const names = (members) => members.map((m) => m.name).join('、');

/** 總覽頁的當天網格（對應 build_day_grid）；所有查詢一次送出 */
export async function buildDayGrid(db, date) {
  const ACTIVE_COACHES = "SELECT id FROM members WHERE role = 'coach' AND is_active = 1";
  const RELEVANT = `SELECT id FROM contracts WHERE status = 'active' AND total_sessions > used_sessions AND (course_type = 'pilates' OR (course_type = 'strength' AND coach_id IN (${ACTIVE_COACHES})))
    UNION SELECT contract_id FROM bookings WHERE slot_date = ?1 AND status = 'booked'`;
  const [coaches, schedules, bookings, contracts, studentRows, venueRows, venueBookings, trials] = await db.many([
    ["SELECT * FROM members WHERE role = 'coach' AND is_active = 1 ORDER BY id"],
    ['SELECT * FROM schedules WHERE work_date = ? AND coach_id IS NOT NULL ORDER BY id', date],
    ["SELECT * FROM bookings WHERE slot_date = ? AND status = 'booked' ORDER BY slot_start_time, id", date],
    [`SELECT * FROM contracts WHERE status = 'active' AND total_sessions > used_sessions AND (course_type = 'pilates' OR (course_type = 'strength' AND coach_id IN (${ACTIVE_COACHES}))) ORDER BY id`],
    [`SELECT cm.contract_id, m.* FROM contract_members cm JOIN members m ON m.id = cm.member_id WHERE cm.contract_id IN (${RELEVANT}) ORDER BY m.id`, date],
    ['SELECT id, name FROM venue_rental_coaches'],
    ["SELECT * FROM venue_bookings WHERE slot_date = ? AND status = 'booked' ORDER BY slot_start_time, id", date],
    ["SELECT * FROM trial_bookings WHERE slot_date = ? AND status = 'booked' ORDER BY slot_start_time, id", date],
  ]);
  const shiftsByCoach = new Map();
  for (const s of schedules) { if (!shiftsByCoach.has(s.coach_id)) shiftsByCoach.set(s.coach_id, []); shiftsByCoach.get(s.coach_id).push(s.shift); }
  const strength = new Map();
  const pilatesByHour = new Map(DAY_GRID_HOURS.map((h) => [h, []]));
  for (const b of bookings) {
    if (b.area === 'pilates') { if (!pilatesByHour.has(b.slot_start_time)) pilatesByHour.set(b.slot_start_time, []); pilatesByHour.get(b.slot_start_time).push(b); }
    else if (b.coach_id != null) { const k = `${b.coach_id}|${b.slot_start_time}`; if (!strength.has(k)) strength.set(k, []); strength.get(k).push(b); }
  }
  const studentsByContract = new Map();
  for (const { contract_id: cid, ...m } of studentRows) { if (!studentsByContract.has(cid)) studentsByContract.set(cid, []); studentsByContract.get(cid).push(m); }
  const students = (cid) => studentsByContract.get(cid) ?? [];
  const coachContracts = (coachId) => contracts.filter((c) => c.course_type === 'strength' && c.coach_id === coachId);
  const pilatesContracts = contracts.filter((c) => c.course_type === 'pilates');

  const columns = coaches.map((coach) => {
    const cells = {};
    for (const h of DAY_GRID_HOURS) {
      cells[h] = [
        ...(strength.get(`${coach.id}|${h}`) ?? []).map((b) => ({ booking_id: b.id, kind: 'booking', label: names(students(b.contract_id)) })),
        ...trials.filter((t) => t.area === 'strength' && t.coach_id === coach.id && t.slot_start_time === h).map((t) => ({ booking_id: t.id, kind: 'trial', label: `【體驗】${t.customer_name}` })),
      ];
    }
    return {
      coach_id: coach.id,
      coach_name: coach.name,
      shift_labels: (shiftsByCoach.get(coach.id) ?? []).map((s) => SHIFT_SHORT_LABELS[s] ?? s),
      cells,
      contract_options: coachContracts(coach.id).map((c) => ({ contract_id: c.id, label: `${names(students(c.id))}（剩${c.total_sessions - c.used_sessions}堂）` })),
    };
  });

  const venueNames = new Map(venueRows.map((v) => [v.id, v.name]));
  const venueColumns = VENUE_SLOT_NUMBERS.map((slot) => {
    const cells = {};
    for (const h of DAY_GRID_HOURS) {
      cells[h] = venueBookings.filter((vb) => vb.slot_number === slot && vb.slot_start_time === h).map((vb) => ({
        booking_id: vb.id,
        label: `${vb.customer_name}／${venueNames.get(vb.venue_coach_id) ?? '?'}${vb.party_size === 2 ? '(1對2)' : ''}`,
        venue_coach_id: vb.venue_coach_id,
      }));
    }
    return { slot_number: slot, cells };
  });

  const coachNames = new Map(coaches.map((c) => [c.id, c.name]));
  const pilatesOptions = pilatesContracts.map((c) => {
    const coachLabel = c.coach_id != null ? (coachNames.get(c.coach_id) ?? '?') : `${venueNames.get(c.venue_coach_id) ?? '?'}（場租）`;
    return { contract_id: c.id, label: `${names(students(c.id))}（${coachLabel}・剩${c.total_sessions - c.used_sessions}堂）` };
  });
  const pilatesCells = {};
  for (const h of DAY_GRID_HOURS) {
    pilatesCells[h] = (pilatesByHour.get(h) ?? []).map((b) => {
      const s = students(b.contract_id);
      const coachName = b.coach_id != null ? (coachNames.get(b.coach_id) ?? '?') : (venueNames.get(b.venue_coach_id) ?? '?');
      return { booking_id: b.id, kind: 'booking', label: `${names(s)}／${coachName}${s.length >= 2 ? '(1對2)' : ''}` };
    });
    for (const t of trials.filter((x) => x.area === 'pilates' && x.slot_start_time === h)) {
      pilatesCells[h].push({ booking_id: t.id, kind: 'trial', label: `【體驗】${t.customer_name}／${coachNames.get(t.coach_id) ?? '?'}` });
    }
  }
  return { hours: DAY_GRID_HOURS, columns, venue_columns: venueColumns, pilates_cells: pilatesCells, pilates_contract_options: pilatesOptions };
}
