// 金額：原本是 Decimal（NUMERIC(10,2)）。這裡一律換成「分」的整數來加減比較，避免浮點誤差；
// 存進資料庫、回傳 JSON 時再除以 100。

export const toCents = (value) => {
  if (value === null || value === undefined || value === '') return 0;
  const n = typeof value === 'number' ? value : Number(String(value).replace(/,/g, ''));
  if (!Number.isFinite(n)) throw new TypeError('金額格式不正確');
  return Math.round(n * 100);
};
export const fromCents = (cents) => Math.round(cents) / 100;

/** 對應 Decimal 的 quantize(0.01)：任何輸入 → 兩位小數的數字 */
export const money = (value) => fromCents(toCents(value));

/** Decimal 的字串樣子（'1500.00'），只用在原本模板直接印出 Decimal 的地方 */
export const dec2 = (value) => (value === null || value === undefined ? '' : (toCents(value) / 100).toFixed(2));

/** 對應 templating._ntd：整數不帶小數，有零頭才顯示兩位；千分位 */
export function ntd(value) {
  if (value === null || value === undefined) return '-';
  const cents = toCents(value);
  const negative = cents < 0;
  const abs = Math.abs(cents);
  const whole = Math.floor(abs / 100).toLocaleString('en-US');
  const frac = abs % 100;
  return `${negative ? '-' : ''}${whole}${frac ? `.${String(frac).padStart(2, '0')}` : ''}`;
}

/** 對應 Python 的 "{:,.0f}".format(x)：四捨六入五成雙，千分位 */
export function fmt0(value) {
  const n = Number(value ?? 0);
  const floor = Math.floor(n);
  const diff = n - floor;
  let r = diff > 0.5 ? floor + 1 : diff < 0.5 ? floor : (floor % 2 === 0 ? floor : floor + 1);
  if (Object.is(r, -0)) r = 0;
  return r.toLocaleString('en-US');
}

/** 對應 "{:,}".format(int) */
export const commas = (value) => Number(value).toLocaleString('en-US');
