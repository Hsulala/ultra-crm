// 後台頁面：Nunjucks（Jinja2 相容）預先編譯的模板，篩選器對應原本 app/templating.py。
import nunjucks from 'nunjucks';
import { TEMPLATES } from './templates.gen.js';
import { commas, dec2, fmt0, ntd } from './lib/money.js';
import { formatTaipei } from './lib/time.js';
import { pyDumps } from './lib/pyjson.js';
import { ADMIN_ROLE_LABELS, SHIFT_LABELS } from './services/people.js';
import { MOVEMENT_TYPE_LABELS, SHIFT_ORDER } from './services/cash.js';

nunjucks.installJinjaCompat();

// Python 的真假值：None、False、0、''、空清單、空字典都是假
const pyBool = (v) => {
  if (v === null || v === undefined || v === false || v === 0 || v === '') return false;
  if (Array.isArray(v)) return v.length > 0;
  if (v instanceof Map || v instanceof Set) return v.size > 0;
  if (typeof v === 'object' && !(v instanceof nunjucks.runtime.SafeString)) return Object.keys(v).length > 0;
  if (v instanceof nunjucks.runtime.SafeString) return String(v).length > 0;
  return Boolean(v);
};
nunjucks.runtime.pyBool = pyBool;
nunjucks.runtime.pyOr = (a, b) => (pyBool(a) ? a : b());
nunjucks.runtime.pyAnd = (a, b) => (pyBool(a) ? b() : a);

class PrecompiledLoader extends nunjucks.Loader {
  getSource(name) {
    const obj = TEMPLATES[name];
    if (!obj) throw new Error(`找不到模板 ${name}`);
    return { src: { type: 'code', obj }, path: name, noCache: false };
  }
}

const env = new nunjucks.Environment(new PrecompiledLoader(), { autoescape: true });
env.addFilter('ntd', ntd);
env.addFilter('tpe', (value, fmt) => (value == null ? '-' : formatTaipei(value, fmt)));
env.addFilter('fmt0', fmt0);
env.addFilter('commas', commas);
env.addFilter('dec2', dec2);
env.addFilter('hh', (time) => String(time).slice(0, 2));
env.addFilter('pyfloat', (v) => (Number.isInteger(Number(v)) ? `${Number(v)}.0` : String(Number(v))));
env.addFilter('tojson', (v) => new nunjucks.runtime.SafeString(pyDumps(v).replace(/</g, '\\u003c').replace(/>/g, '\\u003e').replace(/&/g, '\\u0026').replace(/'/g, '\\u0027')));
env.addFilter('list', (v) => (Array.isArray(v) ? v : Array.from(v ?? [])));
env.addFilter('abs', (v) => Math.abs(Number(v)));
env.addTest('none', (v) => v === null || v === undefined);
env.addGlobal('ADMIN_ROLE_LABELS', ADMIN_ROLE_LABELS);
env.addGlobal('MOVEMENT_TYPE_LABELS', MOVEMENT_TYPE_LABELS);
env.addGlobal('SHIFT_LABELS', SHIFT_LABELS);
env.addGlobal('SHIFT_ORDER', SHIFT_ORDER);

export function render(c, name, context, status = 200) {
  const html = env.render(name, context);
  return c.html(html, status);
}
