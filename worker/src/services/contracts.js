// 對應 app/services/contract_service.py、class_record_service.py
import { HttpError } from '../lib/http.js';
import { insertStmt } from '../lib/db.js';
import { money } from '../lib/money.js';

export class ContractError extends HttpError { constructor(msg) { super(400, msg); } }

/** 沿用 UF0001 格式：目前最大編號 + 1 */
export async function nextMemberNo(db) {
  const rows = await db.all("SELECT member_no FROM members WHERE member_no LIKE 'UF%'");
  let max = 0;
  for (const { member_no: no } of rows) {
    const m = /^UF(\d+)$/.exec(no ?? '');
    if (m) max = Math.max(max, Number(m[1]));
  }
  return `UF${String(max + 1).padStart(4, '0')}`;
}

export async function membersForContract(db, contractId) {
  return db.all('SELECT m.* FROM members m JOIN contract_members cm ON cm.member_id = m.id WHERE cm.contract_id = ? ORDER BY m.id', contractId);
}

/** 多份合約的學員：Map(contract_id → [member]) */
export async function membersForContracts(db, ids) {
  const map = new Map(ids.map((id) => [id, []]));
  if (!ids.length) return map;
  // D1 單一指令最多 100 個參數，分批查
  for (let i = 0; i < ids.length; i += 90) {
    const chunk = ids.slice(i, i + 90);
    const rows = await db.all(`SELECT cm.contract_id, m.* FROM contract_members cm JOIN members m ON m.id = cm.member_id WHERE cm.contract_id IN (${chunk.map(() => '?').join(',')}) ORDER BY m.id`, ...chunk);
    for (const row of rows) {
      const { contract_id: cid, ...member } = row;
      map.get(cid)?.push(member);
    }
  }
  return map;
}

export const activeContractsForCoach = (db, coachId) =>
  db.all("SELECT * FROM contracts WHERE coach_id = ? AND status = 'active' ORDER BY id", coachId);

export const activePilatesContracts = (db) =>
  db.all("SELECT * FROM contracts WHERE course_type = 'pilates' AND status = 'active' ORDER BY id");

export const contractsForMember = (db, memberId) =>
  db.all('SELECT c.* FROM contracts c JOIN contract_members cm ON cm.contract_id = c.id WHERE cm.member_id = ? ORDER BY c.purchase_date DESC, c.id', memberId);

/** 建合約；有 newStudentName 時先建新學員（自動編號），全部一批寫入（任何一步失敗都不留半套資料） */
export async function createContract(db, p) {
  if (!['strength', 'pilates'].includes(p.course_type)) throw new ContractError('course_type 必須是 strength 或 pilates');
  if ((p.coach_id == null) === (p.venue_coach_id == null)) throw new ContractError('coach_id 跟 venue_coach_id 必須擇一填寫');
  if (p.venue_coach_id != null && p.course_type !== 'pilates') throw new ContractError('場租教練只能開皮拉提斯合約，重訓場地租借請用「場租教練」約課功能');

  const memberIds = [...p.member_ids];
  const statements = [];
  let newMemberNo = null;
  if (p.new_student_name) {
    newMemberNo = await nextMemberNo(db);
    statements.push(insertStmt(db, 'members', { member_no: newMemberNo, name: p.new_student_name, role: 'student' }));
  }
  const count = memberIds.length + (newMemberNo ? 1 : 0);
  if (!count) throw new ContractError('合約至少要有一位學員');
  if (count > 2) throw new ContractError('合約最多支援 1對2（兩位學員）');

  statements.push(db.prep(`INSERT INTO contracts (contract_no, coach_id, venue_coach_id, course_type, purchase_date, unit_price, total_sessions, used_sessions, expiry_date, status)
    VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?) RETURNING *`,
  [p.contract_no ?? null, p.coach_id ?? null, p.venue_coach_id ?? null, p.course_type, p.purchase_date, money(p.unit_price), p.total_sessions, p.expiry_date ?? null, p.status ?? 'active']));
  const contractIdx = statements.length - 1;
  // 新合約的 id＝剛插入的那一列；用 last_insert_rowid() 讓同一批指令接得上
  for (const memberId of memberIds) {
    statements.push(db.prep('INSERT INTO contract_members (contract_id, member_id) VALUES ((SELECT max(id) FROM contracts), ?)', [memberId]));
  }
  if (newMemberNo) {
    statements.push(db.prep('INSERT INTO contract_members (contract_id, member_id) VALUES ((SELECT max(id) FROM contracts), (SELECT id FROM members WHERE member_no = ?))', [newMemberNo]));
  }
  try {
    const results = await db.batch(statements);
    return results[contractIdx].results[0];
  } catch (error) {
    if (/UNIQUE constraint failed: members.member_no/.test(error.message)) throw new ContractError('會員編號已存在，請再試一次');
    if (/FOREIGN KEY constraint failed/.test(error.message)) throw new ContractError('member_ids 裡有不存在的會員');
    throw error;
  }
}

export async function createClassRecord(db, p) {
  return db.first(`INSERT INTO class_records (contract_id, actual_teaching_coach_id, class_date, content_summary, logged_by_id)
    VALUES (?, ?, ?, ?, ?) RETURNING *`, p.contract_id, p.actual_teaching_coach_id, p.class_date, p.content_summary, p.logged_by_id);
}

export async function classRecordsForMember(db, memberId, limit = 5) {
  return db.all(`SELECT cr.* FROM class_records cr
    JOIN contracts c ON c.id = cr.contract_id
    JOIN contract_members cm ON cm.contract_id = c.id
    WHERE cm.member_id = ? ORDER BY cr.class_date DESC, cr.id DESC LIMIT ?`, memberId, limit);
}

/** 前端顯示用的合約（金額轉回數字，對應 ContractResponse） */
export const contractOut = (c) => ({
  id: c.id, contract_no: c.contract_no, coach_id: c.coach_id, venue_coach_id: c.venue_coach_id, course_type: c.course_type,
  purchase_date: c.purchase_date, unit_price: Number(c.unit_price), total_sessions: c.total_sessions, used_sessions: c.used_sessions,
  expiry_date: c.expiry_date, status: c.status,
});
