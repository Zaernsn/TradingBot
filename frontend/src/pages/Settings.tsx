import { useEffect, useState } from 'react';

import {

  Shield,

  TrendingUp,

  RotateCcw,

  Key,

  Activity,

  AlertTriangle,

  Play,

  Save,

  TestTube,

} from 'lucide-react';

import { RiskConfig, BacktestResult, BotState } from '../types';

import { settingsApi, marketApi, botApi, portfolioApi } from '../services/api';



function errorMessage(err: any, fallback: string): string {

  const detail = err.response?.data?.detail;

  return typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((item: any) => item.msg).join('; ') : fallback;

}



export default function Settings() {

  const [orders, setOrders] = useState<any[]>([]);

  const [risk, setRisk] = useState<RiskConfig | null>(null);

  const [safety, setSafety] = useState<any>(null);

  const [exchange, setExchange] = useState<{ connected: boolean; masked_key: string } | null>(null);

  const [botState, setBotState] = useState<BotState | null>(null);

  const [krakenKey, setKrakenKey] = useState('');

  const [krakenSecret, setKrakenSecret] = useState('');

  const [message, setMessage] = useState('');

  const [error, setError] = useState('');

  const [backtestSymbol, setBacktestSymbol] = useState('PORTFOLIO');

  const [backtestLoading, setBacktestLoading] = useState(false);

  const [backtestResult, setBacktestResult] = useState<BacktestResult | null>(null);
  const [settingsLoading, setSettingsLoading] = useState(true);
  const [savingRisk, setSavingRisk] = useState(false);

  const applyAggressiveHundredPreset = () => {
    if (!risk) return;
    setRisk({
      ...risk,
      entry_strategy: 'auto',
      buy_probability_threshold: .4,
      max_open_positions: 3,
      max_invest_per_trade_eur: 25,
      max_daily_trades: 15,
      max_position_pct: .30,
      memecoin_max_position_pct: .25,
      max_total_exposure_pct: .75,
      memecoin_max_exposure_pct: .50,
      max_correlated_exposure_pct: .60,
      correlation_threshold: .70,
      stop_loss_pct: .035,
      take_profit_pct: .10,
      max_drawdown_pct: .15,
      memecoins_enabled: true,
      memecoin_max_spread_pct: .005,
      memecoin_min_daily_volume_eur: 75000,
      prediction_horizon: 10,
      risk_per_trade_pct: .03,
      max_holding_hours: 18,
      discovery_limit: 80,
      watchlist_limit: 30,
    });
    setError('');
    setMessage('Autonomous high-risk €100 preset loaded. Review it, then save to apply.');
  };

  const applyBalancedLivePreset = () => {
    if (!risk) return;
    setRisk({
      ...risk,
      entry_strategy: 'momentum',
      buy_probability_threshold: .55,
      max_open_positions: 2,
      max_invest_per_trade_eur: 20,
      max_daily_trades: 4,
      max_position_pct: .20,
      memecoin_max_position_pct: .10,
      max_total_exposure_pct: .40,
      memecoin_max_exposure_pct: .20,
      max_correlated_exposure_pct: .30,
      correlation_threshold: .70,
      stop_loss_pct: .04,
      take_profit_pct: .08,
      max_drawdown_pct: .08,
      memecoins_enabled: false,
      memecoin_max_spread_pct: .002,
      memecoin_min_daily_volume_eur: 250000,
      prediction_horizon: 10,
      risk_per_trade_pct: .01,
      max_holding_hours: 72,
      discovery_limit: 60,
      watchlist_limit: 10,
    });
    setError('');
    setMessage('Balanced live €100 preset loaded. Review and save it, then enable live trading separately.');
  };



  useEffect(() => {

    load();

    const timer = setInterval(() => {

      botApi.getState().then((res) => setBotState(res.data)).catch(() => {});

    }, 30000);

    return () => clearInterval(timer);

  }, []);



  const load = async () => {

    try {

      const [riskRes, safetyRes, exchangeRes, botRes] = await Promise.all([

        settingsApi.getRisk(),

        settingsApi.getSafety(),

        settingsApi.getExchange(),

        botApi.getState(),

      ]);

      setOrders((await portfolioApi.getOrders()).data);

      setRisk(riskRes.data);

      setBotState(botRes.data);

      setSafety(safetyRes.data);

      setExchange(exchangeRes.data);

      setError('');

    } catch (err: any) {

      setError(errorMessage(err, 'Failed to load settings'));

    } finally {

      setSettingsLoading(false);

    }

  };



  const updateRisk = async (e: React.FormEvent) => {

    e.preventDefault();

    if (!risk) return;

    if (savingRisk) return;

    setSavingRisk(true);

    try {

      const saved = await settingsApi.updateRisk({
        entry_strategy: risk.entry_strategy,
        buy_probability_threshold: risk.buy_probability_threshold,

        max_position_pct: risk.max_position_pct,

        stop_loss_pct: risk.stop_loss_pct,

        take_profit_pct: risk.take_profit_pct,

        fee_pct: risk.fee_pct,

        max_daily_trades: risk.max_daily_trades,

        max_open_positions: risk.max_open_positions,
        max_invest_per_trade_eur: risk.max_invest_per_trade_eur,
        risk_per_trade_pct: risk.risk_per_trade_pct,
        discovery_limit: risk.discovery_limit,
        watchlist_limit: risk.watchlist_limit,
        max_holding_hours: risk.max_holding_hours,

        prediction_horizon: risk.prediction_horizon,

        max_drawdown_pct: risk.max_drawdown_pct,

        max_total_exposure_pct: risk.max_total_exposure_pct,

        max_correlated_exposure_pct: risk.max_correlated_exposure_pct,

        correlation_threshold: risk.correlation_threshold,

        slippage_pct: risk.slippage_pct,
        memecoins_enabled: risk.memecoins_enabled,
        memecoin_max_position_pct: risk.memecoin_max_position_pct,
        memecoin_max_exposure_pct: risk.memecoin_max_exposure_pct,
        memecoin_max_spread_pct: risk.memecoin_max_spread_pct,
        memecoin_min_daily_volume_eur: risk.memecoin_min_daily_volume_eur,


      });

      setRisk(saved.data);

      setBotState((await botApi.getState()).data);

      setError('');

      setMessage('Risk settings saved');

    } catch (err: any) {

      setError(errorMessage(err, 'Failed to save settings'));

    } finally {

      setSavingRisk(false);

    }

  };



  const resetPaper = async () => {

    if (!confirm('WARNING: This will reset your paper portfolio to €500 and delete all paper-trading history. Continue?')) return;

    try {

      await settingsApi.resetPaper();

      setMessage('Paper portfolio reset');

    } catch (err: any) {

      setError(errorMessage(err, 'Reset failed'));

    }

  };



  const enableLive = async () => {

    if (!confirm('WARNING: Live trading uses real money and can result in losses. Only proceed if you understand the risks.')) return;

    try {

      await settingsApi.enableLive();

      setMessage('Live trading enabled');

      load();

    } catch (err: any) {

      setError(errorMessage(err, 'Live mode not enabled'));

    }

  };



  const disableLive = async () => {

    try {

      await settingsApi.disableLive();

      setMessage('Switched to paper mode');

      load();

    } catch (err: any) {

      setError(errorMessage(err, 'Failed to disable live mode'));

    }

  };



  const runBacktest = async () => {

    setBacktestLoading(true);

    try {

      const res = await marketApi.backtest(backtestSymbol);

      setBacktestResult(res.data);

      setError('');

    } catch (err: any) {

      setError(errorMessage(err, 'Backtest failed'));

    } finally {

      setBacktestLoading(false);

    }

  };



  const saveKraken = async (e: React.FormEvent) => {

    e.preventDefault();

    try {

      await settingsApi.saveExchange(krakenKey, krakenSecret);

      setKrakenKey('');

      setKrakenSecret('');

      setMessage('Kraken credentials saved');

      load();

    } catch (err: any) {

      setError(errorMessage(err, 'Failed to save credentials'));

    }

  };



  const testKraken = async () => {

    try {

      const res = await settingsApi.testExchange();

      setMessage(res.data.detail);

    } catch (err: any) {

      setError(errorMessage(err, 'Connection test failed'));

    }

  };



  return (

    <div>
      <div className="page-heading settings-heading">
        <div><span className="page-eyebrow">CONTROL CENTER</span><h2 className="section-title">Settings</h2><p className="text-muted">Strategy, account connection and safety controls in one place.</p></div>
      </div>
      <nav className="settings-nav" aria-label="Settings sections">
        <a href="#strategy">Strategy</a><a href="#exchange">Exchange</a><a href="#testing">Testing</a><a href="#safety">Safety</a><a href="#recovery">Recovery</a>
      </nav>



      {message && (

        <div className="card mb-2" style={{ borderColor: 'rgba(16,185,129,0.4)', background: 'var(--success-dim)' }}>

          <div className="flex items-center gap-2 text-success">

            <Activity size={18} />

            {message}

          </div>

        </div>

      )}



      {error && (

        <div className="card mb-2" style={{ borderColor: 'rgba(239,68,68,0.4)', background: 'var(--danger-dim)' }}>

          <div className="flex items-center gap-2 text-danger">

            <AlertTriangle size={18} />

            {error}

          </div>

        </div>

      )}



      <div className="grid grid-12 mb-3">

        {/* Risk Parameters */}

        <div className="card span-8 risk-card" id="strategy">

          <div className="card-header">

            <div className="card-title">

              <Shield className="card-title-icon" size={18} />

              Risk Parameters

            </div>

          </div>

          {settingsLoading ? <div className="table-skeleton table-skeleton-lg" aria-label="Loading risk settings">{[1,2,3,4].map(i => <span key={i} className="skeleton" />)}</div> : risk && (

            <form onSubmit={updateRisk} className="risk-form">
              <fieldset className="preset-group"><legend>Wallet presets</legend>
                <div className="preset-option preset-live">
                  <div className="preset-heading"><div><strong>Balanced live €100 wallet</strong><span>Standard momentum · core markets · 40% maximum exposure</span></div><span className="badge badge-success">Recommended live</span></div>
                  <div className="preset-metrics"><span><strong>2 × €20</strong> positions</span><span><strong>€60</strong> reserve</span><span><strong>4%</strong> stop</span><span><strong>8%</strong> target</span></div>
                  <button className="btn-success" type="button" onClick={applyBalancedLivePreset}><RotateCcw size={16} /> Use balanced live €100 preset</button>
                  <p className="risk-description">Uses standard momentum on the curated core markets, limits trading to four entries per day, and halts new entries at 8% drawdown. The 1% planned-loss budget can reduce an order below €20 when volatility requires it.</p>
                </div>
                <div className="preset-option preset-aggressive">
                  <div className="preset-heading"><div><strong>Autonomous high-risk €100 wallet</strong><span>Automatic strategy research · 75% maximum exposure</span></div><span className="badge badge-warning">High risk</span></div>
                  <div className="preset-metrics"><span><strong>3 × €25</strong> positions</span><span><strong>€25</strong> reserve</span><span><strong>3.5%</strong> stop</span><span><strong>10%</strong> target</span></div>
                  <button className="btn-warning" type="button" onClick={applyAggressiveHundredPreset}><RotateCcw size={16} /> Use autonomous high-risk preset</button>
                  <p className="risk-description">Researches bounded strategies automatically, risks up to 3% of equity per planned stop, allows volatile memecoin entries and halts new entries at 15% drawdown. Gaps can make actual losses larger.</p>
                </div>
                <p className="preset-note">Presets only fill the form. Save the settings, check the Kraken connection, then use Enable Live Trading separately.</p>
              </fieldset>
              <fieldset><legend>Trade sizing</legend><p className="risk-description">Set how much the bot can invest. The smallest applicable limit wins.</p>
                <label>Entry strategy<select value={risk.entry_strategy ?? 'model'} onChange={e => setRisk({...risk, entry_strategy: e.target.value as 'model' | 'momentum' | 'fast_momentum' | 'auto'})}><option value="auto">Automatic — regime-aware strategy selection</option><option value="model">Validated prediction model</option><option value="momentum">Momentum — hourly checks of 24-hour strength</option><option value="fast_momentum">Fast momentum — 3-hour strength, breakout and volume</option></select></label>
                <p className="risk-description">Automatic mode uses completed basket data to remain in cash defensively, use 24-hour momentum in a broad trend, or require fast breakout confirmation during broad acceleration. Momentum modes ignore the model BUY threshold; spread, order minimums and portfolio limits still apply. More entries can mean more losses.</p>
                <div className="risk-fields">
                  <label>Open positions<input type="number" min="1" max="20" step="1" required value={risk.max_open_positions} onChange={e => setRisk({...risk, max_open_positions: Number(e.target.value)})} /><small>Up to 20 at once</small></label>
                  <label>Max investment / trade (€)<input type="number" min="0" step="0.01" required value={risk.max_invest_per_trade_eur} onChange={e => setRisk({...risk, max_invest_per_trade_eur: Number(e.target.value)})} /><small>Includes fee & slippage reserve; 0 = no extra cap</small></label>
                  <label>Max daily trades<input type="number" min="1" step="1" required value={risk.max_daily_trades} onChange={e => setRisk({...risk, max_daily_trades: Number(e.target.value)})} /></label>
                </div>
              </fieldset>
              <fieldset><legend>Memecoin focus</legend>
                <div className="risk-grid">
                  <label>Discovery candidates retained<input type="number" min="30" max="120" step="1" required value={risk.discovery_limit ?? 60} onChange={e => setRisk({...risk, discovery_limit: Number(e.target.value)})} /><small>Markets kept after quote screening. Defaults to 60; does not increase position or exposure limits.</small></label>
                  <label>Watchlist size<input type="number" min="5" max="30" step="1" required value={risk.watchlist_limit ?? 30} onChange={e => setRisk({...risk, watchlist_limit: Number(e.target.value)})} /><small>Eligible candidates are prioritized. Held coins remain monitored outside this limit.</small></label>
                </div>
                <label className="risk-switch"><div><strong>Memecoin radar & entries</strong><small>Automatically discover Kraken meme markets and rank liquidity, spreads and momentum. Up to 30 tracked coins; refresh every 5 minutes. No manual coin list needed. Tracked does not mean eligible to buy; spread and volume limits still gate entries.</small></div><input type="checkbox" role="switch" checked={risk.memecoins_enabled} onChange={e => setRisk({...risk, memecoins_enabled: e.target.checked})} /></label>
                <div className="risk-fields">{([
                  ['memecoin_max_position_pct', 'Per-coin cap', 25], ['memecoin_max_exposure_pct', 'Total meme exposure', 50], ['memecoin_max_spread_pct', 'Maximum spread', 2],
                ] as const).map(([key, label, max]) => <label key={key}>{label} (%)<input type="number" min="0.01" max={max} step="0.01" required value={Number((risk[key] * 100).toFixed(4))} onChange={e => setRisk({...risk, [key]: Number(e.target.value) / 100})} /></label>)}</div>
                <div className="risk-watchlist"><span>Currently tracked</span><div className="risk-pairs">{botState?.watchlist?.length ? botState.watchlist.map(pair => <span key={pair}>{pair}</span>) : <small>The watchlist appears after the bot evaluates markets.</small>}</div></div>
              </fieldset>
              <fieldset><legend>Optional risk sizing and time exit</legend><p className="risk-description">Both start disabled. Evaluate changes in paper mode before relying on them.</p>
                <div className="risk-grid">
                  <label>Planned loss budget / trade (%)<input type="number" min="0" max="5" step="0.01" required value={Number(((risk.risk_per_trade_pct ?? 0) * 100).toFixed(4))} onChange={e => setRisk({...risk, risk_per_trade_pct: Number(e.target.value) / 100})} /><small>0 = disabled. Reduces size for wider stops or higher volatility; losses can exceed this budget.</small></label>
                  <label>Maximum holding time (hours)<input type="number" min="0" max="8760" step="1" required value={risk.max_holding_hours ?? 0} onChange={e => setRisk({...risk, max_holding_hours: Number(e.target.value)})} /><small>0 = disabled. Existing positions are also subject to this exit when enabled.</small></label>
                </div>
              </fieldset>
              <fieldset><legend>Portfolio protection</legend><p className="risk-description">Percentages of portfolio equity. These limits also apply to memecoins.</p>
                <div className="risk-fields">{([
                  ['max_position_pct', 'Position limit'], ['stop_loss_pct', 'Stop loss'], ['take_profit_pct', 'Take profit'], ['max_drawdown_pct', 'Max drawdown'], ['max_total_exposure_pct', 'Total exposure'], ['max_correlated_exposure_pct', 'Correlated exposure'],
                ] as const).map(([key, label]) => <label key={key}>{label} (%)<input type="number" min="0.1" max="100" step="0.1" required value={Number((risk[key] * 100).toFixed(4))} onChange={e => setRisk({...risk, [key]: Number(e.target.value) / 100})} /></label>)}</div>
              </fieldset>
              <details className="risk-advanced"><summary>Execution & model settings</summary><div className="risk-fields">
                <label>Model BUY threshold (%)<input type="number" min="40" max="95" step="0.01" value={(risk.buy_probability_threshold ?? .4)*100} onChange={e => setRisk({...risk,buy_probability_threshold:Number(e.target.value)/100})} /><small>Probability strategy only. Lower values permit more entries, including predictions below 50%; model validation and execution checks still apply.</small></label>
                {([['fee_pct', 'Trading fee', 99], ['slippage_pct', 'Slippage reserve', 5], ['correlation_threshold', 'Correlation threshold', 100]] as const).map(([key, label, max]) => <label key={key}>{label} (%)<input type="number" min="0" max={max} step="0.01" required value={Number((risk[key] * 100).toFixed(4))} onChange={e => setRisk({...risk, [key]: Number(e.target.value) / 100})} /></label>)}
                <p className="risk-description">{risk.verified_taker_fee_pct == null
                  ? 'Kraken taker fee has not yet been verified for this account. Live entries verify it before sizing.'
                  : `Last verified Kraken taker fee: ${(risk.verified_taker_fee_pct * 100).toFixed(3)}%${risk.verified_taker_fee_at ? ` · ${new Date(risk.verified_taker_fee_at).toLocaleString()}` : ''}. Live and research use the highest applicable fee.`}</p>
                <label>Prediction horizon (candles)<input type="number" min="1" max="100" required value={risk.prediction_horizon} onChange={e => setRisk({...risk, prediction_horizon: Number(e.target.value)})} /></label>
                <label>Minimum meme daily volume (€)<input type="number" min="5000" step="1000" required value={risk.memecoin_min_daily_volume_eur} onChange={e => setRisk({...risk, memecoin_min_daily_volume_eur: Number(e.target.value)})} /></label>
              </div></details>
              <div className="risk-save"><span>Changes apply after saving.</span><button className="btn-primary" type="submit" disabled={savingRisk} aria-busy={savingRisk}><Save size={16} />{savingRisk ? 'Saving…' : 'Save risk settings'}</button></div>
            </form>

          )}

        </div>



        {/* Kraken Connection */}

        <div className="card span-4 connection-card" id="exchange">

          <div className="card-header">

            <div className="card-title">

              <Key className="card-title-icon" size={18} />

              Kraken Connection

            </div>

            <span className={`badge ${exchange?.connected ? 'badge-success' : 'badge-warning'}`}>

              {exchange?.connected ? 'Key saved' : 'No account key'}

            </span>

          </div>

          <p className="text-muted" style={{ fontSize: '0.9rem', marginBottom: '1rem' }}>

            Stored key: <span className="mono">{exchange?.masked_key || '****'}</span>

          </p>

          <form onSubmit={saveKraken} className="grid" style={{ gap: '1rem', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>

            <label>

              API Key

              <input type="password" value={krakenKey} onChange={(e) => setKrakenKey(e.target.value)} placeholder="Enter API key" />

            </label>

            <label>

              API Secret

              <input type="password" value={krakenSecret} onChange={(e) => setKrakenSecret(e.target.value)} placeholder="Enter API secret" />

            </label>

            <div style={{ gridColumn: '1 / -1', display: 'flex', gap: '0.75rem' }}>

              <button className="btn-primary" type="submit">

                <Save size={16} />

                Save Credentials

              </button>

              <button className="btn-ghost" type="button" onClick={testKraken} disabled={!exchange?.connected}>

                <TestTube size={16} />

                Test Connection

              </button>

            </div>

          </form>

        </div>



        {/* Backtest */}

        <div className="card span-6" id="testing">

          <div className="card-header">

            <div className="card-title">

              <TrendingUp className="card-title-icon" size={18} />

              Backtest

            </div>

          </div>

          <div className="flex gap-2 mb-2">

            <input value={backtestSymbol} onChange={(e) => setBacktestSymbol(e.target.value)} placeholder="PORTFOLIO or DOGE/EUR" style={{ maxWidth: '160px' }} />

            <button className="btn-primary" onClick={runBacktest} disabled={backtestLoading}>

              <Play size={16} />

              {backtestLoading ? 'Running...' : 'Run Backtest'}

            </button>

          </div>

          {backtestResult && <div>

            <p>Evaluated bars: {backtestResult.evaluated_bars} · Fees: €{backtestResult.total_fees.toFixed(2)} · Net expectancy: €{backtestResult.expectancy.toFixed(2)}</p>

            {Object.entries(backtestResult.benchmarks).map(([name,value]) => <p key={name}>{name.split('_').join(' ')}: {value === null ? 'Unavailable' : (value*100).toFixed(2)+'%'}</p>)}

            {backtestResult.warnings.map(w => <p className="text-muted" key={w}>{w}</p>)}

          </div>}

          {backtestResult && (

            <div className="grid" style={{ gap: '0.75rem', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))' }}>

              <div className="card" style={{ padding: '0.75rem' }}>

                <div className="metric-label">Initial</div>

                <div className="mono" style={{ fontSize: '1.1rem' }}>€{backtestResult.initial_cash.toFixed(2)}</div>

              </div>

              <div className="card" style={{ padding: '0.75rem' }}>

                <div className="metric-label">Final</div>

                <div className="mono" style={{ fontSize: '1.1rem' }}>€{backtestResult.final_equity.toFixed(2)}</div>

              </div>

              <div className="card" style={{ padding: '0.75rem' }}>

                <div className="metric-label">Return</div>

                <div className={`mono ${backtestResult.total_return_pct >= 0 ? 'text-success' : 'text-danger'}`} style={{ fontSize: '1.1rem' }}>

                  {(backtestResult.total_return_pct * 100).toFixed(2)}%

                </div>

              </div>

              <div className="card" style={{ padding: '0.75rem' }}>

                <div className="metric-label">Trades</div>

                <div className="mono" style={{ fontSize: '1.1rem' }}>{backtestResult.num_trades}</div>

              </div>

              <div className="card" style={{ padding: '0.75rem' }}>

                <div className="metric-label">Win Rate</div>

                <div className="mono" style={{ fontSize: '1.1rem' }}>{(backtestResult.win_rate * 100).toFixed(1)}%</div>

              </div>

              <div className="card" style={{ padding: '0.75rem' }}>

                <div className="metric-label">Max DD</div>

                <div className="mono text-danger" style={{ fontSize: '1.1rem' }}>{(backtestResult.max_drawdown_pct * 100).toFixed(2)}%</div>

              </div>

            </div>

          )}

        </div>



        {/* Live Trading Safety */}

        <div className="card span-6" id="safety">

          <div className="card-header">

            <div className="card-title">

              <Activity className="card-title-icon" size={18} />

              Live Trading Safety

            </div>

          </div>

          <div className="grid" style={{ gap: '0.75rem', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', marginBottom: '1rem' }}>

            <div className="card" style={{ padding: '0.75rem' }}>

              <div className="metric-label">Environment</div>

              <div className={`badge ${safety?.enable_live_trading_env ? 'badge-success' : 'badge-warning'}`}>

                {safety?.enable_live_trading_env ? 'Enabled' : 'Disabled'}

              </div>

            </div>

            <div className="card" style={{ padding: '0.75rem' }}>

              <div className="metric-label">Credentials</div>

              <div className={`badge ${safety?.api_credentials_present ? 'badge-success' : 'badge-danger'}`}>

                {safety?.api_credentials_present ? 'Saved' : safety?.credential_status === 'unreadable' ? 'Cannot decrypt' : 'Not saved'}

              </div>

            </div>

          </div>

          <p className="text-muted">{safety?.credential_message}</p>
          <div className="flex gap-2">

            <button className="btn-success" onClick={enableLive} disabled={!safety?.live_possible}>

              <Play size={16} />

              Enable Live Trading

            </button>

            <button className="btn-warning" onClick={disableLive}>

              <RotateCcw size={16} />

              Switch to Paper

            </button>

          </div>

          <p className="text-muted mt-1" style={{ fontSize: '0.82rem' }}>

            Stop the bot before switching. Live activation uses the actual EUR balance in a dedicated Kraken account and preserves your paper history. Emergency stop halts new orders; it does not sell your holdings. Withdrawal permissions are rejected.

          </p>

        </div>

      </div>



      <div className="card mb-3" id="recovery">

        <h3>Live order recovery</h3>

        <p className="text-muted">Uncertain orders block further execution and are queried automatically. Never resend an uncertain order manually. Refresh this page for the latest status.</p>

        {orders.length === 0 ? <p>No live order records in this book.</p> : <div style={{overflowX:'auto'}}><table><thead><tr><th>Pair</th><th>Side</th><th>Status</th><th>Filled</th><th>Client ID / exchange ID</th></tr></thead><tbody>

          {orders.map(o => <tr key={o.id}><td>{o.symbol}</td><td>{o.side}</td><td>{o.status}{o.last_error && <div className="text-danger">{o.last_error}</div>}</td><td>{o.filled_quantity}</td><td className="mono">{o.client_id}<br />{o.exchange_id || 'Awaiting confirmation'}</td></tr>)}

        </tbody></table></div>}

      </div>

      <div className="card mb-3">

        <h3>Drawdown halt</h3>

        <p className="text-muted">A drawdown halt prevents new entries and still permits exits. Stop the bot and review losses before resetting the reference to the current equity.</p>

        <button className="btn-warning" disabled={botState?.is_running} onClick={async () => {

          if (!confirm('Reset the drawdown reference to current equity? This permits new entries after you restart the bot.')) return;

          try { const res = await settingsApi.resumeRisk(); setMessage(res.data.detail); } catch (err) { setError(errorMessage(err, 'Could not reset drawdown halt')); }

        }}>Reset drawdown reference</button>

      </div>

      {/* Paper Portfolio Reset */}

      <div className="card">

        <div className="card-header">

          <div className="card-title">

            <RotateCcw className="card-title-icon" size={18} />

            Paper Portfolio

          </div>

        </div>

        <div className="flex items-center gap-2">

          <button className="btn-danger" onClick={resetPaper}>

            <RotateCcw size={16} />

            Reset to €500

          </button>

          <span className="text-muted" style={{ fontSize: '0.85rem' }}>Deletes all paper-trading history. Cannot be undone.</span>

        </div>

      </div>

    </div>

  );

}
