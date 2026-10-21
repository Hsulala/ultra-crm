// 新舊版比對（開發用，不在 npm test 裡）：
//   舊版：Python（FastAPI）跑在 http://localhost:8081，資料庫是 SQLite
//   新版：這個 Worker，用 Node 內建 SQLite 模擬 D1，資料從舊版 /api/remote/backup 匯入
// 兩邊做完全相同的操作，比對：每個 API 回應、所有頁面的 HTML、最後兩邊的整份資料（扣掉時間欄位）。
//   node test/compare.mjs
import { DatabaseSync } from 'node:sqlite';
import { app } from '../src/index.js';
import { createSqliteBinding } from './sqlite-d1.js';
import { migrationsSql, toStatements } from '../scripts/import-backup.mjs';

const PY = process.env.PY_BASE ?? 'http://localhost:8081';
const JS = 'http://ultra.test';
const READ = 'r'.repeat(40);
const WRITE = 'w'.repeat(40);
const ADMIN = { username: 'uly', password: 'ref-password-123' };

const binding = createSqliteBinding(':memory:');
binding.sqlite.exec(migrationsSql());
const env = { DB: binding, SESSION_SECRET_KEY: 's'.repeat(40), REMOTE_READ_KEY: READ, REMOTE_WRITE_KEY: WRITE, DEV_MODE: 'true' };

async function pyBackup() {
  const r = await fetch(`${PY}/api/remote/backup`, { headers: { authorization: `Bearer ${WRITE}` } });
  return r.json();
}

// ---- 兩個用戶端（各自保存 Cookie） ----
function client(kind) {
  let cookie = '';
  return async (method, path, { json, form, multipart, headers = {} } = {}) => {
    const h = { ...headers };
    if (cookie) h.cookie = cookie;
    let body;
    if (json !== undefined) { h['content-type'] = 'application/json'; body = JSON.stringify(json); }
    if (form) { h['content-type'] = 'application/x-www-form-urlencoded'; body = new URLSearchParams(form).toString(); }
    if (multipart) body = multipart();
    const url = (kind === 'py' ? PY : JS) + path;
    const req = new Request(url, { method, headers: h, body, redirect: 'manual' });
    const res = kind === 'py' ? await fetch(req) : await app.fetch(req, env);
    const set = res.headers.get('set-cookie');
    if (set) { const v = set.split(';')[0]; cookie = /=$/.test(v) || /=""$/.test(v) || /Max-Age=0/i.test(set) ? '' : v; }
    const text = await res.text();
    let data = null; try { data = JSON.parse(text); } catch { /* HTML */ }
    return { status: res.status, location: res.headers.get('location'), text, data };
  };
}

const py = client('py');
const js = client('js');
const problems = [];
let checks = 0;

// 比對時略過：時間戳記、綁定碼（隨機）
const VOLATILE = /^(created_at|updated_at|expires_at|used_at|submitted_at|closed_at|interval_start|reviewed_at|voided_at|code|exportedAt|batch)$/;
function scrub(v) {
  if (Array.isArray(v)) return v.map(scrub);
  if (v && typeof v === 'object') return Object.fromEntries(Object.entries(v).filter(([k]) => !VOLATILE.test(k)).map(([k, x]) => [k, scrub(x)]));
  return v;
}
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

async function both(label, method, path, opts = {}, { html = false, ignore = [] } = {}) {
  const [a, b] = [await py(method, path, opts), await js(method, path, opts)];
  checks += 1;
  if (a.status !== b.status) { problems.push(`${label}：狀態碼 舊 ${a.status}／新 ${b.status}\n  舊：${a.text.slice(0, 300)}\n  新：${b.text.slice(0, 300)}`); return [a, b]; }
  const loc = (l) => l?.replace(/^https?:\/\/[^/]+/, '');
  if (loc(a.location) !== loc(b.location)) problems.push(`${label}：轉址 舊 ${a.location}／新 ${b.location}`);
  if (html) {
    const [x, y] = [normHtml(a.text, ignore), normHtml(b.text, ignore)];
    if (x !== y) problems.push(`${label}：HTML 不同\n${firstDiff(x, y)}`);
  } else if (a.status === 422) {
    // 欄位格式錯誤：前端只看 detail 是不是陣列，比對出錯的欄位就好
    const locs = (d) => JSON.stringify((d?.detail ?? []).map((e) => e.loc));
    if (locs(a.data) !== locs(b.data)) problems.push(`${label}：422 欄位不同 舊 ${locs(a.data)}／新 ${locs(b.data)}`);
  } else if (a.data !== null || b.data !== null) {
    if (!same(scrub(a.data), scrub(b.data))) problems.push(`${label}：回應不同\n  舊：${JSON.stringify(scrub(a.data)).slice(0, 600)}\n  新：${JSON.stringify(scrub(b.data)).slice(0, 600)}`);
  }
  return [a, b];
}

