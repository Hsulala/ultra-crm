// Ultra Worker 的自動測試（不需要 Python）：Node 內建 SQLite 模擬 D1。
// 完整的新舊版逐項比對在 test/compare.mjs（需要先在 :8081 跑起 Python 版）。
import assert from 'node:assert/strict';
import test from 'node:test';
import { app } from '../src/index.js';
import { createSqliteBinding } from './sqlite-d1.js';
import { compare, migrationsSql, toStatements } from '../scripts/import-backup.mjs';
import { wrap } from '../src/lib/db.js';
import { runImport } from '../src/services/legacy.js';
import { ntd, fmt0 } from '../src/lib/money.js';
import { normalizeInstant, monthWeeks } from '../src/lib/time.js';

const READ = 'r'.repeat(40);
const WRITE = 'w'.repeat(40);
// 原本 Python（passlib）產生的雜湊：搬家後舊密碼要能登入
const LEGACY_HASH = '$2b$12$LsLD8pKj7BIOMTLiEpEjXOlwDaPwk9qxVEnr30hyQNDgvZEWosDWW';

function setup() {
  const binding = createSqliteBinding();
  binding.sqlite.exec(migrationsSql());
  const env = { DB: binding, SESSION_SECRET_KEY: 's'.repeat(40), REMOTE_READ_KEY: READ, REMOTE_WRITE_KEY: WRITE, DEV_MODE: 'true' };
  const sql = binding.sqlite;
  sql.exec(`INSERT INTO admin_users (username, password_hash, role) VALUES ('owner', '${LEGACY_HASH}', 'super_admin')`);
  sql.exec("INSERT INTO members (member_no, name, role) VALUES ('C1', 'NICK', 'coach'), ('UF0001', '甲', 'student'), ('UF0002', '乙', 'student'), ('UF0003', '丙', 'student'), ('UF0004', '丁', 'student')");
  let cookie = '';
  const call = async (method, path, { json, form, headers = {} } = {}) => {
    const h = { ...headers, ...(cookie ? { cookie } : {}) };
    let body;
    if (json !== undefined) { h['content-type'] = 'application/json'; body = JSON.stringify(json); }
    if (form) { h['content-type'] = 'application/x-www-form-urlencoded'; body = new URLSearchParams(form).toString(); }
    const res = await app.fetch(new Request(`http://ultra.test${path}`, { method, headers: h, body, redirect: 'manual' }), env);
    const set = res.headers.get('set-cookie');
    if (set) cookie = /Max-Age=0/i.test(set) ? '' : set.split(';')[0];
    const text = await res.text();
    let data = null; try { data = JSON.parse(text); } catch { /* html */ }
    return { status: res.status, location: res.headers.get('location'), text, data };
  };
  return { env, sql, call, db: wrap(binding) };
}

test('舊密碼（passlib bcrypt）可以登入；密碼錯 401；停用的帳號被擋', async () => {
  const { call, sql } = setup();
  assert.equal((await call('POST', '/admin/login', { form: { username: 'owner', password: 'nope' } })).status, 401);
  const ok = await call('POST', '/admin/login', { form: { username: 'owner', password: 'legacy-pass-1' } });
  assert.equal(ok.status, 303);
  assert.equal((await call('GET', '/admin/')).status, 200);
  sql.exec("UPDATE admin_users SET is_active = 0 WHERE username = 'owner'");
  const denied = await call('GET', '/admin/');
  assert.equal(denied.status, 303);
  assert.equal(denied.location, '/admin/login?denied=1');
});

test('皮拉提斯名額：同時段最多 4 個名額，1對2 佔 2 個；同教練同時段不能重複', async () => {
  const { call, sql } = setup();
  sql.exec("INSERT INTO members (member_no, name, role) VALUES ('C2', 'YOKO', 'coach'), ('C3', 'DK', 'coach'), ('C4', 'MUMU', 'coach')");
  await call('POST', '/admin/login', { form: { username: 'owner', password: 'legacy-pass-1' } });
  const mk = async (coach, ids) => (await call('POST', '/admin/contracts', { json: { coach_id: coach, member_ids: ids, course_type: 'pilates', purchase_date: '2026-10-01', unit_price: 1000, total_sessions: 10 } })).data.id;
  const pairA = await mk(1, [2, 3]);
  const single = await mk(6, [4]);
  const single2 = await mk(7, [5]);
  const pairB = await mk(8, [4, 5]);
  const book = (contract_id) => call('POST', '/admin/bookings', { json: { contract_id, slot_date: '2026-10-30', slot_start_time: '10:00:00' } });
  assert.equal((await book(pairA)).status, 200);
  assert.equal((await book(single)).status, 200);
  const dup = await book(single);
  assert.equal(dup.status, 400);
  assert.match(dup.data.detail, /已經有其他預約/);
  assert.equal((await book(single2)).status, 200); // 2 + 1 + 1 = 4
  const full = await book(pairB);
  assert.equal(full.status, 400);
  assert.match(full.data.detail, /名額已滿（目前 4\/4，還需要 2 個名額）/);
});

