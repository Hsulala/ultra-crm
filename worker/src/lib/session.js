// 後台登入工作階段：簽章 Cookie（對應原本 Starlette SessionMiddleware：名稱 session、14 天、SameSite=Lax、HttpOnly）。
// 內容只放 admin_user_id 與到期時間；每次請求仍會重新查帳號是否啟用（見 auth.js）。
import { getCookie, setCookie, deleteCookie } from 'hono/cookie';

const NAME = 'session';
const MAX_AGE = 14 * 24 * 3600;
const enc = new TextEncoder();

const b64url = (bytes) => btoa(String.fromCharCode(...new Uint8Array(bytes))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
const fromB64url = (s) => Uint8Array.from(atob(s.replace(/-/g, '+').replace(/_/g, '/')), (ch) => ch.charCodeAt(0));

const keys = new Map();
async function hmacKey(secret) {
  if (!keys.has(secret)) keys.set(secret, crypto.subtle.importKey('raw', enc.encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign', 'verify']));
  return keys.get(secret);
}

export async function readSession(c, secret) {
  const raw = getCookie(c, NAME);
  if (!raw) return {};
  const [payload, signature] = raw.split('.');
  if (!payload || !signature) return {};
  try {
    const ok = await crypto.subtle.verify('HMAC', await hmacKey(secret), fromB64url(signature), enc.encode(payload));
    if (!ok) return {};
    const data = JSON.parse(new TextDecoder().decode(fromB64url(payload)));
    if (!data.exp || data.exp < Date.now()) return {};
    return data.s ?? {};
  } catch {
    return {};
  }
}

export async function writeSession(c, secret, data) {
  const payload = b64url(enc.encode(JSON.stringify({ s: data, exp: Date.now() + MAX_AGE * 1000 })));
  const signature = b64url(await crypto.subtle.sign('HMAC', await hmacKey(secret), enc.encode(payload)));
  setCookie(c, NAME, `${payload}.${signature}`, { path: '/', httpOnly: true, sameSite: 'Lax', maxAge: MAX_AGE, secure: new URL(c.req.url).protocol === 'https:' });
}

export const clearSession = (c) => deleteCookie(c, NAME, { path: '/' });
