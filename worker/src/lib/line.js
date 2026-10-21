// LINE Messaging API（對應 app/services/line_client.py）：沒設 LINE_CHANNEL_ACCESS_TOKEN 時只記錄、直接跳過。
const LINE_API_BASE = 'https://api.line.me/v2/bot';

async function call(env, method, path, body) {
  if (!env.LINE_CHANNEL_ACCESS_TOKEN) {
    console.warn(`LINE_CHANNEL_ACCESS_TOKEN 尚未設定，略過 ${method} ${path}`);
    return;
  }
  const response = await fetch(`${LINE_API_BASE}${path}`, {
    method,
    headers: { authorization: `Bearer ${env.LINE_CHANNEL_ACCESS_TOKEN}`, ...(body ? { 'content-type': 'application/json' } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (response.status !== 200) console.error(`LINE ${method} ${path} 失敗：${await response.text()}`);
}

export const linkRichMenu = (env, userId, menuId) => call(env, 'POST', `/user/${encodeURIComponent(userId)}/richmenu/${encodeURIComponent(menuId)}`);
export const unlinkRichMenu = (env, userId) => call(env, 'DELETE', `/user/${encodeURIComponent(userId)}/richmenu`);
export const pushMessage = (env, userId, text) => call(env, 'POST', '/message/push', { to: userId, messages: [{ type: 'text', text }] });

/** webhook 簽章：HMAC-SHA256(channel secret, body) 的 base64，固定時間比較 */
export async function verifySignature(secret, body, signature) {
  if (!secret || !signature) return false;
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(secret), { name: 'HMAC', hash: 'SHA-256' }, false, ['sign']);
  const mac = new Uint8Array(await crypto.subtle.sign('HMAC', key, body));
  const expected = btoa(String.fromCharCode(...mac));
  const a = new TextEncoder().encode(expected);
  const b = new TextEncoder().encode(signature);
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) diff |= a[i] ^ b[i];
  return diff === 0;
}
