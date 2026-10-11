import { useEffect, useMemo, useState } from 'react';
import { AlertTriangle, Check, ChevronRight, Key, RotateCcw, Save, Shield, TestTube, X } from 'lucide-react';
import { botApi, portfolioApi, settingsApi } from '../services/api';
import type { BotState, Portfolio, RiskConfig } from '../types';
import { applyProfile, changedRiskFields, increasesRisk, PROFILE_LABELS, riskPreview, type RiskProfile } from '../lib/riskPreview';

type Safety = { enable_live_trading_env: boolean; api_credentials_present: boolean; credential_status: string; credential_message: string; live_possible: boolean; message: string };
type Exchange = { connected: boolean; masked_key: string };

const euro = (value: number) => Number.isFinite(value) ? value.toLocaleString('de-AT', { style: 'currency', currency: 'EUR', maximumFractionDigits: 2 }) : 'No extra cap';
const errorMessage = (error: any, fallback: string) => {
  const detail = error.response?.data?.detail;
  return typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((item: any) => item.msg).join('; ') : fallback;
};

export default function Settings() {
  const [risk, setRisk] = useState<RiskConfig | null>(null);
  const [savedRisk, setSavedRisk] = useState<RiskConfig | null>(null);
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [bot, setBot] = useState<BotState | null>(null);
  const [safety, setSafety] = useState<Safety | null>(null);
  const [exchange, setExchange] = useState<Exchange | null>(null);
  const [orders, setOrders] = useState<any[]>([]);
  const [krakenKey, setKrakenKey] = useState('');
  const [krakenSecret, setKrakenSecret] = useState('');
  const [lastConnectionTest, setLastConnectionTest] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [reviewOpen, setReviewOpen] = useState(false);
  const [liveOpen, setLiveOpen] = useState(false);

  const load = async () => {
    try {
      const [riskRes, portfolioRes, botRes, safetyRes, exchangeRes, ordersRes] = await Promise.all([
        settingsApi.getRisk(), portfolioApi.getPortfolio(), botApi.getState(), settingsApi.getSafety(), settingsApi.getExchange(), portfolioApi.getOrders(),
      ]);
      setRisk(riskRes.data); setSavedRisk(riskRes.data); setPortfolio(portfolioRes.data); setBot(botRes.data); setSafety(safetyRes.data); setExchange(exchangeRes.data); setOrders(ordersRes.data); setError('');
    } catch (err: any) { setError(errorMessage(err, 'Failed to load settings.')); }
    finally { setLoading(false); }
  };
  useEffect(() => { void load(); }, []);

  const changes = useMemo(() => risk && savedRisk ? changedRiskFields(savedRisk, risk) : [], [risk, savedRisk]);
  const riskRaised = useMemo(() => risk && savedRisk ? increasesRisk(savedRisk, risk) : false, [risk, savedRisk]);
  const preview = risk && portfolio ? riskPreview(risk, portfolio.equity, portfolio.cash) : null;

  const selectProfile = (profile: RiskProfile) => {
    if (!risk) return;
    if (profile === 'paper') {
      setMessage('Paper learning selected. Use “Switch to Paper” below if Live is active; your saved risk limits stay unchanged.');
      document.getElementById('kraken')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      return;
    }
    setRisk(applyProfile(risk, profile)); setMessage(`${PROFILE_LABELS[profile].title} loaded as a draft. Review the EUR impact before saving.`); setError('');
    document.getElementById('risk-impact')?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  };

  const persistRisk = async () => {
    if (!risk || saving) return;
    setSaving(true);
    try {
      const { id: _id, updated_at: _updated, verified_taker_fee_pct: _fee, verified_taker_fee_at: _feeAt, trading_pair: _pair, ...payload } = risk;
      const response = await settingsApi.updateRisk(payload);
      setRisk(response.data); setSavedRisk(response.data); setBot((await botApi.getState()).data); setReviewOpen(false); setMessage('Settings saved. Live mode and bot state were not changed.'); setError('');
    } catch (err: any) { setError(errorMessage(err, 'Failed to save settings.')); }
    finally { setSaving(false); }
  };

  const saveCredentials = async (event: React.FormEvent) => {
    event.preventDefault();
    try { await settingsApi.saveExchange(krakenKey, krakenSecret); setKrakenKey(''); setKrakenSecret(''); setMessage('Kraken credentials saved. Test the connection next.'); await load(); }
    catch (err: any) { setError(errorMessage(err, 'Failed to save credentials.')); }
  };
  const testConnection = async () => {
    try { const response = await settingsApi.testExchange(); setLastConnectionTest(new Date().toISOString()); setMessage(response.data.detail); setError(''); }
    catch (err: any) { setError(errorMessage(err, 'Connection test failed.')); }
  };
  const enableLive = async () => {
    try { const response = await settingsApi.enableLive(); setLiveOpen(false); setMessage(response.data.detail); await load(); }
    catch (err: any) { setError(errorMessage(err, 'Live mode was not enabled.')); }
  };
  const disableLive = async () => {
    try { const response = await settingsApi.disableLive(); setMessage(response.data.detail); await load(); }
    catch (err: any) { setError(errorMessage(err, 'Failed to switch to Paper.')); }
  };

  const percentField = (key: keyof RiskConfig, label: string, hint: string, max = 100) => risk && <label>{label}<span className="setting-hint">{hint}{portfolio ? ` Current preview: ${euro(portfolio.equity * Number(risk[key]))}.` : ''}</span><div className="input-suffix"><input type="number" min="0" max={max} step="0.1" value={Number((Number(risk[key]) * 100).toFixed(4))} onChange={event => setRisk({ ...risk, [key]: Number(event.target.value) / 100 })} /><span>%</span></div></label>;

  return <div aria-busy={loading}>
    <div className="page-heading settings-heading"><div><span className="page-eyebrow">CONTROL CENTER</span><h2 className="section-title">Settings</h2><p className="text-muted">Choose a safe starting point, understand its EUR impact, then configure advanced limits only when needed.</p></div></div>
    <nav className="settings-nav" aria-label="Settings sections"><a href="#guided">Guided setup</a><a href="#strategy">Strategy</a><a href="#risk">Risk & exits</a><a href="#kraken">Kraken & Live</a><a href="#recovery">Safety & recovery</a></nav>
    {message && <div className="safety-banner is-success" role="status"><Check size={18} /><span>{message}</span></div>}
    {error && <div className="safety-banner is-critical" role="alert"><AlertTriangle size={18} /><span>{error}</span></div>}

    <section className="settings-section" id="guided">
      <div className="section-intro"><span className="section-number">1</span><div><h3>Choose how you want to use the bot</h3><p>Profiles fill the form only. They never enable Live or start the bot.</p></div></div>
      <div className="profile-grid">{(Object.keys(PROFILE_LABELS) as RiskProfile[]).map(profile => { const copy = PROFILE_LABELS[profile]; return <article className={`profile-card is-${profile}`} key={profile}><div><span className="profile-risk">{copy.risk}</span><h4>{copy.title}</h4><p>{copy.description}</p></div><ul>{profile === 'paper' ? <><li>Use current limits with simulated funds</li><li>Best first step after any strategy change</li><li>No real Kraken orders after switching to Paper</li></> : profile === 'cautious' ? <><li>Two positions, up to 20% each</li><li>40% maximum total exposure</li><li>Core markets; memecoins off</li></> : <><li>Three positions and broader discovery</li><li>75% maximum total exposure</li><li>Automatic research; profitability unproven</li></>}</ul><button className={profile === 'cautious' ? 'btn-success' : profile === 'experimental' ? 'btn-warning' : 'btn-primary'} onClick={() => selectProfile(profile)}>{profile === 'paper' ? 'Go to Paper controls' : 'Use as draft'} <ChevronRight size={16} /></button></article>; })}</div>
      <p className="settings-disclaimer">A “cautious” profile reduces configured exposure; it does not make trading safe or profitable. Historical profitability has not been established.</p>
    </section>

    {risk && preview && <section className="card impact-card" id="risk-impact">
      <div className="card-header"><div><span className="page-eyebrow">LIVE PREVIEW</span><h3>What these limits mean for {euro(portfolio?.equity || 0)}</h3></div><span className="badge badge-ghost">Estimate</span></div>
      <div className="impact-summary"><div><span>Effective order ceiling</span><strong>{euro(preview.effectiveOrder)}</strong><small>The smallest current ceiling wins</small></div><div><span>Total exposure ceiling</span><strong>{euro(preview.totalExposure)}</strong><small>{(risk.max_total_exposure_pct * 100).toFixed(0)}% of equity</small></div><div><span>Cash reserve</span><strong>{euro(preview.reserve)}</strong><small>Before fees and market movement</small></div><div><span>Loss at configured stop</span><strong>≈ {euro(preview.plannedLoss)}</strong><small>Not guaranteed; gaps and costs can increase loss</small></div></div>
      <div className="limit-list"><div><span>Configured trade cap</span><strong>{risk.max_invest_per_trade_eur > 0 ? euro(preview.configuredTradeCap) : 'No extra cap'}</strong></div><div><span>Position exposure cap</span><strong>{euro(preview.byPosition)}</strong></div><div><span>Total exposure available to this estimate</span><strong>{euro(preview.totalExposure)}</strong></div><div><span>Cash after fee/slippage reserve</span><strong>{euro(preview.cashAfterReserve)}</strong></div><div className="is-effective"><span>Estimated effective ceiling</span><strong>{euro(preview.effectiveOrder)}</strong></div></div>
      <p className="text-muted">This preview does not include every live condition, current holdings, canary limits, or Kraken’s order minimum. The backend remains authoritative.</p>
    </section>}

    {risk && <>
      <section className="settings-section" id="strategy"><div className="section-intro"><span className="section-number">2</span><div><h3>Strategy & markets</h3><p>Control how signals are selected and which markets may enter the watchlist.</p></div></div>
        <div className="card settings-form-grid"><label>Entry strategy<span className="setting-hint">Automatic may remain in cash when no locally validated candidate qualifies.</span><select value={risk.entry_strategy} onChange={event => setRisk({ ...risk, entry_strategy: event.target.value as RiskConfig['entry_strategy'] })}><option value="momentum">Momentum — completed 24-hour strength</option><option value="fast_momentum">Fast momentum — breakout and volume</option><option value="model">Validated prediction model</option><option value="auto">Automatic — regime-aware research</option></select></label>
          <label>Watchlist size<span className="setting-hint">Held coins remain monitored outside this limit.</span><input type="number" min="5" max="30" value={risk.watchlist_limit} onChange={event => setRisk({ ...risk, watchlist_limit: Number(event.target.value) })} /></label>
          <label>Discovery candidates<span className="setting-hint">Markets retained after initial quote screening.</span><input type="number" min="30" max="120" value={risk.discovery_limit} onChange={event => setRisk({ ...risk, discovery_limit: Number(event.target.value) })} /></label>
          <label className="risk-switch settings-wide"><div><strong>Memecoin radar and entries</strong><small>Enables broader, more volatile market discovery. Spread, volume, exposure, and order checks still apply.</small></div><input type="checkbox" role="switch" checked={risk.memecoins_enabled} onChange={event => setRisk({ ...risk, memecoins_enabled: event.target.checked })} /></label>
          {risk.memecoins_enabled && <><label>Minimum meme daily volume<span className="setting-hint">Higher values require deeper markets.</span><input type="number" min="5000" step="1000" value={risk.memecoin_min_daily_volume_eur} onChange={event => setRisk({ ...risk, memecoin_min_daily_volume_eur: Number(event.target.value) })} /></label>{percentField('memecoin_max_spread_pct', 'Maximum meme spread', 'Entries wait when the live spread is wider.', 2)}{percentField('memecoin_max_position_pct', 'Maximum per memecoin', 'Caps one memecoin position.', 25)}{percentField('memecoin_max_exposure_pct', 'Maximum total meme exposure', 'Caps all memecoin positions together.', 50)}</>}
        </div>
      </section>

      <section className="settings-section" id="risk"><div className="section-intro"><span className="section-number">3</span><div><h3>Risk & exits</h3><p>Every percentage includes an estimated EUR value. The smallest applicable ceiling wins.</p></div></div>
        <div className="card settings-form-grid"><label>Maximum open positions<span className="setting-hint">An upper bound, not a target.</span><input type="number" min="1" max="20" value={risk.max_open_positions} onChange={event => setRisk({ ...risk, max_open_positions: Number(event.target.value) })} /></label><label>Maximum investment per trade<span className="setting-hint">Includes the fee/slippage reserve; zero disables this extra cap.</span><div className="input-suffix"><input type="number" min="0" step="0.01" value={risk.max_invest_per_trade_eur} onChange={event => setRisk({ ...risk, max_invest_per_trade_eur: Number(event.target.value) })} /><span>€</span></div></label><label>Maximum daily trades<span className="setting-hint">Limits entry frequency, not protective exits.</span><input type="number" min="1" max="100" value={risk.max_daily_trades} onChange={event => setRisk({ ...risk, max_daily_trades: Number(event.target.value) })} /></label>
          {percentField('max_position_pct', 'Maximum per position', 'Caps one position as a share of equity.')}{percentField('max_total_exposure_pct', 'Maximum invested at once', 'Caps all open positions combined.')}{percentField('max_correlated_exposure_pct', 'Maximum correlated exposure', 'Limits positions that may move together.')}{percentField('stop_loss_pct', 'Stop loss', 'A trigger, not a guaranteed fill price.')}{percentField('take_profit_pct', 'Take-profit target', 'A fixed target for the current exit policy.')}{percentField('max_drawdown_pct', 'Drawdown halt', 'Pauses new buys after the portfolio falls from its peak.')}
          <label>Planned loss budget per trade<span className="setting-hint">Zero disables volatility-aware risk sizing. Actual losses can exceed it.</span><div className="input-suffix"><input type="number" min="0" max="5" step="0.01" value={(risk.risk_per_trade_pct * 100).toFixed(2)} onChange={event => setRisk({ ...risk, risk_per_trade_pct: Number(event.target.value) / 100 })} /><span>%</span></div></label><label>Maximum holding time<span className="setting-hint">Zero disables the time exit; existing positions are affected when enabled.</span><div className="input-suffix"><input type="number" min="0" max="8760" value={risk.max_holding_hours} onChange={event => setRisk({ ...risk, max_holding_hours: Number(event.target.value) })} /><span>h</span></div></label>
          <details className="settings-advanced settings-wide"><summary>Advanced loss, execution, and model controls</summary><div className="settings-form-grid nested">{percentField('daily_loss_pct', 'Rolling 24-hour loss halt', 'Zero disables this entry halt.')}{percentField('weekly_loss_pct', 'Rolling seven-day loss halt', 'Zero disables this entry halt.')}{percentField('max_realized_slippage_pct', 'Adverse realized slippage halt', 'Zero disables this entry halt.', 10)}<label>Failed-order halt<span className="setting-hint">Consecutive failed orders in the last 24 hours; zero disables.</span><input type="number" min="0" max="20" value={risk.max_order_failures} onChange={event => setRisk({ ...risk, max_order_failures: Number(event.target.value) })} /></label>{percentField('fee_pct', 'Trading fee', 'Live sizing uses the highest applicable verified fee.')}{percentField('slippage_pct', 'Slippage reserve', 'Cash held back for adverse price movement.', 5)}{percentField('correlation_threshold', 'Correlation threshold', 'Defines which positions count as correlated.')}<label>Model BUY threshold<span className="setting-hint">Only used by the prediction-model strategy.</span><div className="input-suffix"><input type="number" min="40" max="95" step="0.01" value={(risk.buy_probability_threshold * 100).toFixed(2)} onChange={event => setRisk({ ...risk, buy_probability_threshold: Number(event.target.value) / 100 })} /><span>%</span></div></label><label>Prediction horizon<span className="setting-hint">Number of completed candles used by the model target.</span><input type="number" min="1" max="100" value={risk.prediction_horizon} onChange={event => setRisk({ ...risk, prediction_horizon: Number(event.target.value) })} /></label></div></details>
        </div>
      </section>
    </>}

    <section className="settings-section" id="kraken"><div className="section-intro"><span className="section-number">4</span><div><h3>Kraken & Live</h3><p>Connection, preflight, Live activation, and bot start remain separate actions.</p></div></div>
      <div className="grid grid-12"><div className="card span-6"><div className="card-header"><div className="card-title"><Key size={18} /> Kraken connection</div><span className={`badge ${exchange?.connected ? 'badge-success' : 'badge-warning'}`}>{exchange?.connected ? 'Key saved' : 'Not connected'}</span></div><p className="text-muted">Use a dedicated API key without withdrawal permission. Stored key: <span className="mono">{exchange?.masked_key || '****'}</span></p><form className="settings-form-grid" onSubmit={saveCredentials}><label>API key<input type="password" autoComplete="off" value={krakenKey} onChange={event => setKrakenKey(event.target.value)} placeholder="Enter API key" /></label><label>API secret<input type="password" autoComplete="off" value={krakenSecret} onChange={event => setKrakenSecret(event.target.value)} placeholder="Enter API secret" /></label><div className="settings-wide button-row"><button className="btn-primary" type="submit" disabled={!krakenKey || !krakenSecret}><Save size={16} />Save credentials</button><button className="btn-ghost" type="button" onClick={testConnection} disabled={!exchange?.connected}><TestTube size={16} />Test connection</button></div></form>{lastConnectionTest && <p className="connection-tested"><Check size={15} /> Tested successfully {new Date(lastConnectionTest).toLocaleString('de-AT')}</p>}</div>
        <div className="card span-6"><div className="card-header"><div className="card-title"><Shield size={18} /> Live activation</div><span className={`badge ${portfolio?.mode === 'LIVE' ? 'badge-danger' : 'badge-ghost'}`}>{portfolio?.mode === 'LIVE' ? 'LIVE' : 'PAPER'}</span></div><div className="activation-list"><div className={safety?.enable_live_trading_env ? 'is-complete' : ''}><Check size={16} /><span>Server permits Live</span></div><div className={safety?.api_credentials_present ? 'is-complete' : ''}><Check size={16} /><span>Credentials saved</span></div><div className={lastConnectionTest ? 'is-complete' : ''}><Check size={16} /><span>Connection tested this session</span></div><div className={changes.length === 0 ? 'is-complete' : ''}><Check size={16} /><span>Settings saved</span></div></div><p className="text-muted">{safety?.credential_message}</p><div className="button-row"><button className="btn-success" onClick={() => setLiveOpen(true)} disabled={!safety?.live_possible || changes.length > 0 || portfolio?.mode === 'LIVE'}>Review and enable Live</button><button className="btn-warning" onClick={disableLive} disabled={portfolio?.mode !== 'LIVE'}><RotateCcw size={16} />Switch to Paper</button></div><p className="setting-hint">Enabling Live does not start the bot. Emergency stop does not sell holdings.</p></div></div>
    </section>

    <section className="settings-section" id="recovery"><div className="section-intro"><span className="section-number">5</span><div><h3>Safety & recovery</h3><p>Advanced recovery actions stay separate from routine configuration.</p></div></div>
      <div className="card recovery-card"><h4>Live order incidents</h4><p className="text-muted">Uncertain orders block further execution and are reconciled automatically. Never resend an uncertain order manually.</p>{orders.length === 0 ? <div className="empty">No live order records in this book.</div> : <div className="recovery-list">{orders.map(order => <details key={order.id}><summary><span><strong>{order.symbol} · {order.side}</strong><small>{order.status}{order.last_error ? ` · ${order.last_error}` : ''}</small></span><span className={`badge ${['UNKNOWN', 'FAILED'].includes(order.status) ? 'badge-danger' : 'badge-ghost'}`}>{order.status}</span></summary><div><p>Filled: {order.filled_quantity}</p><p className="mono">Client ID: {order.client_id}<br />Exchange ID: {order.exchange_id || 'Awaiting confirmation'}</p></div></details>)}</div>}</div>
      <details className="card dangerous-actions"><summary>Recovery and destructive actions</summary><div className="dangerous-grid"><article><h4>Reset drawdown reference</h4><p>Stops blocking new entries from the existing drawdown reference. The bot must be stopped.</p><button className="btn-warning" disabled={bot?.is_running} onClick={async () => { if (!confirm('Reset the drawdown reference to current equity? The bot remains stopped.')) return; try { setMessage((await settingsApi.resumeRisk()).data.detail); } catch (err) { setError(errorMessage(err, 'Could not reset drawdown reference.')); } }}>Reset drawdown reference</button></article><article><h4>Reset entry guards</h4><p>Resets rolling-loss baselines after review. The drawdown halt is unchanged.</p><button className="btn-warning" disabled={bot?.is_running} onClick={async () => { if (!confirm('Reset entry-guard baselines after reviewing the cause?')) return; try { setMessage((await settingsApi.resumeEntryGuards()).data.detail); await load(); } catch (err) { setError(errorMessage(err, 'Could not reset entry guards.')); } }}>Reset entry guards</button></article><article><h4>Delete Paper history</h4><p>Resets the Paper portfolio to €500 and permanently deletes its trading history.</p><button className="btn-danger" onClick={async () => { if (!confirm('Delete all Paper trading history and reset to €500? This cannot be undone.')) return; try { setMessage((await settingsApi.resetPaper()).data.detail); await load(); } catch (err) { setError(errorMessage(err, 'Paper reset failed.')); } }}><RotateCcw size={16} />Reset Paper portfolio</button></article></div></details>
    </section>

    {changes.length > 0 && <div className="unsaved-bar" role="status"><div><strong>{changes.length} unsaved {changes.length === 1 ? 'change' : 'changes'}</strong><span className={riskRaised ? 'text-warning' : 'text-success'}>{riskRaised ? 'Risk or exposure increased' : 'No configured risk increase detected'}</span></div><div><button className="btn-ghost" onClick={() => savedRisk && setRisk(savedRisk)}>Discard</button><button className={riskRaised ? 'btn-warning' : 'btn-primary'} onClick={() => setReviewOpen(true)}>Review changes</button></div></div>}

    {reviewOpen && risk && savedRisk && <div className="dialog-backdrop"><div className="dialog-card settings-dialog" role="dialog" aria-modal="true" aria-labelledby="review-title"><button className="dialog-close" onClick={() => setReviewOpen(false)}><X size={18} /></button><span className="page-eyebrow">BEFORE YOU SAVE</span><h2 id="review-title">Review {changes.length} settings changes</h2><p>{riskRaised ? 'One or more changes increase configured exposure, frequency, or tolerated loss.' : 'These changes do not increase the risk fields tracked by the preview.'}</p><div className="change-list">{changes.map(key => <div key={String(key)}><span>{String(key).replace(/_/g, ' ')}</span><strong>{String(savedRisk[key])} → {String(risk[key])}</strong></div>)}</div><p className="text-muted">Saving does not enable Live or start the bot.</p><div className="dialog-actions"><button className="btn-ghost" onClick={() => setReviewOpen(false)}>Keep editing</button><button className={riskRaised ? 'btn-warning' : 'btn-primary'} onClick={persistRisk} disabled={saving}>{saving ? 'Saving…' : riskRaised ? 'Confirm risk change' : 'Save settings'}</button></div></div></div>}
    {liveOpen && risk && preview && <div className="dialog-backdrop"><div className="dialog-card settings-dialog" role="alertdialog" aria-modal="true" aria-labelledby="live-title"><button className="dialog-close" onClick={() => setLiveOpen(false)}><X size={18} /></button><span className="dialog-danger-icon"><AlertTriangle size={24} /></span><h2 id="live-title">Enable real-money trading?</h2><p>Current equity: <strong>{euro(portfolio?.equity || 0)}</strong>. Estimated order ceiling: <strong>{euro(preview.effectiveOrder)}</strong>. Total exposure ceiling: <strong>{euro(preview.totalExposure)}</strong>.</p><ul><li>Profitability has not been established.</li><li>Losses can exceed stop estimates because of gaps, slippage, and fees.</li><li>The API key must not have withdrawal permission.</li><li>The bot remains stopped until you start it separately.</li></ul><div className="dialog-actions"><button className="btn-ghost" onClick={() => setLiveOpen(false)}>Cancel</button><button className="btn-danger" onClick={enableLive}>I understand — enable Live</button></div></div></div>}
  </div>;
}
