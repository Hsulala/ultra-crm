// 對應 Python json.dumps 的預設輸出（', ' 與 ': ' 分隔、非 ASCII 字元轉成 \uXXXX），
// 讓頁面裡內嵌的 JSON 跟原本完全一樣。瀏覽器解析結果與 JSON.stringify 相同。
export function pyDumps(value) {
  if (value === null || value === undefined) return 'null';
  if (value instanceof PyFloat) return value.v === null ? 'null' : pyFloat(value.v);
  if (value === true) return 'true';
  if (value === false) return 'false';
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return 'NaN';
    return Number.isInteger(value) && !Object.is(value, -0) ? String(value) : pyFloat(value);
  }
  if (typeof value === 'string') return JSON.stringify(value).replace(/[\u007f-￿]/g, (ch) => `\\u${ch.charCodeAt(0).toString(16).padStart(4, '0')}`);
  if (Array.isArray(value)) return `[${value.map(pyDumps).join(', ')}]`;
  return `{${Object.entries(value).filter(([, v]) => v !== undefined).map(([k, v]) => `${pyDumps(String(k))}: ${pyDumps(v)}`).join(', ')}}`;
}

// 浮點數：Python repr（1500.0、0.1）
export const pyFloat = (n) => (Number.isInteger(n) ? `${n}.0` : String(n));

/** 標記成「Python 浮點數」：在 pyDumps 裡輸出 1500.0 而不是 1500 */
export class PyFloat { constructor(v) { this.v = v; } }