function normHtml(s, ignore) {
  let t = s.replace(/\s+/g, ' ').replace(/>\s+</g, '><').replace(/\s+>/g, '>').trim();
  for (const re of ignore) t = t.replace(re, '«略»');
  return t;
}
function firstDiff(a, b) {
  let i = 0; while (i < a.length && a[i] === b[i]) i += 1;
  return `  舊：…${a.slice(Math.max(0, i - 120), i + 200)}\n  新：…${b.slice(Math.max(0, i - 120), i + 200)}`;
}

// ---- 1. 舊版資料匯入新版 ----
const initial = await pyBackup();
for (const s of toStatements(initial)) binding.sqlite.exec(s);
console.log('已把舊版資料匯入新版');

// ---- 2. 登入 ----
await both('登入頁', 'GET', '/admin/login', {}, { html: true });
await both('登入失敗', 'POST', '/admin/login', { form: { username: 'uly', password: 'wrong' } }, { html: true });
await both('未登入看總覽', 'GET', '/admin/');
await both('登入', 'POST', '/admin/login', { form: ADMIN });

const today = new Date(Date.now() + 8 * 3600_000).toISOString().slice(0, 10);
const addDays = (d, n) => { const x = new Date(`${d}T00:00:00Z`); x.setUTCDate(x.getUTCDate() + n); return x.toISOString().slice(0, 10); };
const tomorrow = addDays(today, 1);

