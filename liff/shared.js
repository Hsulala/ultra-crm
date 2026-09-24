// LIFF 頁面共用的認證邏輯：正式環境走真的 LINE LIFF ID Token；
// 本機開發（沒有設定 LIFF_ID 時）改用後端的 dev_mode X-Dev-Line-User-Id 繞過。
// DEV_LINE_USER_ID 由每支頁面自己指定要用哪個測試身分登入。

const LIFF_ID = ""; // 之後拿到真的 LIFF ID 再填進來，其他程式碼不用改

async function getAuthHeaders(devLineUserId) {
  if (LIFF_ID) {
    await liff.init({ liffId: LIFF_ID });
    if (!liff.isLoggedIn()) {
      liff.login();
      return null;
    }
    const idToken = liff.getIDToken();
    return { Authorization: "Bearer " + idToken };
  }
  return { "X-Dev-Line-User-Id": devLineUserId };
}

async function apiFetch(path, devLineUserId, options = {}) {
  const authHeaders = await getAuthHeaders(devLineUserId);
  if (!authHeaders) return null; // 正式環境走到這裡代表正在 liff.login() 跳轉中

  const response = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...authHeaders,
      ...(options.headers || {}),
    },
  });

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `請求失敗（${response.status}）`);
  }
  return response.json();
}
