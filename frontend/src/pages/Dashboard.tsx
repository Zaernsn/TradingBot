import { useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Activity, AlertTriangle, ArrowDownRight, ArrowUpRight, Coins, History, Play, Square, Wallet } from 'lucide-react';
import KrakenOverview from '../components/KrakenOverview';
import LiveReadiness from '../components/LiveReadiness';
import EmergencyStopDialog from '../components/EmergencyStopDialog';
import { botApi, portfolioApi } from '../services/api';
import type { BotState, Portfolio, Position, ResearchStatus, Signal, Trade } from '../types';

const euro = (value: number) => value.toLocaleString('de-AT', { style: 'currency', currency: 'EUR', maximumFractionDigits: 2 });
const date = (value: string) => new Date(/(?:Z|[+-]\d{2}:\d{2})$/.test(value) ? value : `${value}Z`).toLocaleString('de-AT', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });

export default function Dashboard() {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [bot, setBot] = useState<BotState | null>(null);
  const [research, setResearch] = useState<ResearchStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const [action, setAction] = useState<'toggle' | 'emergency' | null>(null);
  const [confirmEmergency, setConfirmEmergency] = useState(false);
  const fetching = useRef(false);

  const load = async () => {
    if (fetching.current) return;
    fetching.current = true; setRefreshing(true);
    try {
      const [portfolioRes, positionsRes, tradesRes, signalsRes, botRes, researchRes] = await Promise.all([
        portfolioApi.getPortfolio(), portfolioApi.getPositions(), portfolioApi.getTrades(), portfolioApi.getSignals(), botApi.getState(), botApi.getResearchStatus(),
      ]);
      setPortfolio(portfolioRes.data); setPositions(positionsRes.data); setTrades(tradesRes.data); setSignals(signalsRes.data); setBot(botRes.data); setResearch(researchRes.data); setError('');
    } catch (err: any) { setError(err.response?.data?.detail || 'Could not load the current operating state.'); }
    finally { fetching.current = false; setLoading(false); setRefreshing(false); }
  };

  useEffect(() => { void load(); const interval = setInterval(load, 30000); return () => clearInterval(interval); }, []);

  const toggleBot = async () => {
    setAction('toggle');
    try { if (bot?.is_running) await botApi.stop(); else await botApi.start(); await load(); }
    catch (err: any) { setError(err.response?.data?.detail || 'Bot action failed.'); }
    finally { setAction(null); }
  };
  const emergencyStop = async () => {
    setAction('emergency');
    try { await botApi.emergencyStop(); setConfirmEmergency(false); await load(); }
    catch (err: any) { setError(err.response?.data?.detail || 'Emergency stop failed.'); }
    finally { setAction(null); }
  };

  const pnl = portfolio ? portfolio.equity - portfolio.initial_equity : 0;
  const invested = positions.reduce((sum, position) => sum + position.current_price * position.quantity, 0);
  const activity = useMemo(() => [
    ...trades.slice(0, 8).map(item => ({ time: item.created_at, title: `${item.side === 'BUY' ? 'Bought' : 'Sold'} ${item.symbol}`, detail: `${item.quantity.toLocaleString('de-AT', { maximumFractionDigits: 7 })} at ${euro(item.price)}`, tone: item.side === 'BUY' ? 'success' : 'danger' })),
    ...signals.slice(0, 8).map(item => ({ time: item.created_at, title: `${item.symbol}: ${item.action}`, detail: item.explanation || `${item.model} signal`, tone: item.action === 'BUY' ? 'success' : item.action === 'SELL' ? 'danger' : 'muted' })),
  ].sort((a, b) => new Date(b.time).getTime() - new Date(a.time).getTime()).slice(0, 10), [trades, signals]);

  const protectionCritical = bot?.protection_status && (bot.protection_status.status !== 'HEALTHY' || Object.keys(bot.protection_status.failures || {}).length > 0);
  return <div aria-busy={loading}>
    {refreshing && !loading && <div className="refresh-progress" role="progressbar" aria-label="Refreshing overview" />}
    <div className="page-heading"><div><span className="page-eyebrow">TRADING WORKSPACE</span><h2 className="section-title">Overview</h2><p className="text-muted">Your account, entry readiness, and the next safe action.</p></div><span className={`sync-state ${refreshing ? 'is-syncing' : ''}`}><span className="sync-dot" />{loading ? 'Loading' : refreshing ? 'Refreshing' : 'Updated every 30s'}</span></div>
    {error && <div className="safety-banner is-critical" role="alert"><AlertTriangle size={19} /><div><strong>Current data needs attention</strong><span>{error}</span></div></div>}
    {(bot?.entry_halt?.halted || portfolio?.risk_halted || protectionCritical) && <div className="safety-banner is-critical" role="alert"><AlertTriangle size={19} /><div><strong>New buys are paused</strong><span>{bot?.entry_halt?.reasons?.join('; ') || (portfolio?.risk_halted ? 'Portfolio drawdown protection is active.' : 'Position protection checks are delayed or failing.')} Protective exits remain available while the bot is running. <Link to="/settings#recovery">Review recovery</Link>.</span></div></div>}

    <div className="overview-hero">
      <section className="card operating-card">
        <div className="operating-head"><div><span className="page-eyebrow">CURRENT MODE</span><h3>{portfolio?.mode === 'LIVE' ? 'Live trading' : portfolio?.mode === 'LIVE_DISABLED' ? 'Live unavailable' : 'Paper trading'}</h3></div><span className={`badge ${portfolio?.mode === 'LIVE' ? 'badge-danger' : 'badge-success'}`}>{portfolio?.mode?.replace('_', ' ') || 'Loading'}</span></div>
        <div className="operating-state"><span className={`state-dot ${bot?.is_running ? 'is-running' : ''}`} /><div><strong>{bot?.is_running ? 'Bot running' : 'Bot stopped'}</strong><small>{bot?.is_running ? 'Evaluating entries and protecting positions.' : 'No new entries are being evaluated.'}</small></div></div>
        <div className="operating-actions"><button className={bot?.is_running ? 'btn-warning' : 'btn-success'} onClick={toggleBot} disabled={loading || action !== null}>{bot?.is_running ? <Square size={16} /> : <Play size={16} />}{action === 'toggle' ? 'Working…' : bot?.is_running ? 'Stop bot' : 'Start bot'}</button><button className="btn-danger btn-emergency" onClick={() => setConfirmEmergency(true)} disabled={loading || action !== null}><AlertTriangle size={16} />Emergency stop</button></div>
      </section>
      <section className="overview-metrics">
        <div className="card"><span className="metric-label"><Wallet size={15} /> Equity</span><strong>{portfolio ? euro(portfolio.equity) : '—'}</strong><small className={pnl >= 0 ? 'text-success' : 'text-danger'}>{pnl >= 0 ? '+' : ''}{euro(pnl)} vs {portfolio?.mode === 'LIVE' ? 'net funded' : 'initial'}</small></div>
        <div className="card"><span className="metric-label"><Coins size={15} /> Available cash</span><strong>{portfolio ? euro(portfolio.cash) : '—'}</strong><small>{portfolio && portfolio.equity > 0 ? `${((portfolio.cash / portfolio.equity) * 100).toFixed(0)}% of equity` : '—'}</small></div>
        <div className="card"><span className="metric-label"><Activity size={15} /> Invested</span><strong>{euro(invested)}</strong><small>{positions.length} open {positions.length === 1 ? 'position' : 'positions'}</small></div>
      </section>
    </div>

    <LiveReadiness portfolio={portfolio} bot={bot} research={research} />

    <div className="grid grid-12 dashboard-content">
      <section className="card span-7"><div className="card-header"><div className="card-title">Open positions</div><span className="badge badge-ghost">{positions.length}</span></div>
        {positions.length === 0 ? <div className="empty">No open positions. The bot will only enter when every safety and strategy check passes.</div> : <div className="position-cards">{positions.map(position => <article className="position-card" key={position.id}><div><strong>{position.symbol}</strong><span>Opened {date(position.opened_at)}</span></div><div><span>Value</span><strong>{euro(position.quantity * position.current_price)}</strong></div><div><span>Entry</span><strong>{euro(position.avg_entry_price)}</strong></div><div><span>Unrealized P/L</span><strong className={position.unrealized_pnl >= 0 ? 'text-success' : 'text-danger'}>{position.unrealized_pnl >= 0 ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}{euro(position.unrealized_pnl)}</strong></div></article>)}</div>}
      </section>
      <section className="card span-5"><div className="card-header"><div className="card-title"><History size={18} /> Recent decisions</div><Link to="/markets" className="text-link">View markets</Link></div>
        {activity.length === 0 ? <div className="empty">No decisions or trades yet.</div> : <div className="activity-list">{activity.map((item, index) => <article key={`${item.time}-${index}`}><span className={`activity-dot is-${item.tone}`} /><div><strong>{item.title}</strong><p>{item.detail}</p><time>{date(item.time)}</time></div></article>)}</div>}
      </section>
      <div className="span-12 dashboard-wide"><KrakenOverview /></div>
    </div>
    <EmergencyStopDialog open={confirmEmergency} busy={action === 'emergency'} onCancel={() => setConfirmEmergency(false)} onConfirm={emergencyStop} />
  </div>;
}