// ---- 3. 一連串操作 ----
const steps = [
  ['新增學員', 'POST', '/admin/members', { json: { member_no: 'UF9001', name: '測試學員甲', role: 'student' } }],
  ['新增學員乙', 'POST', '/admin/members', { json: { member_no: 'UF9002', name: '測試學員乙', role: 'student', membership_start_date: today, membership_active_until: addDays(today, 30) } }],
  ['新增教練', 'POST', '/admin/members', { json: { member_no: 'C9001', name: '測試教練', role: 'coach' } }],
  ['會員編號重複', 'POST', '/admin/members', { json: { member_no: 'UF9001', name: 'x', role: 'student' } }],
  ['身分錯誤', 'POST', '/admin/members', { json: { member_no: 'UF9003', name: 'x', role: 'boss' } }],
  ['缺欄位', 'POST', '/admin/members', { json: { name: 'x' } }],
  ['改會籍', 'POST', '/admin/members/12/membership', { json: { membership_start_date: today, membership_active_until: null } }],
  ['改會籍：找不到', 'POST', '/admin/members/99999/membership', { json: {} }],
  ['新增場租教練', 'POST', '/admin/venue-coaches', { json: { name: ' 測試場租 ', phone: '0900' } }],
  ['改場租教練', 'POST', '/admin/venue-coaches/16', { json: { name: '測試場租改', phone: null } }],
  ['停用場租教練', 'POST', '/admin/venue-coaches/15/deactivate'],
  ['啟用場租教練', 'POST', '/admin/venue-coaches/15/activate'],
  ['場租教練找不到', 'POST', '/admin/venue-coaches/999/deactivate'],
  ['合約：重訓', 'POST', '/admin/contracts', { json: { coach_id: 1, member_ids: [12], course_type: 'strength', purchase_date: today, unit_price: 1500, total_sessions: 10, contract_no: '09001' } }],
  ['合約：皮拉提斯 1對2＋新學員', 'POST', '/admin/contracts', { json: { coach_id: 2, member_ids: [13], course_type: 'pilates', purchase_date: today, unit_price: 2200.5, total_sessions: 12, new_student_name: '新同學' } }],
  ['合約：場租教練皮拉提斯', 'POST', '/admin/contracts', { json: { venue_coach_id: 1, member_ids: [12], course_type: 'pilates', purchase_date: addDays(today, -40), unit_price: 1800, total_sessions: 1, status: 'free' } }],
  ['合約：場租教練不能開重訓', 'POST', '/admin/contracts', { json: { venue_coach_id: 1, member_ids: [12], course_type: 'strength', purchase_date: today, unit_price: 1, total_sessions: 1 } }],
  ['合約：沒選教練', 'POST', '/admin/contracts', { json: { member_ids: [12], purchase_date: today, unit_price: 1, total_sessions: 1 } }],
  ['合約：會員不存在', 'POST', '/admin/contracts', { json: { coach_id: 1, member_ids: [12, 9999], purchase_date: today, unit_price: 1, total_sessions: 1 } }],
  ['合約：沒有學員', 'POST', '/admin/contracts', { json: { coach_id: 1, member_ids: [], purchase_date: today, unit_price: 1, total_sessions: 1 } }],
  ['合約：教練不是教練', 'POST', '/admin/contracts', { json: { coach_id: 12, member_ids: [13], purchase_date: today, unit_price: 1, total_sessions: 1 } }],
  ['合約：格式錯', 'POST', '/admin/contracts', { json: { coach_id: 1, member_ids: [12], purchase_date: 'abc', unit_price: 'x', total_sessions: 1 } }],
  ['約課：重訓', 'POST', '/admin/bookings', { json: { coach_id: 1, contract_id: 4, slot_date: today, slot_start_time: '10:00:00' } }],
  ['約課：同教練同時段', 'POST', '/admin/bookings', { json: { coach_id: 1, contract_id: 4, slot_date: today, slot_start_time: '10:00:00' } }],
  ['約課：皮拉提斯 1對2（2 名額）', 'POST', '/admin/bookings', { json: { contract_id: 5, slot_date: today, slot_start_time: '11:00:00' } }],
  ['約課：皮拉提斯 場租（1 名額）', 'POST', '/admin/bookings', { json: { contract_id: 6, slot_date: today, slot_start_time: '11:00:00' } }],
  ['約課：合約不存在', 'POST', '/admin/bookings', { json: { contract_id: 999, slot_date: today, slot_start_time: '11:00:00' } }],
  ['約課：時間格式', 'POST', '/admin/bookings', { json: { contract_id: 4, slot_date: today, slot_start_time: '25:00' } }],
  ['取消約課', 'POST', '/admin/bookings/1/cancel'],
  ['取消約課：找不到', 'POST', '/admin/bookings/999/cancel'],
  ['場租約課', 'POST', '/admin/venue-bookings', { json: { venue_coach_id: 2, customer_name: '王先生', party_size: 2, slot_date: today, slot_start_time: '16:00:00', slot_number: 1 } }],
  ['場租約課：同檔期', 'POST', '/admin/venue-bookings', { json: { venue_coach_id: 3, customer_name: '李小姐', slot_date: today, slot_start_time: '16:00:00', slot_number: 1 } }],
  ['場租約課：檔期 4', 'POST', '/admin/venue-bookings', { json: { venue_coach_id: 3, customer_name: '李小姐', slot_date: today, slot_start_time: '16:00:00', slot_number: 4 } }],
  ['場租約課：人數 3', 'POST', '/admin/venue-bookings', { json: { venue_coach_id: 3, customer_name: '李小姐', party_size: 3, slot_date: today, slot_start_time: '17:00:00', slot_number: 2 } }],
  ['場租約課：明天', 'POST', '/admin/venue-bookings', { json: { venue_coach_id: 3, customer_name: '陳先生', slot_date: tomorrow, slot_start_time: '09:00:00', slot_number: 3, customer_phone: '0911' } }],
  ['取消場租', 'POST', '/admin/venue-bookings/2/cancel'],
  ['紀錄課程', 'POST', '/admin/class-records', { json: { coach_id: 1, contract_id: 4, class_date: today, content_summary: '深蹲 5x5' } }],
  ['紀錄課程：合約不存在', 'POST', '/admin/class-records', { json: { coach_id: 1, contract_id: 999, class_date: today, content_summary: 'x' } }],
  ['收款：現金', 'POST', '/admin/revenue', { json: { entry_date: today, item_category: 'coaching', item_name: '私人教練 10 堂', payment_method: '現金', amount: 15000, coach_id: 1, contract_id: 4 } }],
  ['收款：Cash 寫法', 'POST', '/admin/revenue', { json: { entry_date: today, item_category: 'beverage', item_name: '蛋白飲', payment_method: ' Cash ', amount: 80.5 } }],
  ['收款：匯款末五碼', 'POST', '/admin/revenue', { json: { entry_date: today, item_category: 'membership', item_name: '單月會籍', payment_method: '匯款', amount: 2000, remittance_last5: '12345' } }],
  ['收款：末五碼錯', 'POST', '/admin/revenue', { json: { entry_date: today, item_category: 'membership', item_name: '單月會籍', payment_method: '匯款', amount: 2000, remittance_last5: '12a45' } }],
  ['收款：補登昨天', 'POST', '/admin/revenue', { json: { entry_date: addDays(today, -1), item_category: 'service', item_name: '毛巾', payment_method: '現 金', amount: 30 } }],
  ['收款：上個月', 'POST', '/admin/revenue', { json: { entry_date: addDays(today, -35), item_category: 'custom', item_name: '自訂', payment_method: '信用卡', amount: 999 } }],
  ['結帳：還沒設零用金', 'POST', '/admin/cash/closings', { json: { business_date: today, shift: 'morning', denominations: { 1000: 3 } } }],
  ['設零用金', 'POST', '/admin/cash/settings/float', { json: { amount: 3000 } }],
  ['零用金負數', 'POST', '/admin/cash/settings/float', { json: { amount: -1 } }],
  ['現金異動：支出', 'POST', '/admin/cash/movements', { json: { entry_date: today, movement_type: 'petty_cash', amount: 120, counterparty: ' 全聯 ', description: '洗手液' } }],
  ['現金異動：歸還', 'POST', '/admin/cash/movements', { json: { entry_date: today, movement_type: 'advance_return', amount: 500, description: '教練還錢' } }],
  ['現金異動：沒原因', 'POST', '/admin/cash/movements', { json: { entry_date: today, movement_type: 'refund', amount: 100, description: ' ' } }],
  ['現金異動：類型錯', 'POST', '/admin/cash/movements', { json: { entry_date: today, movement_type: 'x', amount: 100, description: 'a' } }],
  ['現金異動：未來', 'POST', '/admin/cash/movements', { json: { entry_date: tomorrow, movement_type: 'refund', amount: 100, description: 'a' } }],
  ['作廢異動', 'POST', '/admin/cash/movements/1/void', { json: { reason: '記錯' } }],
  ['作廢異動：再一次', 'POST', '/admin/cash/movements/1/void', { json: { reason: '記錯' } }],
  ['作廢異動：沒原因', 'POST', '/admin/cash/movements/2/void', { json: { reason: '' } }],
  ['結帳：面額錯', 'POST', '/admin/cash/closings', { json: { business_date: today, shift: 'morning', denominations: { 3: 1 } } }],
  ['結帳：張數非整數', 'POST', '/admin/cash/closings', { json: { business_date: today, shift: 'morning', denominations: { 1000: 1.5 } } }],
  ['結帳：收走太多', 'POST', '/admin/cash/closings', { json: { business_date: today, shift: 'morning', denominations: { 1000: 1 }, collected_amount: 2000 } }],
  ['結帳：未來', 'POST', '/admin/cash/closings', { json: { business_date: tomorrow, shift: 'morning', denominations: {} } }],
  ['結帳：班次錯', 'POST', '/admin/cash/closings', { json: { business_date: today, shift: 'night', denominations: {} } }],
  ['結帳：早班', 'POST', '/admin/cash/closings', { json: { business_date: today, shift: 'morning', denominations: { 1000: 18, 500: 1, 100: 3, 10: 4, 1: 1 }, collected_amount: 0, note: ' ' } }],
  ['結帳：早班重複', 'POST', '/admin/cash/closings', { json: { business_date: today, shift: 'morning', denominations: {} } }],
  ['結帳說明', 'POST', '/admin/cash/closings/1/note', { json: { note: '少了零錢' } }],
  ['覆核', 'POST', '/admin/cash/closings/1/review', { json: { note: '已確認' } }],
  ['作廢結帳', 'POST', '/admin/cash/closings/1/void', { json: { reason: '點錯' } }],
  ['重新結帳', 'POST', '/admin/cash/closings', { json: { business_date: today, shift: 'morning', denominations: { 2000: 9, 500: 1, 100: 3, 50: 1, 10: 1, 5: 1 }, collected_amount: 15000 } }],
  ['再收一筆現金', 'POST', '/admin/revenue', { json: { entry_date: today, item_category: 'beverage', item_name: '水', payment_method: '現金', amount: 20 } }],
  ['結帳：中班', 'POST', '/admin/cash/closings', { json: { business_date: today, shift: 'afternoon', denominations: { 1000: 3, 10: 2 }, collected_amount: 0 } }],
  ['作廢舊的結帳（不是最新）', 'POST', '/admin/cash/closings/2/void', { json: { reason: 'x' } }],
  ['排班：教練', 'POST', '/admin/schedule', { json: { work_date: today, shift: 'evening', coach_id: 1 } }],
  ['排班：櫃檯', 'POST', '/admin/schedule', { json: { work_date: tomorrow, shift: 'morning', admin_user_id: 1 } }],
  ['排班：兩者都填', 'POST', '/admin/schedule', { json: { work_date: today, shift: 'evening', coach_id: 1, admin_user_id: 1 } }],
  ['發布班表', 'POST', '/admin/schedule/publish', { json: { year: Number(today.slice(0, 4)), month: Number(today.slice(5, 7)) } }],
  ['移除排班', 'POST', '/admin/schedule/4/remove'],
  ['移除排班：找不到', 'POST', '/admin/schedule/999/remove'],
  ['品項：新增', 'POST', '/admin/settings/items', { json: { item_category: 'beverage', item_name: '測試飲料', default_price: 55 } }],
  ['品項：分類錯', 'POST', '/admin/settings/items', { json: { item_category: 'food', item_name: 'x' } }],
  ['品項：修改', 'POST', '/admin/settings/items/147', { json: { default_price: null } }],
  ['品項：停用', 'POST', '/admin/settings/items/146/deactivate'],
  ['帳號：櫃檯', 'POST', '/admin/accounts', { json: { username: 'desk', password: 'desk-password-1', role: 'front_desk' } }],
  ['帳號：教練', 'POST', '/admin/accounts', { json: { username: 'coach1', password: 'coach-password-1', role: 'coach', linked_member_id: 1 } }],
  ['帳號：重複', 'POST', '/admin/accounts', { json: { username: 'desk', password: 'x', role: 'front_desk' } }],
  ['帳號：角色錯', 'POST', '/admin/accounts', { json: { username: 'x', password: 'x', role: 'god' } }],
  ['帳號：停用自己', 'POST', '/admin/accounts/1/deactivate'],
  ['帳號：停用', 'POST', '/admin/accounts/3/deactivate'],
  ['帳號：啟用', 'POST', '/admin/accounts/3/activate'],
  ['綁定碼：會員', 'POST', '/admin/members/12/binding-code'],
  ['綁定碼：場租', 'POST', '/admin/venue-coaches/2/binding-code'],
  ['綁定碼：找不到', 'POST', '/admin/members/999/binding-code'],
];
// 舊版在 SQLite 上的 created_at 只到秒，結帳時間有微秒：同一秒內的收款會被算錯區間（PostgreSQL 不會）。
// 結帳前後各等 1.1 秒，避開這個只有參考環境才有的誤差。
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
for (const [label, method, path, opts] of steps) {
  const cashStep = path === '/admin/cash/closings' || label === '再收一筆現金';
  if (cashStep) await sleep(1100);
  await both(label, method, path, opts ?? {});
  if (cashStep) await sleep(1100);
}

