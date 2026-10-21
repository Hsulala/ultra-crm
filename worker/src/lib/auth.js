// 登入與權限：對應原本 app/auth/admin.py、line_auth.py、member_auth.py。
import bcrypt from 'bcryptjs';
import { createRemoteJWKSet, jwtVerify } from 'jose';
import { HttpError } from './http.js';
import { clearSession, readSession } from './session.js';

// ---- 密碼（passlib bcrypt 的 $2b$ 雜湊，舊帳號密碼照樣能登入）----
export const hashPassword = (password) => bcrypt.hash(password, 12);
export const verifyPassword = (password, hash) => {
  try { return bcrypt.compare(password, hash); } catch { return Promise.resolve(false); }
};

// ---- 後台帳號 ----
/** 要求已登入、帳號仍啟用（每次都重新查資料庫，停用立刻生效） */
export async function currentAdmin(c) {
  if (c.get('admin')) return c.get('admin');
  const session = await readSession(c, c.env.SESSION_SECRET_KEY);
  const id = session.admin_user_id;
  if (id == null) throw new HttpError(303, 'See Other', { location: '/admin/login' });
  const user = await c.get('db').first('SELECT * FROM admin_users WHERE id = ?', id);
  if (!user || !user.is_active) {
    clearSession(c);
    throw new HttpError(303, 'See Other', { location: '/admin/login?denied=1' });
  }
  c.set('admin', user);
  return user;
}

/** super_admin 一路暢通（原本 require_role 的規則） */
export async function requireRole(c, ...roles) {
  const user = await currentAdmin(c);
  if (user.role !== 'super_admin' && !roles.includes(user.role)) throw new HttpError(403, '沒有權限');
  return user;
}

// ---- LINE LIFF ID Token ----
const LINE_ISSUER = 'https://access.line.me';
let jwks = null;

export async function lineUserId(c) {
  const env = c.env;
  const dev = c.req.header('X-Dev-Line-User-Id');
  // 只給本機開發：正式環境不會設 DEV_MODE
  if (env.DEV_MODE === 'true' && dev) return dev;
  const auth = c.req.header('authorization') ?? '';
  if (!auth.startsWith('Bearer ')) throw new HttpError(401, '缺少 Bearer Token');
  if (!env.LINE_CHANNEL_ID) throw new HttpError(500, 'LINE_CHANNEL_ID 尚未設定');
  jwks ??= createRemoteJWKSet(new URL('https://api.line.me/oauth2/v2.1/certs'));
  try {
    const { payload } = await jwtVerify(auth.slice(7).trim(), jwks, { issuer: LINE_ISSUER, audience: env.LINE_CHANNEL_ID, algorithms: ['ES256', 'RS256'] });
    return payload.sub;
  } catch (error) {
    throw new HttpError(401, `LINE ID Token 驗證失敗：${error.message}`);
  }
}

export async function currentMember(c) {
  const lineId = await lineUserId(c);
  const member = await c.get('db').first('SELECT * FROM members WHERE line_user_id = ? AND is_active = 1 LIMIT 1', lineId);
  if (!member) throw new HttpError(403, '尚未綁定，請先完成會員/教練綁定');
  return member;
}

export async function requireMemberRole(c, ...roles) {
  const member = await currentMember(c);
  if (!roles.includes(member.role)) throw new HttpError(403, '沒有權限使用此功能');
  return member;
}

export async function currentVenueCoach(c) {
  const lineId = await lineUserId(c);
  const coach = await c.get('db').first('SELECT * FROM venue_rental_coaches WHERE line_user_id = ? AND is_active = 1 LIMIT 1', lineId);
  if (!coach) throw new HttpError(403, '尚未綁定場租教練身分');
  return coach;
}
