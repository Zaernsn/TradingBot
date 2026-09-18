import { useEffect, useState } from 'react';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid } from 'recharts';
import {
  Portfolio,
  Position,
  Trade,
  Signal,
  BotState,
  OHLCV,
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
  const [price, setPrice] = useState<number | null>(null);
  const [ohlcv, setOhlcv] = useState<OHLCV[]>([]);
  const symbol = 'BTC/EUR';
  const [error, setError] = useState('');

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
    await botApi.emergencyStop();
    fetchAll();
  };

  const pnl = portfolio ? portfolio.equity - 500 : 0;
  const pnlPct = portfolio ? (pnl / 500) * 100 : 0;

  return (
    <div>
      {error && <p style={{ color: 'var(--danger)' }}>{error}</p>}

      <div className="grid grid-4">
        <div className="card">
          <div className="text-muted">Portfolio Value</div>
          <div style={{ fontSize: '1.6rem', fontWeight: 700 }}>€{portfolio?.equity.toFixed(2) || '---'}</div>
        </div>
        <div className="card">
          <div className="text-muted">Cash</div>
          <div style={{ fontSize: '1.6rem', fontWeight: 700 }}>€{portfolio?.cash.toFixed(2) || '---'}</div>
        </div>
        <div className="card">
          <div className="text-muted">P/L</div>
          <div style={{ fontSize: '1.6rem', fontWeight: 700, color: pnl >= 0 ? 'var(--success)' : 'var(--danger)' }}>
            {pnl >= 0 ? '+' : ''}€{pnl.toFixed(2)} ({pnlPct.toFixed(2)}%)
          </div>
        </div>
        <div className="card">
          <div className="text-muted">Mode</div>
          <div style={{ fontSize: '1.2rem', fontWeight: 700 }}>{portfolio?.mode}</div>
          <div className="text-muted">{botState?.health}</div>
        </div>
      </div>

      <div className="card" style={{ display: 'flex', gap: '1rem', alignItems: 'center', flexWrap: 'wrap' }}>
        <div>
          <div className="text-muted">Current Price ({symbol})</div>
          <div style={{ fontSize: '1.4rem', fontWeight: 700 }}>€{price?.toLocaleString() || '---'}</div>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: '0.5rem' }}>
          <button className={botState?.is_running ? 'btn-warning' : 'btn-success'} onClick={toggleBot}>
            {botState?.is_running ? 'Stop Bot' : 'Start Bot'}
          </button>
          <button className="btn-danger" onClick={emergencyStop}>Emergency Stop</button>
        </div>
      </div>

      <div className="card">
        <h3>Price Chart</h3>
        <div style={{ height: 300 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={ohlcv.map((d) => ({ time: new Date(d.timestamp).toLocaleTimeString(), close: d.close }))}>
              <CartesianGrid stroke="#334155" />
              <XAxis dataKey="time" stroke="#94a3b8" />
              <YAxis stroke="#94a3b8" domain={['auto', 'auto']} />
              <Tooltip />
              <Line type="monotone" dataKey="close" stroke="#3b82f6" dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="grid grid-4">
        <div className="card">
          <h3>Open Positions</h3>
          {positions.length === 0 ? (
            <p className="text-muted">No open positions</p>
          ) : (
            <table>
              <thead>
                <tr><th>Symbol</th><th>Qty</th><th>Entry</th><th>P/L</th></tr>
              </thead>
              <tbody>
                {positions.map((p) => (
                  <tr key={p.id}>
                    <td>{p.symbol}</td>
                    <td>{p.quantity.toFixed(6)}</td>
                    <td>€{p.avg_entry_price.toFixed(2)}</td>
                    <td style={{ color: p.unrealized_pnl >= 0 ? 'var(--success)' : 'var(--danger)' }}>
                      €{p.unrealized_pnl.toFixed(2)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="card" style={{ gridColumn: 'span 3' }}>
          <h3>Recent Signals</h3>
          {signals.length === 0 ? (
            <p className="text-muted">No signals yet</p>
          ) : (
            <table>
              <thead>
                <tr><th>Time</th><th>Action</th><th>Probability</th><th>Confidence</th><th>Why</th></tr>
              </thead>
              <tbody>
                {signals.map((s) => (
                  <tr key={s.id}>
                    <td>{new Date(s.created_at).toLocaleString()}</td>
                    <td style={{ fontWeight: 700, color: s.action === 'BUY' ? 'var(--success)' : s.action === 'SELL' ? 'var(--danger)' : 'var(--muted)' }}>{s.action}</td>
                    <td>{(s.probability * 100).toFixed(1)}%</td>
                    <td>{(s.confidence * 100).toFixed(1)}%</td>
                    <td>{s.explanation}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <div className="card">
        <h3>Trade History</h3>
        {trades.length === 0 ? (
          <p className="text-muted">No trades yet</p>
        ) : (
          <table>
            <thead>
              <tr><th>Time</th><th>Side</th><th>Symbol</th><th>Qty</th><th>Price</th><th>Fee</th><th>Total</th><th>Realized P/L</th><th>Reason</th></tr>
            </thead>
            <tbody>
              {trades.map((t) => (
                <tr key={t.id}>
                  <td>{new Date(t.created_at).toLocaleString()}</td>
                  <td style={{ color: t.side === 'BUY' ? 'var(--success)' : 'var(--danger)' }}>{t.side}</td>
                  <td>{t.symbol}</td>
                  <td>{t.quantity.toFixed(6)}</td>
                  <td>€{t.price.toFixed(2)}</td>
                  <td>€{t.fee.toFixed(4)}</td>
                  <td>€{t.total_cost.toFixed(2)}</td>
                  <td>{t.pnl !== null ? `€${t.pnl.toFixed(2)}` : '-'}</td>
                  <td>{t.reason || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