// ---- 4. 頁面 ----
const ym = today.slice(0, 7);
const prevYm = addDays(`${ym}-01`, -1).slice(0, 7);
const pages = [
  '/admin/', `/admin/?d=${tomorrow}`, `/admin/?d=${addDays(today, -1)}`, '/admin', '/admin/members/page', '/admin/members/page?q=測試', '/admin/members/page?page=3',
  '/admin/contracts/page', '/admin/contracts/page?view=all', '/admin/contracts/page?view=done', '/admin/contracts/page?view=refunded',
  '/admin/contracts/page?view=all&course=pilates', '/admin/contracts/page?q=測試&view=all', '/admin/contracts/page?view=bogus&page=0',
  '/admin/class-records/page', '/admin/class-records/page?coach_id=2', '/admin/revenue/page', '/admin/revenue/page?tab=month', `/admin/revenue/page?ym=${prevYm}`,
  '/admin/revenue/page?year=2099&month=1', '/admin/cash/page', '/admin/cash/closings/1/page', '/admin/cash/closings/2/page', '/admin/cash/closings/3/page', '/admin/cash/closings/99/page',
  '/admin/schedule/page', `/admin/schedule/page?year=${Number(today.slice(0, 4)) + 1}&month=2`, '/admin/venue-coaches/page', '/admin/settings/items/page',
  '/admin/accounts/page', '/admin/legacy-import/page',
];
for (const p of pages) await both(`頁面 ${p}`, 'GET', p, {}, { html: true });
const jsonGets = [
  `/admin/schedule?year=${today.slice(0, 4)}&month=${Number(today.slice(5, 7))}`, `/admin/revenue/daily-summary?date=${today}`,
  `/admin/revenue/monthly-summary?year=${today.slice(0, 4)}&month=${Number(today.slice(5, 7))}`, `/admin/revenue/coach-performance?year=${today.slice(0, 4)}&month=${Number(today.slice(5, 7))}`,
  '/admin/schedule', '/admin/nope', '/admin/members/page?page=x',
];
for (const p of jsonGets) await both(`API ${p}`, 'GET', p);
await both('遠端統計', 'GET', `/api/remote/stats?month=${ym}`, { headers: { authorization: `Bearer ${READ}` } });
await both('遠端統計：月份錯', 'GET', '/api/remote/stats?month=2026-13', { headers: { authorization: `Bearer ${READ}` } });
await both('遠端設定', 'GET', '/api/remote/config', { headers: { authorization: `Bearer ${READ}` } });
await both('遠端備份：讀取金鑰不行', 'GET', '/api/remote/backup', { headers: { authorization: `Bearer ${READ}` } });
await both('遠端：金鑰錯', 'GET', '/api/remote/config', { headers: { authorization: 'Bearer nope' } });


