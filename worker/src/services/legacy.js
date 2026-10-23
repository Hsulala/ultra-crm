// 匯入客戶舊 Google Sheets 資料（對應 app/services/legacy_import.py；bundle 由 scripts/legacy/convert.py 產生）。
// D1 沒有可以回滾的交易，所以做法改成：
//   1. 先在程式裡把要寫的每一列都算好（試跑到這裡就停，回報的數字就是正式匯入會寫進去的數字）
//   2. 正式匯入：清除＋寫入＋「寫完再從資料庫數一次跟檔案比對」全部放進同一個 batch；
//      比對用 import_guard 的 CHECK (ok = 1)：數字不符時那一列插不進去，整批（含清除）一起不生效。
import { HttpError } from '../lib/http.js';
import { toCents } from '../lib/money.js';

export const BUNDLE_FORMAT = 'ultra-legacy-v1';
const CLEAR_TABLES = ['notification_logs', 'trial_bookings', 'bookings', 'class_records', 'contract_sessions', 'revenue_details', 'contract_members', 'binding_codes',
  'schedules', 'coach_unavailabilities', 'venue_bookings', 'cash_movements', 'cash_closings', 'contracts', 'members', 'venue_rental_coaches'];
const MAX_SQL = 90_000; // D1 單一指令約 100KB

export class LegacyImportError extends HttpError { constructor(msg) { super(400, msg); } }

const lit = (v) => {
  if (v === null || v === undefined) return 'NULL';
  if (typeof v === 'number') { if (!Number.isFinite(v)) throw new LegacyImportError('檔案裡有不正確的數字'); return String(v); }
  if (typeof v === 'boolean') return v ? '1' : '0';
  return `'${String(v).replace(/'/g, "''")}'`;
};

/** 多列 INSERT，切成每個指令 90KB 以內（不用綁定參數：D1 一個指令最多 100 個參數） */
function insertMany(table, cols, rows) {
  const out = [];
  const head = `INSERT INTO ${table} (${cols.join(', ')}) VALUES `;
  let parts = [];
  let size = head.length;
  for (const row of rows) {
    const v = `(${cols.map((c) => lit(row[c])).join(', ')})`;
    if (parts.length && size + v.length + 2 > MAX_SQL) { out.push(head + parts.join(', ')); parts = []; size = head.length; }
    parts.push(v); size += v.length + 2;
  }
  if (parts.length) out.push(head + parts.join(', '));
  return out;
}

const upper = (s) => String(s ?? '').toUpperCase();