test('現金結帳：期初＋現金收款＋收入異動−支出異動＝應有；下一班接著算；作廢後重點', async () => {
  const { call } = setup();
  await call('POST', '/admin/login', { form: { username: 'owner', password: 'legacy-pass-1' } });
  const today = new Date(Date.now() + 8 * 3600_000).toISOString().slice(0, 10);
  assert.equal((await call('POST', '/admin/cash/settings/float', { json: { amount: 3000 } })).data.cash_float, 3000);
  await call('POST', '/admin/revenue', { json: { entry_date: today, item_category: 'beverage', item_name: '水', payment_method: ' 現金', amount: 20.5 } });
  await call('POST', '/admin/revenue', { json: { entry_date: today, item_category: 'beverage', item_name: '水', payment_method: '匯款', amount: 999 } });
  await call('POST', '/admin/cash/movements', { json: { entry_date: today, movement_type: 'petty_cash', amount: 100.25, description: '洗手液' } });
  const first = await call('POST', '/admin/cash/closings', { json: { business_date: today, shift: 'morning', denominations: { 1000: 2, 500: 1, 100: 4 }, collected_amount: 0 } });
  assert.equal(first.status, 200);
  const page = await call('GET', `/admin/cash/closings/${first.data.id}/page`);
  // 應有 = 3000 + 20.5 − 100.25 = 2920.25；實點 2900 → 短少 20.25
  assert.match(page.text, /短少 \$20\.25/);
  assert.match(page.text, /\$2,920\.25/);
  assert.equal((await call('POST', '/admin/cash/closings', { json: { business_date: today, shift: 'morning', denominations: {} } })).status, 400);
  assert.equal((await call('POST', `/admin/cash/closings/${first.data.id}/void`, { json: { reason: '點錯' } })).status, 200);
  const again = await call('POST', '/admin/cash/closings', { json: { business_date: today, shift: 'morning', denominations: { 2000: 1, 500: 1, 100: 4, 10: 2 }, collected_amount: 0 } });
  assert.equal(again.status, 200);
  assert.match((await call('GET', `/admin/cash/closings/${again.data.id}/page`)).text, /短少 \$0\.25/);
});

test('舊資料匯入：試跑不寫入、正式匯入筆數與金額一致、比對不符時整批不生效', async () => {
  const { db, sql } = setup();
  const bundle = {
    format: 'ultra-legacy-v1', staff_coaches: ['nick'], venue_coaches: ['ELSA'],
    contracts: [
      { contract_no: '00001', coach: 'NICK', course_type: 'strength', purchase_date: '2025-01-05', unit_price: 1500, total_sessions: 2, status: 'active', students: ['王'], sessions: [{ no: 1, date: '2025-01-06' }, { no: 2, date: '2025-01-07' }, { no: 3, date: null, raw: '1.32' }] },
      { contract_no: '00002', coach: 'elsa', course_type: 'pilates', purchase_date: '2025-01-01', unit_price: 900, total_sessions: 1, status: 'free', students: ['李', '王'], sessions: [] },
    ],
    revenue: [{ entry_date: '2025-01-05', item_category: 'coaching', item_name: '課', coach: 'NICK', payment_method: '現金', amount: 3000, note: '1' }],
    issues: [],
  };
  const before = sql.prepare('SELECT count(*) AS n FROM contracts').get().n;
  const dry = await runImport(db, bundle, { batch: 'legacy-test', clearExisting: false, commit: false });
  assert.equal(dry.committed, false);
  assert.equal(sql.prepare('SELECT count(*) AS n FROM contracts').get().n, before, '試跑不寫入');
  const done = await runImport(db, bundle, { batch: 'legacy-test', clearExisting: false, commit: true });
  assert.equal(done.matches, true);
  assert.deepEqual(done.db, { contracts: 2, sessions: 3, students: 2, revenue_rows: 1, revenue_sum: 3000 });
  assert.equal(done.revenue_linked_to_contract, 1);
  assert.equal(sql.prepare("SELECT used_sessions AS n FROM contracts WHERE contract_no = '00001'").get().n, 2, '已上堂數以合約堂數為上限');
  assert.equal(sql.prepare("SELECT count(*) AS n FROM members WHERE role = 'coach'").get().n, 1, 'NICK 不分大小寫對到既有教練');
  // 比對失敗的保護：直接驗證 import_guard（數字不符時整批都不寫）
  await assert.rejects(db.batch([db.prep("INSERT INTO members (member_no, name) VALUES ('X1', 'x')"), db.prep('INSERT INTO import_guard (ok) SELECT 0')]));
  assert.equal(sql.prepare("SELECT count(*) AS n FROM members WHERE member_no = 'X1'").get().n, 0);
  await assert.rejects(runImport(db, bundle, { batch: 'legacy-2', clearExisting: false, commit: true }), /已經匯入過/);
});

