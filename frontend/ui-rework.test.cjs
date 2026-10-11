const assert = require('node:assert/strict');
const path = require('node:path');
const Module = require('node:module');
const { buildSync } = require('esbuild');

function load(entry) {
  const filename = path.join(__dirname, entry);
  const source = buildSync({ entryPoints: [filename], bundle: true, platform: 'node', format: 'cjs', write: false }).outputFiles[0].text;
  const loaded = new Module(filename, module);
  loaded.filename = filename;
  loaded.paths = module.paths;
  loaded._compile(source, filename);
  return loaded.exports;
}

const risk = load('src/lib/riskPreview.ts');
const status = load('src/lib/statusCopy.ts');
const base = {
  entry_strategy: 'model', buy_probability_threshold: .55, max_open_positions: 20,
  max_invest_per_trade_eur: 0, max_daily_trades: 10, max_position_pct: .05,
  memecoin_max_position_pct: .05, max_total_exposure_pct: .5, memecoin_max_exposure_pct: .1,
  max_correlated_exposure_pct: .3, correlation_threshold: .7, stop_loss_pct: .04,
  take_profit_pct: .08, max_drawdown_pct: .1, memecoins_enabled: true,
  memecoin_max_spread_pct: .003, memecoin_min_daily_volume_eur: 100000,
  prediction_horizon: 10, risk_per_trade_pct: 0, max_holding_hours: 0,
  discovery_limit: 60, watchlist_limit: 30, fee_pct: .0026, slippage_pct: .002,
  daily_loss_pct: 0, weekly_loss_pct: 0, max_realized_slippage_pct: 0,
  max_order_failures: 0, allocation_mode: 'equal', id: 1, updated_at: '',
};

const cautious = risk.applyProfile(base, 'cautious');
assert.equal(cautious.memecoins_enabled, false);
assert.equal(cautious.max_total_exposure_pct, .4);
assert.equal(cautious.max_open_positions, 2);
const preview = risk.riskPreview(cautious, 100, 100);
assert.equal(preview.totalExposure, 40);
assert.equal(preview.effectiveOrder, 20);
assert.equal(preview.plannedLoss, .8);
assert.equal(risk.increasesRisk(cautious, risk.applyProfile(cautious, 'experimental')), true);
assert.equal(status.statusCopy('risk_halt').severity, 'critical');
assert.match(status.statusCopy('waiting_candle').title, /Waiting/);
assert.doesNotMatch(status.statusCopy('risk_halt').title, /_/);
console.log('UI rework helpers: profiles, EUR risk preview, change severity, and status copy passed.');
