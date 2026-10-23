// Ultra Fitness CRM：Cloudflare Workers 入口（對應原本 app/main.py）。
// 靜態檔（/static、/liff）由 Cloudflare 直接提供；其餘交給這裡。
import { Hono } from 'hono';
import { wrap } from './lib/db.js';
import { HttpError } from './lib/http.js';
import { admin, dashboard } from './routes/admin.js';
import { internal, lineWebhook, liff } from './routes/liff.js';
import { remote } from './routes/remote.js';
import { bootstrapAdmin } from './services/people.js';

const app = new Hono({ strict: true });
let bootstrapped = false;

app.use('*', async (c, next) => {
  if (!c.env.SESSION_SECRET_KEY || c.env.SESSION_SECRET_KEY.length < 32) {
    return c.text('設定有誤：SESSION_SECRET_KEY 至少需要 32 個字元（Worker secret）', 500);
  }
  const db = wrap(c.env.DB);
  c.set('db', db);
  if (!bootstrapped) { await bootstrapAdmin(db, c.env); bootstrapped = true; }
  return next();
});

app.get('/healthz', (c) => c.json({ status: 'ok' }));
// 首頁直接進後台（原本 Railway 版首頁也是 404，正式網址打開就該看到登入頁）
app.get('/', (c) => c.redirect(`${new URL(c.req.url).origin}/admin/`, 302));
// FastAPI 的 redirect_slashes：/admin → /admin/
app.get('/admin', (c) => { const u = new URL(c.req.url); return c.redirect(`${u.origin}/admin/${u.search}`, 307); });
app.get('/admin/', dashboard);
app.route('/admin', admin);
app.route('/api/liff', liff);
app.route('/api/remote', remote);
app.route('/line', lineWebhook);
app.route('/internal', internal);

app.notFound((c) => c.json({ detail: 'Not Found' }, 404));
app.onError((error, c) => {
  if (error instanceof HttpError) {
    return c.json({ detail: error.detail }, error.status, error.headers);
  }
  console.error(error);
  return c.text('Internal Server Error', 500);
});

export default { fetch: app.fetch };
export { app };