// ---- LIFF（本機開發模式：X-Dev-Line-User-Id）----
async function bindBoth(label, issuePath, lineId) {
  const [a, b] = await both(`${label}：產生綁定碼`, 'POST', issuePath);
  const h = { 'X-Dev-Line-User-Id': lineId };
  const ra = await py('POST', '/api/liff/binding/redeem', { json: { code: a.data.code }, headers: h });
  const rb = await js('POST', '/api/liff/binding/redeem', { json: { code: b.data.code }, headers: h });
  checks += 1;
  if (ra.status !== rb.status || !same(ra.data, rb.data)) problems.push(`${label}：兌換結果不同\n  舊：${ra.text}\n  新：${rb.text}`);
}
await bindBoth('學員綁定', '/admin/members/12/binding-code', 'U-student-12');
await bindBoth('學員乙綁定', '/admin/members/13/binding-code', 'U-student-13');
await bindBoth('教練綁定', '/admin/members/1/binding-code', 'U-coach-1');
await bindBoth('場租綁定', '/admin/venue-coaches/3/binding-code', 'U-venue-3');
await both('兌換：錯的碼', 'POST', '/api/liff/binding/redeem', { json: { code: '000000' }, headers: { 'X-Dev-Line-User-Id': 'U-x' } });
await both('兌換：沒 token', 'POST', '/api/liff/binding/redeem', { json: { code: '000000' } });
const S = { headers: { 'X-Dev-Line-User-Id': 'U-student-12' } };
const S2 = { headers: { 'X-Dev-Line-User-Id': 'U-student-13' } };
const C = { headers: { 'X-Dev-Line-User-Id': 'U-coach-1' } };
const V = { headers: { 'X-Dev-Line-User-Id': 'U-venue-3' } };
await both('LIFF 我的合約', 'GET', '/api/liff/contracts/mine', S);
await both('LIFF 我的合約（1對2）', 'GET', '/api/liff/contracts/mine', S2);
await both('LIFF 我的合約：教練不行', 'GET', '/api/liff/contracts/mine', C);
await both('LIFF 未綁定', 'GET', '/api/liff/contracts/mine', { headers: { 'X-Dev-Line-User-Id': 'U-none' } });
await both('LIFF 上課紀錄', 'GET', '/api/liff/class-records/mine', S);
await both('LIFF 教練合約', 'GET', '/api/liff/class-records/active-contracts', C);
await both('LIFF 教練記課', 'POST', '/api/liff/class-records', { ...C, json: { contract_id: 4, class_date: today, content_summary: '硬舉' } });
await both('LIFF 教練記課：格式錯', 'POST', '/api/liff/class-records', { ...C, json: { contract_id: 4, class_date: 'x' } });
await both('LIFF 學員約課', 'POST', '/api/liff/bookings', { ...S, json: { coach_id: 1, contract_id: 4, slot_date: tomorrow, slot_start_time: '09:00', area: 'strength' } });
await both('LIFF 學員約別人的合約', 'POST', '/api/liff/bookings', { ...S, json: { coach_id: 1, contract_id: 2, slot_date: tomorrow, slot_start_time: '10:00', area: 'strength' } });
await both('LIFF 皮拉提斯滿額', 'POST', '/api/liff/bookings', { ...S2, json: { coach_id: 2, contract_id: 5, slot_date: today, slot_start_time: '11:00', area: 'pilates' } });
await both('LIFF 教練的預約', 'GET', '/api/liff/bookings/mine', C);
await both('LIFF 不排班回報', 'POST', '/api/liff/schedule/unavailability', { ...C, json: { target_month: `${tomorrow.slice(0, 7)}-01`, entries: [{ unavailable_date: tomorrow, shift: 'morning', note: '請假' }, { unavailable_date: tomorrow, shift: 'evening' }] } });
await both('LIFF 不排班回報：班次錯', 'POST', '/api/liff/schedule/unavailability', { ...C, json: { target_month: `${tomorrow.slice(0, 7)}-01`, entries: [{ unavailable_date: tomorrow, shift: 'x' }] } });
await both('LIFF 班表', 'GET', `/api/liff/schedule?year=${today.slice(0, 4)}&month=${Number(today.slice(5, 7))}`, C);
await both('LIFF 場租約課', 'POST', '/api/liff/venue-bookings', { ...V, json: { customer_name: '林先生', slot_date: today, slot_start_time: '16:00:00' } });
await both('LIFF 場租約課（自動找檔期）', 'POST', '/api/liff/venue-bookings', { ...V, json: { customer_name: '吳小姐', party_size: 2, slot_date: today, slot_start_time: '16:00:00' } });
await both('LIFF 場租約課：學員不行', 'POST', '/api/liff/venue-bookings', { ...S, json: { customer_name: 'x', slot_date: today, slot_start_time: '16:00:00' } });
await both('LINE webhook：沒簽章', 'POST', '/line/webhook', { json: { events: [] } });
await both('內部排程：沒密鑰', 'POST', '/internal/cron/daily');
await both('頁面 總覽（含 LIFF 約課後）', 'GET', '/admin/', {}, { html: true });
await both('頁面 會員（已綁定）', 'GET', '/admin/members/page', {}, { html: true });

