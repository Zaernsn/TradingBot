const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const Module = require('node:module');
const ts = require('typescript');
const filename = path.resolve(__dirname, './src/components/TrackedCoins.tsx');
const compiled = ts.transpileModule(fs.readFileSync(filename, 'utf8'), { compilerOptions: { jsx: ts.JsxEmit.ReactJSX, module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } }).outputText;
const loaded = new Module(filename, module);
loaded.filename = filename;
loaded.paths = Module._nodeModulePaths(path.dirname(filename));
loaded._compile(compiled, filename);
const { summarizeCandles } = loaded.exports;
const { entryHint } = loaded.exports;
assert.match(entryHint(false, false), /Bot stopped/);
assert.match(entryHint(true, true), /Already in your portfolio/);
assert.match(entryHint(false, true), /first entry evaluation/);
assert.equal(entryHint(false, true, {message:'Spread too wide', checked_at:new Date(100000).toISOString()}, 110000), 'Spread too wide');
assert.match(entryHint(false, true, {message:'Spread too wide', checked_at:new Date(100000).toISOString()}, 300000), /not current/);
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const html = renderToStaticMarkup(React.createElement(loaded.exports.default, {
  symbols:['BTC/EUR'], quotes:{}, signals:[], positions:[], running:true,
  decisions:{'BTC/EUR':{code:'liquidity',message:'Spread too wide',checked_at:new Date().toISOString()}}
}));
assert.match(html, /Signal \/ entry status/);
assert.match(html, /Spread too wide/);
assert.match(html, /Checked/);
const hour = 3600000;
const now = Date.UTC(2026, 8, 20, 12, 30);
const candles = Array.from({length: 170}, (_, i) => ({ timestamp: new Date(Date.UTC(2026, 8, 20, 12) - (169 - i) * hour).toISOString(), close: 10, volume: 2 }));
const quote = summarizeCandles(12, candles, now);
for (const key of ['hour', 'day', 'week']) assert.ok(Math.abs(quote[key] - 20) < 1e-10);
assert.equal(quote.volume, 480);
assert.equal(summarizeCandles(12, candles.slice(-10), now).week, null);
assert.equal(summarizeCandles(12, candles.filter((_, i) => i !== 160), now).volume, null);
assert.equal(summarizeCandles(12, candles, now + 48 * hour).volume, null);
assert.equal(summarizeCandles(12, [], now).hour, null);
console.log('Tracked coin calculations: passed (time windows, incomplete and stale data).');

