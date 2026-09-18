import { useEffect, useState } from 'react';
import { XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid, Area, AreaChart } from 'recharts';
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
  OHLCV,
  RiskConfig,
} from '../types';
import {
  portfolioApi,
  marketApi,
  botApi,
  settingsApi,
} from '../services/api';

export default function Dashboard() {
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [trades, setTrades] = useState<Trade[]>([]);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [botState, setBotState] = useState<BotState | null>(null);
  const [price, setPrice] = useState<number | null>(null);
  const [ohlcv, setOhlcv] = useState<OHLCV[]>([]);
  const [risk, setRisk] = useState<RiskConfig | null>(null);
  const [error, setError] = useState('');

  const symbol = risk?.trading_pair || 'BTC/EUR';

  const loadRisk = async () => {
    try {
      const res = await settingsApi.getRisk();
      setRisk(res.data);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load risk config');
    }
  };

  const fetchAll = async () => {
    try {
      const [pRes, posRes, tRes, sRes, bRes, priceRes, ohlcvRes] = await Promise.all([
        portfolioApi.getPortfolio(),
        portfolioApi.getPositions(),
        portfolioApi.getTrades(),
        portfolioApi.getSignals(),
        botApi.getState(),
        marketApi.getPrice(symbol),
        marketApi.getOHLCV(symbol, '1h', 100),
      ]);
      setPortfolio(pRes.data);
      setPositions(posRes.data);
      setTrades(tRes.data);
      setSignals(sRes.data);
      setBotState(bRes.data);
      setPrice(priceRes.data.price);
      setOhlcv(ohlcvRes.data);
      setError('');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load dashboard');
    }
  };

  useEffect(() => {
    loadRisk();
  }, []);

  useEffect(() => {
    if (!symbol) return;
    fetchAll();
    const interval = setInterval(fetchAll, 30000);
    return () => clearInterval(interval);
  }, [symbol]);

  const toggleBot = async () => {
    try {
      if (botState?.is_running) {
        await botApi.stop();
      } else {
        await botApi.start();
      }
      fetchAll();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Bot action failed');
    }
  };

  const emergencyStop = async () => {
    if (!confirm('Emergency stop will halt the bot and switch to paper mode. Continue?')) return;
    try {
      await botApi.emergencyStop();
      fetchAll();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Emergency stop failed');
    }
  };

  const initialEquity = 500;
  const pnl = portfolio ? portfolio.equity - initialEquity : 0;
  const pnlPct = portfolio ? (pnl / initialEquity) * 100 : 0;
  const isUp = pnl >= 0;

  const formatNumber = (n: number, digits = 2) =>
    n.toLocaleString('de-DE', { minimumFractionDigits: digits, maximumFractionDigits: digits });

  const formatDate = (d: string) => new Date(d).toLocaleString('de-DE', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });

  const modeColor = portfolio?.mode === 'LIVE' ? 'badge-danger' : portfolio?.mode === 'PAPER' ? 'badge-success' : 'badge-warning';
  const healthColor = botState?.health === 'HEALTHY' ? 'badge-success' : botState?.health === 'ERROR' ? 'badge-danger' : 'badge-warning';

  return (
    <div>
      {error && (
        <div className="card mb-2" style={{ borderColor: 'rgba(239,68,68,0.4)', background: 'var(--danger-dim)' }}>
          <div className="flex items-center gap-2 text-danger">
            <AlertTriangle size={18} />
            {error}
          </div>
        </div>
      )}

      <h2 className="section-title">Dashboard</h2>

      <div className="grid grid-12 mb-3">
        {/* Portfolio value - hero metric */}
        <div className="card span-4">
          <div className="metric">
            <span className="metric-label">Portfolio Value</span>
            <span className="metric-value">€{portfolio ? formatNumber(portfolio.equity) : '---'}</span>
            <div className="flex items-center gap-2 mt-1">
              <span className={`metric-change ${isUp ? 'up' : 'down'}`}>
                {isUp ? <ArrowUpRight size={14} /> : <ArrowDownRight size={14} />}
                {isUp ? '+' : ''}€{formatNumber(pnl)} ({isUp ? '+' : ''}{pnlPct.toFixed(2)}%)
              </span>
              <span className="text-muted" style={{ fontSize: '0.8rem' }}>vs €{initialEquity} initial</span>
            </div>
          </div>
        </div>

        {/* Cash */}
        <div className="card span-2">
          <div className="metric">
            <span className="metric-label flex items-center gap-1">
              <Wallet size={14} /> Cash
            </span>
            <span className="metric-value metric-value-sm">€{portfolio ? formatNumber(portfolio.cash) : '---'}</span>
          </div>
        </div>

        {/* Mode */}
        <div className="card span-2">
          <div className="metric">
            <span className="metric-label flex items-center gap-1">
              <Activity size={14} /> Mode
            </span>
            <div className="mt-1">
              <span className={`badge ${modeColor}`}>{portfolio?.mode || '---'}</span>
            </div>
            <span className="text-muted mt-1" style={{ fontSize: '0.8rem' }}>{symbol}</span>
          </div>
        </div>

        {/* Current price */}
        <div className="card span-4">
          <div className="metric">
            <span className="metric-label flex items-center gap-1">
              <Coins size={14} /> Current Price — {symbol}
            </span>
            <span className="metric-value">€{price ? formatNumber(price, price < 1 ? 4 : 2) : '---'}</span>
          </div>
        </div>

        {/* Bot control */}
        <div className="card span-4">
          <div className="card-header" style={{ marginBottom: '0.75rem' }}>
            <div className="card-title">
              <BarChart3 className="card-title-icon" size={18} />
              Bot Control
            </div>
            <span className={`badge ${healthColor}`}>{botState?.health || 'UNKNOWN'}</span>
          </div>
          <div className="flex items-center gap-2">
            <button
              className={botState?.is_running ? 'btn-warning' : 'btn-success'}
              onClick={toggleBot}
              style={{ flex: 1 }}
            >
              {botState?.is_running ? <Square size={16} /> : <Play size={16} />}
              {botState?.is_running ? 'Stop Bot' : 'Start Bot'}
            </button>
            <button className="btn-danger" onClick={emergencyStop}>
              <AlertTriangle size={16} />
              Emergency
            </button>
          </div>
          <div className="text-muted mt-1" style={{ fontSize: '0.8rem' }}>
            Last run: {botState?.last_run_at ? formatDate(botState.last_run_at) : 'Never'}
          </div>
        </div>

        {/* Price chart */}
        <div className="card span-8" style={{ display: 'flex', flexDirection: 'column' }}>
          <div className="card-header">
            <div className="card-title">
              <TrendingUp className="card-title-icon" size={18} />
              Price Chart — {symbol}
            </div>
          </div>
          <div className="chart-container" style={{ flex: 1 }}>
            <ResponsiveContainer width="100%" height={320}>
              <AreaChart data={ohlcv.map((d) => ({ time: new Date(d.timestamp).toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' }), close: d.close }))}>
                <defs>
                  <linearGradient id="priceGradient" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#D4AF37" stopOpacity={0.25} />
                    <stop offset="95%" stopColor="#D4AF37" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid stroke="rgba(148,163,184,0.08)" vertical={false} />
                <XAxis dataKey="time" stroke="#94A3B8" fontSize={11} tickLine={false} axisLine={false} />
                <YAxis stroke="#94A3B8" fontSize={11} tickLine={false} axisLine={false} domain={['auto', 'auto']} tickFormatter={(v) => `€${v}`} />
                <Tooltip
                  contentStyle={{ background: '#151B2B', border: '1px solid var(--border)', borderRadius: '8px' }}
                  itemStyle={{ color: '#F8FAFC', fontFamily: 'var(--font-mono)' }}
                  formatter={(value: number) => [`€${value.toFixed(2)}`, 'Close']}
                />
                <Area type="monotone" dataKey="close" stroke="#D4AF37" strokeWidth={2} fill="url(#priceGradient)" />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Open Positions */}
      <div className="card mb-2">
        <div className="card-header">
          <div className="card-title">
            <List className="card-title-icon" size={18} />
            Open Positions
          </div>
        </div>
        {positions.length === 0 ? (
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
                    <td className="text-right mono">{p.quantity.toFixed(6)}</td>
                    <td className="text-right mono">€{p.avg_entry_price.toFixed(2)}</td>
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
          {signals.length === 0 ? (
            <div className="empty">No signals yet</div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Action</th>
                    <th className="text-right">Prob</th>
                    <th>Why</th>
                  </tr>
                </thead>
                <tbody>
                  {signals.slice(0, 6).map((s) => (
                    <tr key={s.id}>
                      <td className="text-muted" style={{ fontSize: '0.82rem' }}>{formatDate(s.created_at)}</td>
                      <td>
                        <span className={`badge ${s.action === 'BUY' ? 'badge-success' : s.action === 'SELL' ? 'badge-danger' : 'badge-ghost'}`} style={{ color: s.action === 'BUY' ? 'var(--success)' : s.action === 'SELL' ? 'var(--danger)' : 'var(--muted)', background: 'transparent', border: '1px solid var(--border)' }}>
                          {s.action === 'BUY' ? <TrendingUp size={12} /> : s.action === 'SELL' ? <TrendingDown size={12} /> : <Activity size={12} />}
                          {s.action}
                        </span>
                      </td>
                      <td className="text-right mono">{(s.probability * 100).toFixed(1)}%</td>
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
          {trades.length === 0 ? (
            <div className="empty">No trades yet</div>
          ) : (
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Side</th>
                    <th className="text-right">Qty</th>
                    <th className="text-right">Price</th>
                    <th className="text-right">P/L</th>
                  </tr>
                </thead>
                <tbody>
                  {trades.slice(0, 8).map((t) => (
                    <tr key={t.id}>
                      <td className="text-muted" style={{ fontSize: '0.82rem' }}>{formatDate(t.created_at)}</td>
                      <td>
                        <span className={`badge ${t.side === 'BUY' ? 'badge-success' : 'badge-danger'}`} style={{ background: 'transparent', border: '1px solid var(--border)' }}>
                          {t.side}
                        </span>
                      </td>
                      <td className="text-right mono">{t.quantity.toFixed(6)}</td>
                      <td className="text-right mono">€{t.price.toFixed(2)}</td>
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