// ---- 匯入舊資料 ----
const bundle = {
  format: 'ultra-legacy-v1',
  staff_coaches: ['NICK', 'NEWCOACH'],
  venue_coaches: ['ELSA', 'NEWVENUE'],
  contracts: [
    { contract_no: '00001', coach: 'NICK', course_type: 'strength', purchase_date: '2025-01-05', unit_price: 1500, total_sessions: 10, status: 'active', note: null, students: ['舊學員甲'], sessions: [{ no: 1, date: '2025-01-06' }, { no: 2, date: null, raw: '110.8.32' }] },
    { contract_no: '00002', coach: 'newvenue', course_type: 'pilates', purchase_date: '2025-01-03', unit_price: 1800.5, total_sessions: 2, status: 'refunded', note: '已退費', students: ['舊學員乙', '舊學員甲'], sessions: [{ no: 1, date: '2025-01-04' }, { no: 2, date: '2025-01-05' }, { no: 3, date: '2025-01-06' }] },
    { contract_no: '00003', coach: '', course_type: 'pilates', purchase_date: '2025-02-01', unit_price: 900, total_sessions: 1, status: 'free', students: ['舊學員丙'], sessions: [] },
  ],
  revenue: [
    { entry_date: '2025-01-05', item_category: 'coaching', item_name: '教練課', coach: 'NICK', customer_name: '舊學員甲', payment_method: '現金', amount: 15000, note: '1' },
    { entry_date: '2025-01-06', item_category: 'beverage', item_name: '水', payment_method: '匯款', amount: 20.5, note: 'abc' },
  ],
  issues: [{ row: 3, problem: '日期打錯' }],
};
const multipart = (fields) => () => { const f = new FormData(); f.append('bundle', new Blob([JSON.stringify(bundle)], { type: 'application/json' }), 'b.json'); for (const [k, v] of Object.entries(fields)) f.append(k, v); return f; };
await both('匯入：試跑', 'POST', '/admin/legacy-import', { multipart: multipart({ mode: 'dryrun' }) });
await both('匯入：沒輸入確認字', 'POST', '/admin/legacy-import', { multipart: multipart({ mode: 'commit', confirm: '' }) });
await both('匯入：正式', 'POST', '/admin/legacy-import', { multipart: multipart({ mode: 'commit', confirm: '匯入' }) });
await both('匯入：已匯入過', 'POST', '/admin/legacy-import', { multipart: multipart({ mode: 'commit', confirm: '匯入' }) });
await both('頁面 匯入舊資料（匯入後）', 'GET', '/admin/legacy-import/page', {}, { html: true, ignore: [/legacy-\d{8}-\d{4}/g] });
await both('頁面 合約（匯入後）', 'GET', '/admin/contracts/page?view=all', {}, { html: true });
await both('頁面 營收 2025-01', 'GET', '/admin/revenue/page?ym=2025-01', {}, { html: true });