export async function runImport(db, bundle, { batch, clearExisting, commit }) {
  if (!bundle || bundle.format !== BUNDLE_FORMAT) throw new LegacyImportError('檔案格式不對，請用 scripts/legacy/convert.py 產生的檔案');
  const report = { batch, committed: false, cleared: {} };

  if (clearExisting) {
    for (const t of CLEAR_TABLES) report.cleared[t] = Number(await db.value(`SELECT count(*) FROM ${t}`));
  } else if (await db.first('SELECT id FROM members WHERE import_batch IS NOT NULL LIMIT 1')) {
    throw new LegacyImportError('已經匯入過舊資料；要重新匯入請勾選「先清除目前的資料」');
  }
  const admin = await db.first("SELECT id FROM admin_users WHERE role = 'super_admin' AND is_active = 1 ORDER BY id LIMIT 1");
  if (!admin) throw new LegacyImportError('找不到啟用中的超級管理者帳號，營收需要登記人');

  const contractsIn = bundle.contracts ?? [];
  const revenueIn = bundle.revenue ?? [];
  const statements = [];
  if (clearExisting) {
    statements.push('UPDATE admin_users SET linked_member_id = NULL');
    for (const t of CLEAR_TABLES) statements.push(`DELETE FROM ${t}`);
    statements.push("DELETE FROM sqlite_sequence WHERE name IN ('members', 'contracts', 'contract_sessions', 'revenue_details', 'venue_rental_coaches')");
  }

  // 清除後資料庫裡剩下的（不清除時就是目前的）教練／場租教練／學員編號
  const existingCoaches = clearExisting ? [] : await db.all("SELECT id, name FROM members WHERE role = 'coach' ORDER BY id");
  const existingVenue = clearExisting ? [] : await db.all('SELECT id, name FROM venue_rental_coaches ORDER BY id');
  let maxNo = 0;
  if (!clearExisting) {
    for (const { member_no: no } of await db.all("SELECT member_no FROM members WHERE member_no LIKE 'UF%'")) {
      const m = /^UF(\d+)$/.exec(no ?? '');
      if (m) maxNo = Math.max(maxNo, Number(m[1]));
    }
  }

  // ---- 教練：用名字（不分大小寫）對應，沒有就新增；新增的 id 在 SQL 裡用子查詢找回 ----
  const coachRef = new Map(); // NAME → SQL 片段
  const newCoaches = [];
  for (const name of bundle.staff_coaches ?? []) {
    const hit = existingCoaches.find((m) => upper(m.name) === upper(name));
    if (hit) coachRef.set(upper(name), String(hit.id));
    else {
      newCoaches.push({ member_no: `COACH-${name}`, name, role: 'coach', is_active: 1, import_batch: batch });
      coachRef.set(upper(name), `(SELECT id FROM members WHERE member_no = ${lit(`COACH-${name}`)})`);
    }
  }
  const venueRef = new Map();
  const newVenue = [];
  const venueNames = [...(bundle.venue_coaches ?? [])];
  if (contractsIn.some((c) => !c.coach)) venueNames.push('原表未填教練');
  for (const name of venueNames) {
    const key = upper(String(name).trim());
    if (venueRef.has(key)) continue;
    const hit = existingVenue.find((v) => upper(String(v.name).trim()) === key);
    if (hit) venueRef.set(key, String(hit.id));
    else {
      newVenue.push({ name, import_batch: batch, is_active: 1 });
      venueRef.set(key, `(SELECT id FROM venue_rental_coaches WHERE import_batch = ${lit(batch)} AND name = ${lit(name)})`);
    }
  }

  // ---- 學員：同名視為同一人，依第一次購買日期排會員編號 ----
  const sorted = [...contractsIn].sort((a, b) => (a.purchase_date + '\u0000' + a.contract_no < b.purchase_date + '\u0000' + b.contract_no ? -1 : a.purchase_date + '\u0000' + a.contract_no > b.purchase_date + '\u0000' + b.contract_no ? 1 : 0));
  const firstSeen = new Map();
  for (const c of sorted) for (const n of c.students) if (!firstSeen.has(n)) firstSeen.set(n, c.purchase_date);
  const students = [...firstSeen.keys()].map((name, i) => ({ member_no: `UF${String(maxNo + 1 + i).padStart(4, '0')}`, name, role: 'student', is_active: 1, import_batch: batch }));
  const studentNo = new Map(students.map((s) => [s.name, s.member_no]));

  // ---- 合約：照檔案順序寫入，暫存 import_batch 加序號，寫完後統一改回 batch ----
  const contractRows = contractsIn.map((c, i) => {
    const coach = upper(c.coach);
    const coachId = coachRef.get(coach) ?? null;
    const venueId = coachId ? null : venueRef.get(coach || '原表未填教練') ?? null;
    if (coachId === null && venueId === null) throw new LegacyImportError(`合約 ${c.contract_no} 的教練 ${coach} 對不到`);
    return { c, i, coachId, venueId, tag: `${batch}#${i}` };
  });

  const sessionsCount = contractsIn.reduce((s, c) => s + c.sessions.length, 0);
  const revenueSum = toCents(revenueIn.reduce((s, r) => s + toCents(r.amount), 0) / 100);
  const fileCounts = {
    contracts: contractsIn.length,
    sessions: sessionsCount,
    students: firstSeen.size,
    revenue_rows: revenueIn.length,
    revenue_sum: revenueSum / 100,
  };

  // ---- 營收：備註是 5 碼合約編號且只對到一份合約，就掛上合約 ----
  const byNo = new Map();
  contractRows.forEach((r) => { if (!byNo.has(r.c.contract_no)) byNo.set(r.c.contract_no, []); byNo.get(r.c.contract_no).push(r); });
  let linked = 0;
  const revRows = revenueIn.map((r) => {
    const note = r.note;
    let contract = null;
    if (note && /^\d+$/.test(note)) {
      const m = byNo.get(note.padStart(5, '0')) ?? [];
      if (m.length === 1) { contract = m[0]; linked += 1; }
    }
    return { r, contract, content: contract ? null : (note ? `備註：${note}` : null) };
  });

  const statusCounts = {};
  for (const c of contractsIn) statusCounts[c.status] = (statusCounts[c.status] ?? 0) + 1;
  Object.assign(report, {
    file: fileCounts,
    db: { ...fileCounts },
    staff_coaches: coachRef.size,
    venue_coaches: venueRef.size,
    contract_status: statusCounts,
    revenue_linked_to_contract: linked,
    issues: (bundle.issues ?? []).length,
  });

  // ---- 組 SQL ----
  statements.push(...insertMany('members', ['member_no', 'name', 'role', 'is_active', 'import_batch'], newCoaches));
  statements.push(...insertMany('venue_rental_coaches', ['name', 'is_active', 'import_batch'], newVenue));
  statements.push(...insertMany('members', ['member_no', 'name', 'role', 'is_active', 'import_batch'], students));

  // 合約欄位裡的教練 id 是子查詢，不能用 lit()，所以自己組
  const contractValues = contractRows.map(({ c, coachId, venueId, tag }) => `(${[lit(c.contract_no), coachId ?? 'NULL', venueId ?? 'NULL', lit(c.course_type), lit(c.purchase_date),
    lit(Number(c.unit_price)), lit(c.total_sessions), lit(Math.min(c.sessions.length, c.total_sessions)), lit(c.status), lit(c.note ?? null), lit(tag)].join(', ')})`);
  const cHead = 'INSERT INTO contracts (contract_no, coach_id, venue_coach_id, course_type, purchase_date, unit_price, total_sessions, used_sessions, status, note, import_batch) VALUES ';
  for (let i = 0, parts = [], size = 0; i <= contractValues.length; i += 1) {
    const v = contractValues[i];
    if (v === undefined || (parts.length && size + v.length > MAX_SQL)) { if (parts.length) statements.push(cHead + parts.join(', ')); parts = []; size = 0; }
    if (v !== undefined) { parts.push(v); size += v.length + 2; }
  }
  // 合約學員、上課紀錄、營收都用暫存標記找回合約 id
  const cid = (tag) => `(SELECT id FROM contracts WHERE import_batch = ${lit(tag)})`;
  const sid = (name) => `(SELECT id FROM members WHERE member_no = ${lit(studentNo.get(name))})`;
  const linkValues = [];
  const sessionValues = [];
  for (const { c, tag } of contractRows) {
    for (const n of [...new Set(c.students)]) linkValues.push(`(${cid(tag)}, ${sid(n)})`);
    for (const s of c.sessions) sessionValues.push(`(${cid(tag)}, ${lit(s.no)}, ${lit(s.date || null)}, ${lit(s.raw ?? null)}, ${lit(batch)})`);
  }
  const pushValues = (head, values) => {
    for (let i = 0, parts = [], size = 0; i <= values.length; i += 1) {
      const v = values[i];
      if (v === undefined || (parts.length && size + v.length > MAX_SQL)) { if (parts.length) statements.push(head + parts.join(', ')); parts = []; size = 0; }
      if (v !== undefined) { parts.push(v); size += v.length + 2; }
    }
  };
  pushValues('INSERT INTO contract_members (contract_id, member_id) VALUES ', linkValues);
  pushValues('INSERT INTO contract_sessions (contract_id, session_no, session_date, raw_value, import_batch) VALUES ', sessionValues);
  pushValues('INSERT INTO revenue_details (entry_date, item_category, item_name, coach_id, coach_name, customer_name, content, payment_method, amount, contract_id, entered_by_id, import_batch) VALUES ',
    revRows.map(({ r, contract, content }) => `(${[lit(r.entry_date), lit(r.item_category), lit(r.item_name), coachRef.get(upper(r.coach)) ?? 'NULL', lit(r.coach ?? null), lit(r.customer_name ?? null),
      lit(content), lit(r.payment_method), lit(Number(r.amount)), contract ? cid(contract.tag) : 'NULL', String(admin.id), lit(batch)].join(', ')})`));
  statements.push(`UPDATE contracts SET import_batch = ${lit(batch)} WHERE import_batch LIKE ${lit(`${batch}#%`)}`);

  // 寫完再從資料庫數一次：跟檔案一致才插得進 ok = 1，否則整批不生效
  statements.push(`INSERT INTO import_guard (ok) SELECT
    (SELECT count(*) FROM contracts WHERE import_batch = ${lit(batch)}) = ${fileCounts.contracts}
    AND (SELECT count(*) FROM contract_sessions WHERE import_batch = ${lit(batch)}) = ${fileCounts.sessions}
    AND (SELECT count(*) FROM members WHERE import_batch = ${lit(batch)} AND role = 'student') = ${fileCounts.students}
    AND (SELECT count(*) FROM revenue_details WHERE import_batch = ${lit(batch)}) = ${fileCounts.revenue_rows}
    AND (SELECT coalesce(CAST(round(sum(amount * 100)) AS INTEGER), 0) FROM revenue_details WHERE import_batch = ${lit(batch)}) = ${revenueSum}`);
  statements.push('DELETE FROM import_guard');

  if (!commit) { report.matches = true; return report; }

  try {
    await db.batch(statements.map((sql) => db.binding.prepare(sql)));
  } catch (error) {
    if (/CHECK constraint failed/.test(error.message)) throw new LegacyImportError('寫入後比對不符，整批已取消、資料庫沒有任何變動');
    throw new LegacyImportError(`匯入失敗，資料庫沒有任何變動：${error.message}`);
  }
  // 寫入成功後再數一次，回報資料庫裡的實際數字
  report.db = {
    contracts: Number(await db.value('SELECT count(*) FROM contracts WHERE import_batch = ?', batch)),
    sessions: Number(await db.value('SELECT count(*) FROM contract_sessions WHERE import_batch = ?', batch)),
    students: Number(await db.value("SELECT count(*) FROM members WHERE import_batch = ? AND role = 'student'", batch)),
    revenue_rows: Number(await db.value('SELECT count(*) FROM revenue_details WHERE import_batch = ?', batch)),
    revenue_sum: Number(await db.value('SELECT coalesce(CAST(round(sum(amount * 100)) AS INTEGER), 0) FROM revenue_details WHERE import_batch = ?', batch)) / 100,
  };
  report.matches = JSON.stringify(report.db) === JSON.stringify(report.file);
  report.committed = true;
  return report;
}
