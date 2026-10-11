const assert = require('node:assert/strict');
const path = require('node:path');
const Module = require('node:module');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { buildSync } = require('esbuild');
const source = buildSync({ entryPoints: [path.join(__dirname, 'src/components/ExecutionCosts.tsx')],
  bundle: true, platform: 'node', format: 'cjs', jsx: 'automatic', write: false,
  external: ['react', 'react-dom', 'react/jsx-runtime'] }).outputFiles[0].text;
const component = new Module(path.join(__dirname, 'cost-test-render.cjs'), module);
component.filename = path.join(__dirname, 'cost-test-render.cjs'); component.paths = module.paths;
component._compile(source, component.filename);
const render = props => renderToStaticMarkup(React.createElement(component.exports.default, props));
assert.match(render({ report: null }), /Loading cost evidence/);
assert.match(render({ report: null, error: '<unavailable>' }), /&lt;unavailable&gt;/);
const empty = { public_markets: { observations: 0, median_valid_spread_pct: null, latest: {} },
  live_execution: { filled_orders: 0, fresh_quote_matched_orders: 0, quote_fee_eur: null, adverse_vs_touch_eur: null } };
assert.match(render({ report: empty }), /No market observations yet/);
assert.match(render({ report: empty }), /Unavailable/);
const html = render({ report: { ...empty, public_markets: { observations: 1, median_valid_spread_pct: .002,
  latest: { 'BTC/EUR': { status: 'STALE', received_at: '2026-10-11T12:00:00Z', age_seconds: 120,
    spread_pct: .002, bid_depth_eur: 100, ask_depth_eur: 200 } } } } });
for (const text of ['0.200%', '€100.00', '2 min', 'stale', 'Paper fills are excluded', '20 price levels']) {
  assert.ok(html.includes(text), text);
}
console.log('Execution cost evidence: missing data, sample age, liquidity and escaped errors passed.');