test('遠端備份：讀取金鑰不能下載；備份可以完整還原到另一個資料庫', async () => {
  const { call } = setup();
  await call('POST', '/admin/login', { form: { username: 'owner', password: 'legacy-pass-1' } });
  await call('POST', '/admin/contracts', { json: { coach_id: 1, member_ids: [2], purchase_date: '2026-10-01', unit_price: 1234.5, total_sessions: 3 } });
  await call('POST', '/admin/cash/settings/float', { json: { amount: 3000 } });
  assert.equal((await call('GET', '/api/remote/backup', { headers: { authorization: `Bearer ${READ}` } })).status, 403);
  const backup = (await call('GET', '/api/remote/backup', { headers: { authorization: `Bearer ${WRITE}` } })).data;
  assert.equal(backup.tables.contracts[0].unit_price, '1234.50');
  const other = createSqliteBinding();
  other.sqlite.exec(migrationsSql());
  for (const s of toStatements(backup)) other.sqlite.exec(s);
  const report = compare(backup, (t) => other.sqlite.prepare(`SELECT * FROM ${t}`).all());
  for (const r of report) assert.equal(r.missing + r.extra, 0, JSON.stringify(r));
  const stats = await call('GET', '/api/remote/stats?month=2026-10', { headers: { authorization: `Bearer ${READ}` } });
  assert.equal(stats.data.gym.newContracts, 1);
});

test('小工具：金額顯示、時間格式、月曆', () => {
  assert.equal(ntd(1500), '1,500');
  assert.equal(ntd(-20.25), '-20.25');
  assert.equal(ntd(0.5), '0.50');
  assert.equal(fmt0(2.5), '2');
  assert.equal(fmt0(3.5), '4');
  assert.equal(normalizeInstant('2026-10-20T03:00:00.123456+00:00'), '2026-10-20T03:00:00.123456Z');
  assert.equal(normalizeInstant('2026-10-20 11:00:00'), '2026-10-20T11:00:00.000000Z');
  assert.equal(normalizeInstant('2026-10-20T11:00:00+08:00'), '2026-10-20T03:00:00.000000Z');
  const weeks = monthWeeks(2026, 10);
  assert.equal(weeks[0][0], '2026-09-28'); // 週一開頭
  assert.equal(weeks.at(-1)[6], '2026-11-01');
});

