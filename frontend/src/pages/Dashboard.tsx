import KrakenOverview from '../components/KrakenOverview';
import TrackedCoins, { CoinQuote, summarizeCandles } from '../components/TrackedCoins';
import { useEffect, useRef, useState } from 'react';
import {
  TrendingUp,
  TrendingDown,
  Wallet,
  Coins,
  Activity,
  Play,
  Square,
  AlertTriangle,
  BarChart3,
  Signal as SignalIcon,
  List,
  History,
  ArrowUpRight,
  ArrowDownRight,
} from 'lucide-react';
import {
  Portfolio,
  Position,
  Trade,
  Signal,
  BotState,
  ResearchStatus,
} from '../types';
import {
  portfolioApi,
  marketApi,
  botApi,
} from '../services/api';

export default function Dashboard() {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [botState, setBotState] = useState<BotState | null>(null);
  const [research, setResearch] = useState<ResearchStatus | null>(null);
  const [quotes, setQuotes] = useState<Record<string, CoinQuote>>({});
  const [error, setError] = useState('');
  const [now, setNow] = useState(Date.now());
  const [initialLoading, setInitialLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [botAction, setBotAction] = useState<'toggle' | 'emergency' | null>(null);

  const fetching = useRef(false);
  const fetchAll = async () => {
    if (fetching.current) return;
    fetching.current = true;
    setRefreshing(true);
    try {
      const [pRes, posRes, tRes, sRes, bRes, rRes] = await Promise.all([
        portfolioApi.getPortfolio(),
        portfolioApi.getPositions(),
        portfolioApi.getTrades(),
        portfolioApi.getSignals(),
        botApi.getState(),
        botApi.getResearchStatus(),
      ]);
      setPortfolio(pRes.data);
      setPositions(posRes.data);
      setTrades(tRes.data);
      setSignals(sRes.data);
      setBotState(bRes.data);
      setResearch(rRes.data);
      // Reveal the useful dashboard immediately; quote enrichment can continue in place.
      setInitialLoading(false);
      const watchlist: string[] = [...new Set<string>([...(bRes.data.watchlist || []), ...posRes.data.map((p: Position) => p.symbol)])];
      const fresh: Record<string, CoinQuote> = {};
      const pending = [...watchlist];
      // Bound requests as the watchlist grows to 30 markets.
      await Promise.all(Array.from({ length: Math.min(3, pending.length) }, async () => {
        let symbol: string | undefined;
        while ((symbol = pending.shift()) !== undefined) {
          const [ticker, candles] = await Promise.allSettled([
            marketApi.getPrice(symbol), marketApi.getOHLCV(symbol, '1h', 170),
          ]);
          if (ticker.status === 'fulfilled') {
            fresh[symbol] = summarizeCandles(ticker.value.data.price, candles.status === 'fulfilled' ? candles.value.data : []);
            setQuotes(current => ({ ...current, [symbol as string]: fresh[symbol as string] }));
          }
        }
      }));
      setQuotes(fresh);
      setError('');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load dashboard');
    } finally {
      fetching.current = false;
      setInitialLoading(false);
      setRefreshing(false);
    }
  };

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 30000);
    const clock = setInterval(() => setNow(Date.now()), 1000);
    return () => { clearInterval(interval); clearInterval(clock); };
  }, []);

  const toggleBot = async () => {
    if (botAction) return;
    setBotAction('toggle');
    try {
      if (botState?.is_running) {
        await botApi.stop();
      } else {
        await botApi.start();
      }
      fetchAll();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Bot action failed');
    } finally {
      setBotAction(null);
    }
  };

  const emergencyStop = async () => {
    if (botAction) return;
    setBotAction('emergency');
    try {
      await botApi.emergencyStop();
      fetchAll();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Emergency stop failed');
    } finally {
      setBotAction(null);
    }
  };

  const initialEquity = portfolio?.initial_equity ?? 500;
  const pnl = portfolio ? portfolio.equity - initialEquity : 0;
  const pnlPct = portfolio && initialEquity > 0 ? (pnl / initialEquity) * 100 : 0;
  const isUp = pnl >= 0;

  const formatNumber = (n: number, digits = 2) =>
    n.toLocaleString('de-DE', { minimumFractionDigits: digits, maximumFractionDigits: digits });

  const formatCoin = (n: number) => n.toLocaleString('de-AT', { maximumFractionDigits: 7 });

  const formatDate = (d: string) => new Date(/(?:Z|[+-]\d{2}:\d{2})$/.test(d) ? d : `${d}Z`).toLocaleString('de-DE', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });

  const modeColor = portfolio?.mode === 'LIVE' ? 'badge-danger' : portfolio?.mode === 'PAPER' ? 'badge-success' : 'badge-warning';
  const healthColor = botState?.health === 'HEALTHY' ? 'badge-success' : botState?.health === 'ERROR' ? 'badge-danger' : 'badge-warning';

  return (
    <div aria-busy={initialLoading}>
      {refreshing && !initialLoading && <div className="refresh-progress" role="progressbar" aria-label="Refreshing dashboard" />}
      {error && (
        <div className="card mb-2" style={{ borderColor: 'rgba(239,68,68,0.4)', background: 'var(--danger-dim)' }}>
          <div className="flex items-center gap-2 text-danger">
            <AlertTriangle size={18} />
            {error}
          </div>
        </div>
      )}

      <div className="page-heading">
        <div><span className="page-eyebrow">TRADING WORKSPACE</span><h2 className="section-title">Dashboard</h2></div>
        <span className={`sync-state ${refreshing ? 'is-syncing' : ''}`} role="status">
          <span className="sync-dot" />{initialLoading ? 'Loading live data' : refreshing ? 'Refreshing' : 'Live · updates every 30s'}
        </span>
      </div>
      <div className="grid grid-12 mb-3">
        {/* Portfolio value - hero metric */}
        <div className="card span-4 portfolio-summary-card">
          <div className="metric">
            <span className="metric-label">Portfolio Value</span>
            {initialLoading ? <span className="skeleton skeleton-value" /> : <span className="metric-value">€{portfolio ? formatNumber(portfolio.equity) : '—'}</span>}
            {initialLoading ? <span className="skeleton skeleton-line" /> : <div className="flex items-center gap-2 mt-1 metric-context">
              <span className={`metric-change ${isUp ? 'up' : 'down'}`}>
                {isUp ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
                {isUp ? '+' : ''}€{formatNumber(pnl)} ({isUp ? '+' : ''}{pnlPct.toFixed(2)}%)
              </span>
              <span className="text-muted" style={{ fontSize: '0.8rem' }}>vs €{initialEquity.toFixed(2)} {portfolio?.mode === 'LIVE' ? 'net funded' : 'initial'}</span>
            </div>}
          </div>
        </div>

        {/* Cash */}
        <div className="card span-2">
          <div className="metric">
            <span className="metric-label flex items-center gap-1">
              <Wallet size={14} /> Cash
            </span>
            {initialLoading ? <span className="skeleton skeleton-value skeleton-value-sm" /> : <span className="metric-value metric-value-sm">€{portfolio ? formatNumber(portfolio.cash) : '—'}</span>}
          </div>
        </div>

        {/* Mode */}
        <div className="card span-2">
          <div className="metric">
            <span className="metric-label flex items-center gap-1">
              <Activity size={14} /> Mode
            </span>
            <div className="mt-1">
              {initialLoading ? <span className="skeleton skeleton-pill" /> : <span className={`badge ${modeColor}`}>{portfolio?.mode || '—'}</span>}
            </div>
            <span className="text-muted mt-1" style={{ fontSize: '0.8rem' }}>Autonomous portfolio</span>
          </div>
        </div>

        {/* Current price */}
        <div className="card span-4">
          <div className="metric">
            <span className="metric-label flex items-center gap-1">
              <Coins size={14} /> Open Slots
            </span>
            {initialLoading ? <span className="skeleton skeleton-value skeleton-value-sm" /> : <span className="metric-value">{botState?.open_slots ?? '—'}</span>}
          </div>
        </div>

        {/* Bot control */}
        <div className="card span-12 bot-control-card">
          <div className="card-header" style={{ marginBottom: '0.75rem' }}>
            <div className="card-title">
              <BarChart3 className="card-title-icon" size={18} />
              Bot Control
            </div>
            <span className={`badge ${healthColor}`}>{botState?.health || 'UNKNOWN'}</span>
          </div>
          <div className="bot-actions">
            <button
              className={botState?.is_running ? 'btn-warning' : 'btn-success'}
              onClick={toggleBot}
              disabled={initialLoading || !!botAction}
              aria-busy={botAction === 'toggle'}
            >
              {botState?.is_running ? <Square size={16} /> : <Play size={16} />}
              {botAction === 'toggle' ? 'Updating…' : botState?.is_running ? 'Stop Bot' : 'Start Bot'}
            </button>
            <button className="btn-danger" onClick={emergencyStop} disabled={initialLoading || !!botAction} aria-busy={botAction === 'emergency'}>
              <AlertTriangle size={16} />
              {botAction === 'emergency' ? 'Stopping…' : 'Emergency'}
            </button>
          </div>
          <div className="text-muted mt-1" style={{ fontSize: '0.8rem' }}>
            Last run: {botState?.last_run_at ? formatDate(botState.last_run_at) : 'Never'}
          </div>
        </div>

        <div className="card span-12">
          <div className="card-header">
            <div className="card-title"><Activity className="card-title-icon" size={18} />Automatic strategy release</div>
            <span className={`badge ${research?.live_candidate?.status === 'LIVE_APPROVED' ? 'badge-success' : research?.live_candidate?.status === 'LIVE_APPROVED_CANARY' ? 'badge-warning' : 'badge-ghost'}`}>
              {research?.live_candidate?.status || 'NO LIVE CANDIDATE'}
            </span>
          </div>
          <div className="grid grid-12">
            <div className="span-4 metric">
              <span className="metric-label">Candidates tested</span>
              <span className="metric-value metric-value-sm">{research ? Object.values(research.counts).reduce((a, b) => a + b, 0) : '—'}</span>
            </div>
            <div className="span-4 metric">
              <span className="metric-label">Shadow progress</span>
              <span className="metric-value metric-value-sm">{(() => {
                const candidate = research?.candidates.find(c => c.status === 'PAPER_APPROVED');
                return candidate ? `${candidate.shadow_days.toFixed(1)}/${candidate.shadow_days_required}d · ${candidate.shadow_closed_trades}/${candidate.shadow_trades_required}` : '—';
              })()}</span>
            </div>
            <div className="span-4 metric">
              <span className="metric-label">Verified taker fee</span>
              <span className="metric-value metric-value-sm">{research?.verified_taker_fee_pct == null ? '—' : `${(research.verified_taker_fee_pct * 100).toFixed(2)}%`}</span>
            </div>
          </div>
          <p className="text-muted mt-1" style={{ fontSize: '0.82rem' }}>
            Live mode remains active. New buys require a locally validated candidate; the first live stage is limited to two positions and 25% total equity exposure.
          </p>
          {!!research?.candidates[0]?.failed_checks?.length && <p className="text-muted" style={{ fontSize: '0.82rem' }}>
            Latest failed checks: {research.candidates[0].failed_checks.join(', ')}
          </p>}
        </div>

        <div className="span-12 dashboard-section-break">
          <div><span className="page-eyebrow">CONNECTED ACCOUNT</span><h3>Kraken portfolio</h3></div>
          <span className="text-muted">Balances and account history</span>
        </div>
        <div className="span-12 dashboard-wide"><KrakenOverview /></div>

        <div className="card span-12 tracked-panel">
          <div className="card-header">
            <div className="card-title"><List className="card-title-icon" size={18} />Tracked coins</div>
            <span className="badge badge-ghost">{botState?.open_slots ?? 20} open slots</span>
          </div>
          <div className="text-muted mb-2">
            {!botState?.is_running ? 'Refresh paused while bot is stopped' : !botState?.watchlist_updated_at ? 'Selection pending' : (() => {
              const stamp = botState.watchlist_updated_at;
              const utc = /(?:Z|[+-]\d{2}:\d{2})$/.test(stamp) ? stamp : `${stamp}Z`;
              const remaining = Math.max(0, new Date(utc).getTime() + (botState.watchlist_refresh_seconds ?? 86400) * 1000 - now);
              return remaining ? `Next watchlist refresh in ${Math.floor(remaining / 3600000)}h ${Math.floor(remaining / 60000) % 60}m ${Math.floor(remaining / 1000) % 60}s` : 'Watchlist refresh due on next cycle';
            })()}
          </div>
          {!!botState?.memecoin_watchlist_target && <div className="text-muted mb-2">
            Memecoin radar: {botState.memecoin_watchlist_count} / {botState.memecoin_watchlist_target} tracked.
            {botState.memecoin_watchlist_count < botState.memecoin_watchlist_target && ' Waiting for more markets to pass market availability and quote/data checks. Entry liquidity limits are checked separately.'}
          </div>}
          <TrackedCoins symbols={botState?.watchlist || []} quotes={quotes} signals={signals} positions={positions} decisions={botState?.entry_decisions} running={botState?.is_running} discovery={botState?.discovery_stats} loading={initialLoading} />
          {botState?.last_error && <p className="text-danger">{botState.last_error}</p>}
        </div>
      </div>

      <div className="dashboard-section-break activity-heading">
        <div><span className="page-eyebrow">ACTIVITY</span><h3>Positions and decisions</h3></div>
        <span className="text-muted">What the bot owns, sees and has executed</span>
      </div>
      {/* Open Positions */}
      <div className="card mb-2">
        <div className="card-header">
          <div className="card-title">
            <List className="card-title-icon" size={18} />
            Open Positions
          </div>
        </div>
        {initialLoading ? <div className="table-skeleton" aria-label="Loading positions">{[1,2,3].map(i => <span key={i} className="skeleton" />)}</div> : positions.length === 0 ? (
          <div className="empty">No open positions</div>
        ) : (
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th className="text-right">Quantity</th>
                  <th className="text-right">Entry</th>
                  <th className="text-right">P/L</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.id}>
                    <td className="mono">{p.symbol}</td>
                    <td className="text-right mono">{formatCoin(p.quantity)}</td>
                    <td className="text-right mono">€{formatCoin(p.avg_entry_price)}</td>
                    <td className={`text-right mono ${p.unrealized_pnl >= 0 ? 'text-success' : 'text-danger'}`}>
                      {p.unrealized_pnl >= 0 ? '+' : ''}€{p.unrealized_pnl.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="grid grid-12">
        {/* Recent Signals */}
        <div className="card span-6">
          <div className="card-header">
            <div className="card-title">
              <SignalIcon className="card-title-icon" size={18} />
              Recent Signals
            </div>
          </div>
          {initialLoading ? <div className="table-skeleton" aria-label="Loading signals">{[1,2,3,4].map(i => <span key={i} className="skeleton" />)}</div> : signals.length === 0 ? (
            <div className="empty">No signals yet</div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Symbol</th><th>Action</th>
                    <th className="text-right">Prob</th>
                    <th>Why</th>
                  </tr>
                </thead>
                <tbody>
                  {signals.slice(0, 6).map((s) => (
                    <tr key={s.id}>
                      <td className="text-muted" style={{ fontSize: '0.82rem' }}>{formatDate(s.created_at)}</td>
                      <td className="mono">{s.symbol}</td>
                      <td>
                        <span className={`badge ${s.action === 'BUY' ? 'badge-success' : s.action === 'SELL' ? 'badge-danger' : 'badge-ghost'}`} style={{ color: s.action === 'BUY' ? 'var(--success)' : s.action === 'SELL' ? 'var(--danger)' : 'var(--muted)', background: 'transparent', border: '1px solid var(--border)' }}>
                          {s.action === 'BUY' ? <TrendingUp size={12} /> : s.action === 'SELL' ? <TrendingDown size={12} /> : <Activity size={12} />}
                          {s.action}
                        </span>
                      </td>
                      <td className="text-right mono">{s.model === 'momentum-v1' ? '—' : `${(s.probability * 100).toFixed(1)}%`}</td>
                      <td className="text-muted" style={{ fontSize: '0.82rem', maxWidth: '220px' }}>{s.explanation}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Trade History */}
        <div className="card span-6">
          <div className="card-header">
            <div className="card-title">
              <History className="card-title-icon" size={18} />
              Trade History
            </div>
          </div>
          {initialLoading ? <div className="table-skeleton" aria-label="Loading trades">{[1,2,3,4].map(i => <span key={i} className="skeleton" />)}</div> : trades.length === 0 ? (
            <div className="empty">No trades yet</div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Symbol</th><th>Side</th>
                    <th className="text-right">Qty</th>
                    <th className="text-right">Price</th>
                    <th className="text-right">P/L</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.slice(0, 8).map((t) => (
                    <tr key={t.id}>
                      <td className="text-muted" style={{ fontSize: '0.82rem' }}>{formatDate(t.created_at)}</td>
                      <td className="mono">{t.symbol}</td>
                      <td>
                        <span className={`badge ${t.side === 'BUY' ? 'badge-success' : 'badge-danger'}`} style={{ background: 'transparent', border: '1px solid var(--border)' }}>
                          {t.side}
                        </span>
                      </td>
                      <td className="text-right mono">{formatCoin(t.quantity)}</td>
                      <td className="text-right mono">€{formatCoin(t.price)}</td>
                      <td className={`text-right mono ${t.pnl !== null && t.pnl >= 0 ? 'text-success' : t.pnl !== null ? 'text-danger' : ''}`}>
                        {t.pnl !== null ? `${t.pnl >= 0 ? '+' : ''}€${t.pnl.toFixed(2)}` : '-'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
