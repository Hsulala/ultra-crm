// 靜態檔：public/static ← ../app/static、public/liff ← ../liff（原本 FastAPI 掛載的兩個資料夾，內容以原處為準）
import { cpSync, rmSync, mkdirSync } from 'node:fs';
import { join } from 'node:path';
const root = join(import.meta.dirname, '..');
rmSync(join(root, 'public'), { recursive: true, force: true });
mkdirSync(join(root, 'public'));
cpSync(join(root, '..', 'app', 'static'), join(root, 'public', 'static'), { recursive: true });
cpSync(join(root, '..', 'liff'), join(root, 'public', 'liff'), { recursive: true });
console.log('已複製靜態檔');