test('會籍營收自動延長／新建會員；體驗課佔時段與名額並記營收；刪除營收與會員', async () => {
  const { call, sql } = setup();
  await call('POST', '/admin/login', { form: { username: 'owner', password: 'legacy-pass-1' } });
  const rev = (json) => call('POST', '/admin/revenue', { json: { entry_date: '2026-10-23', item_category: 'membership', payment_method: '現金', ...json } });

  // 既有會員：單月 → 10/23～11/22；還沒到期再買半年 → 接在 11/23 之後
  let r = await rev({ item_name: '單月會籍', amount: 1500, customer_name: '甲' });
  assert.equal(r.status, 200);
  assert.deepEqual([r.data.membership.start, r.data.membership.until, r.data.membership.created], ['2026-10-23', '2026-11-22', false]);
  r = await rev({ item_name: '半年會籍', amount: 4800, customer_name: '甲' });
  assert.deepEqual([r.data.membership.start, r.data.membership.until], ['2026-10-23', '2027-05-22']);
  // 沒有這個人 → 自動建立會員、自動編號
  r = await rev({ item_name: '年繳會籍', amount: 7200, customer_name: '新朋友' });
  assert.equal(r.data.membership.created, true);
  assert.equal(r.data.membership.until, '2027-10-22');
  assert.match(r.data.membership.member_no, /^UF\d{4}$/);
  // 週期會籍沒填姓名 → 擋下；單次會籍不用
  assert.equal((await rev({ item_name: '單月會籍', amount: 1500 })).status, 400);
  assert.equal((await rev({ item_name: '單次會籍', amount: 250 })).status, 200);
  // 同名兩人 → 要求帶會員編號
  sql.exec("INSERT INTO members (member_no, name, role) VALUES ('UF0100', '甲', 'student')");
  assert.equal((await rev({ item_name: '單月會籍', amount: 1500, customer_name: '甲' })).status, 400);
  assert.equal((await rev({ item_name: '單月會籍', amount: 1500, customer_name: '甲（UF0100）' })).status, 200);

  // 體驗課：佔教練時段、記一筆營收；同時段再約合約課被擋；取消會刪營收
  const t = await call('POST', '/admin/trial-bookings', { json: { coach_id: 1, area: 'strength', slot_date: '2026-10-24', slot_start_time: '10:00', customer_name: '體驗者', payment_method: '現金' } });
  assert.equal(t.status, 200, t.text);
  assert.equal(sql.prepare("SELECT amount FROM revenue_details WHERE item_name = 'PT體驗' AND customer_name = '體驗者'").get().amount, 500);
  const k = (await call('POST', '/admin/contracts', { json: { coach_id: 1, member_ids: [2], course_type: 'strength', purchase_date: '2026-10-01', unit_price: 1000, total_sessions: 10 } })).data.id;
  assert.equal((await call('POST', '/admin/bookings', { json: { coach_id: 1, contract_id: k, slot_date: '2026-10-24', slot_start_time: '10:00' } })).status, 400);
  assert.equal((await call('POST', `/admin/trial-bookings/${t.data.id}/cancel`)).data.revenue_removed, true);
  assert.equal(sql.prepare("SELECT count(*) n FROM revenue_details WHERE customer_name = '體驗者'").get().n, 0);
  // 皮拉提斯體驗佔 1 個名額：4 個體驗後第 5 個被擋
  sql.exec("INSERT INTO members (member_no, name, role) VALUES ('C2', 'YOKO', 'coach'), ('C3', 'DK', 'coach'), ('C4', 'MUMU', 'coach'), ('C5', 'NINA', 'coach')");
  const coachIds = sql.prepare("SELECT id FROM members WHERE role = 'coach' ORDER BY id").all().map((x) => x.id);
  for (const [i, cid] of coachIds.entries()) {
    const res = await call('POST', '/admin/trial-bookings', { json: { coach_id: cid, area: 'pilates', slot_date: '2026-10-25', slot_start_time: '09:00', customer_name: `P${i}` } });
    assert.equal(res.status, i < 4 ? 200 : 400, `第 ${i + 1} 位`);
  }

  // 刪除營收；刪除會員：有紀錄 → 停用，沒紀錄 → 刪除
  const one = sql.prepare("SELECT id FROM revenue_details WHERE item_name = '單次會籍'").get().id;
  assert.equal((await call('POST', `/admin/revenue/${one}/delete`)).status, 200);
  assert.equal((await call('POST', '/admin/members/2/delete')).data.status, 'deactivated');
  sql.exec("INSERT INTO members (member_no, name, role) VALUES ('UF0200', '打錯的人', 'student')");
  const wrong = sql.prepare("SELECT id FROM members WHERE member_no = 'UF0200'").get().id;
  assert.equal((await call('POST', `/admin/members/${wrong}/delete`)).data.status, 'deleted');
  // 會員編號留空 → 自動編號
  const auto = await call('POST', '/admin/members', { json: { name: '自動編號', role: 'student' } });
  assert.match(auto.data.member_no, /^UF\d{4}$/);
});