// ---- 5. 其他角色 ----
await both('登出', 'POST', '/admin/logout');
await both('櫃檯登入', 'POST', '/admin/login', { form: { username: 'desk', password: 'desk-password-1' } });
for (const p of ['/admin/', '/admin/revenue/page', '/admin/accounts/page', '/admin/cash/page', '/admin/cash/closings/3/page', '/admin/settings/items/page', '/admin/contracts/page']) await both(`櫃檯 ${p}`, 'GET', p, {}, { html: true });
await sleep(1100);
await both('櫃檯：結帳晚班', 'POST', '/admin/cash/closings', { json: { business_date: today, shift: 'evening', denominations: { 1000: 3 }, collected_amount: 0 } });
await both('櫃檯：寫說明', 'POST', '/admin/cash/closings/4/note', { json: { note: '晚班說明' } });
await both('櫃檯：再改說明', 'POST', '/admin/cash/closings/4/note', { json: { note: '改' } });
await both('櫃檯：覆核（沒權限）', 'POST', '/admin/cash/closings/4/review', { json: {} });
await both('櫃檯：看自己的結帳', 'GET', '/admin/cash/closings/4/page', {}, { html: true });
await both('登出', 'POST', '/admin/logout');
await both('教練登入', 'POST', '/admin/login', { form: { username: 'coach1', password: 'coach-password-1' } });
for (const p of ['/admin/', '/admin/class-records/page', '/admin/members/page', '/admin/cash/page', '/admin/schedule/page']) await both(`教練 ${p}`, 'GET', p, {}, { html: true });
await both('教練：記別人的課', 'POST', '/admin/class-records', { json: { coach_id: 2, contract_id: 5, class_date: today, content_summary: 'x' } });
await both('教練：記自己的課', 'POST', '/admin/class-records', { json: { coach_id: 1, contract_id: 4, class_date: today, content_summary: '臥推' } });
await both('登出', 'POST', '/admin/logout');
await both('停用的帳號登入', 'POST', '/admin/accounts/3/deactivate');
await both('登入', 'POST', '/admin/login', { form: ADMIN });
await both('停用櫃檯', 'POST', '/admin/accounts/2/deactivate');

// ---- 6. 最後的資料 ----
const pyFinal = await pyBackup();
const { compare } = await import('../scripts/import-backup.mjs');
const jsDb = binding.sqlite;
const strip = (backup) => ({ tables: Object.fromEntries(Object.entries(backup.tables).map(([t, rows]) => [t, rows.map((r) => Object.fromEntries(Object.entries(r).filter(([k]) => !VOLATILE.test(k) && k !== 'password_hash')))])) });
const report = compare(strip(pyFinal), (t) => jsDb.prepare(`SELECT * FROM ${t}`).all().map((r) => Object.fromEntries(Object.entries(r).filter(([k]) => !VOLATILE.test(k) && k !== 'password_hash'))));
for (const r of report) if (r.missing || r.extra || r.source !== r.target) problems.push(`資料表 ${r.table}：舊 ${r.source} 筆、新 ${r.target} 筆、缺 ${r.missing}、多 ${r.extra}\n  例：${r.sample?.slice(0, 400)}`);
checks += report.length;

console.log(`\n比對 ${checks} 項，不一致 ${problems.length} 項`);
for (const p of problems) console.log(`\n▸ ${p}`);
process.exit(problems.length ? 1 : 0);
void DatabaseSync;
