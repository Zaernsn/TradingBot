const assert = require('node:assert/strict');
const path = require('node:path');
const Module = require('node:module');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { buildSync } = require('esbuild');
const source = buildSync({ entryPoints: [path.join(__dirname, 'src/components/StrategyLearning.tsx')],
  bundle: true, platform: 'node', format: 'cjs', jsx: 'automatic', write: false,
  external: ['react', 'react-dom', 'react/jsx-runtime'] }).outputFiles[0].text;
const component = new Module(path.join(__dirname, 'learning-test-render.cjs'), module);
component.filename = path.join(__dirname, 'learning-test-render.cjs');
component.paths = module.paths;
component._compile(source, component.filename);
const render = research => renderToStaticMarkup(React.createElement(component.exports.default, { research }));
assert.match(render(null), /Loading strategy evidence/);
const candidate = { candidate_id: 'sample', family: 'adaptive_momentum', status: 'REJECTED',
  tested_at: '2026-10-11T07:00:00Z', shadow_days: 0, shadow_days_required: 0,
  shadow_closed_trades: 0, shadow_trades_required: 30, failed_checks: ['holdout_beats_cash'],
  holdout: { total_return_pct: -.1 }, stress: { total_return_pct: -.2 } };
const html = render({ counts: { REJECTED: 1 }, candidates: [candidate],
  learning_policy: { enabled: true, maximum_strategy_identities: 125 }, verified_taker_fee_pct: .008 });
for (const expected of ['Automatic learning on', 'No manual approval', 'Did not beat holding cash', '-10.00%', '-20.00%', '0.80%', 'aria-pressed="true"', 'no fixed day wait', 'one position and 5%', 'no minimum days', 'research every five minutes']) {
  assert.ok(html.includes(expected), expected);
}
assert.match(render({ counts: {}, candidates: [], research: { status: 'error', message: '<unsafe>' } }), /&lt;unsafe&gt;/);
const early = render({ counts: { REJECTED: 1 }, candidates: [{ ...candidate,
  holdout: null, stress: null, stopped_stage: 'validation_windows',
  validation_windows: [{ start: '2026-01-01', end: '2026-02-01', passed: false }],
  failed_checks: ['validation_windows_positive'] }] });
assert.match(early, /Stopped early at validation windows; later test stages were skipped/);
assert.match(early, /Validation windows passed: 0\/1 evaluated/);
assert.match(early, /fewer than five closed trades/);
const intraday = render({ counts: { PAPER_APPROVED: 1 }, candidates: [{ ...candidate,
  family: 'intraday_breakout', timeframe: '15m', status: 'PAPER_APPROVED' }] });
assert.match(intraday, /15-minute breakout/);
assert.match(intraday, /15-minute evidence/);
assert.match(intraday, /five families/);
console.log('Strategy lab rendering: loading, evidence, automatic policy and escaped errors passed.');
