// 把 templates/ 底下的 Nunjucks 模板預先編譯成 src/templates.gen.js（Cloudflare 上不能在執行時編譯程式碼）。
// 編譯前調整條件判斷：原本是 Jinja2（Python），空清單、空字典、0、None 都算「假」；
// JavaScript 的空陣列、空物件卻算「真」。所以 if／not／and／or／三元運算一律改用 runtime.pyBool 判斷。
import nunjucks from 'nunjucks';
import { readdirSync, readFileSync, writeFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';

const root = join(import.meta.dirname, '..');
const dir = join(root, 'templates');
const { Compiler } = nunjucks.compiler;
const P = Compiler.prototype;

P.compileIf = function compileIf(node, frame, async) {
  const self = this;
  this._emit('if(runtime.pyBool(');
  this._compileExpression(node.cond, frame);
  this._emitLine(')) {');
  this._withScopedSyntax(() => { self.compile(node.body, frame); if (async) self._emit('cb()'); });
  if (node.else_) {
    this._emitLine('}\nelse {');
    this._withScopedSyntax(() => { self.compile(node.else_, frame); if (async) self._emit('cb()'); });
  } else if (async) {
    this._emitLine('}\nelse {');
    this._emit('cb()');
  }
  this._emitLine('}');
};
P.compileInlineIf = function compileInlineIf(node, frame) {
  this._emit('(runtime.pyBool(');
  this.compile(node.cond, frame);
  this._emit(')?');
  this.compile(node.body, frame);
  this._emit(':');
  if (node.else_ !== null) this.compile(node.else_, frame); else this._emit('""');
  this._emit(')');
};
P.compileNot = function compileNot(node, frame) {
  this._emit('!runtime.pyBool(');
  this.compile(node.target, frame);
  this._emit(')');
};
P.compileOr = function compileOr(node, frame) {
  this._emit('runtime.pyOr(');
  this.compile(node.left, frame);
  this._emit(', function(){ return ');
  this.compile(node.right, frame);
  this._emit('; })');
};
P.compileAnd = function compileAnd(node, frame) {
  this._emit('runtime.pyAnd(');
  this.compile(node.left, frame);
  this._emit(', function(){ return ');
  this.compile(node.right, frame);
  this._emit('; })');
};

function walk(d) {
  return readdirSync(d).flatMap((name) => {
    const p = join(d, name);
    return statSync(p).isDirectory() ? walk(p) : name.endsWith('.html') ? [p] : [];
  });
}

nunjucks.installJinjaCompat();
let out = '// 這個檔案由 scripts/build-templates.mjs 產生，不要手動修改。\n/* eslint-disable */\nexport const TEMPLATES = {\n';
for (const file of walk(dir)) {
  const name = relative(dir, file).split('\\').join('/');
  const code = nunjucks.compiler.compile(readFileSync(file, 'utf8'), [], [], name, {});
  out += `${JSON.stringify(name)}: (function(){ ${code} })(),\n`;
}
out += '};\n';
writeFileSync(join(root, 'src', 'templates.gen.js'), out);
console.log(`已編譯 ${walk(dir).length} 個模板`);
