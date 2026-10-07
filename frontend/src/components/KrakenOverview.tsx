import { useEffect, useState } from 'react';
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { Link } from 'react-router-dom';
import api from '../services/api';

type Holding = { asset: string; quantity: number; price: number | null; value: number | null };
type Overview = { connected: boolean; equity: number | null; captured_at?: string; holdings: Holding[]; history: { timestamp: string; value: number | null }[] };
const ranges = { '1D': 1, '1W': 7, '1M': 30, '3M': 90, '1Y': 365, ALL: Infinity };
const euro = (n: number) => new Intl.NumberFormat('de-AT', { style: 'currency', currency: 'EUR', maximumFractionDigits: 2 }).format(n);
const coin = (n: number) => new Intl.NumberFormat('de-AT', { maximumFractionDigits: 7 }).format(n);
export default function KrakenOverview() {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState('');
  const [range, setRange] = useState<keyof typeof ranges>('1M');
  useEffect(() => {
    let active = true, running = false;
    const refresh = async () => {
      if (running) return;
      running = true;
      try { const result = await api.get<Overview>('/portfolio/kraken-overview'); if (active) { setData(result.data); setError(''); } }
      catch { if (active) setError('Kraken sync unavailable. Check the saved API key and balance-query permission in Settings.'); }
      finally { running = false; }
    };
    refresh(); const timer = setInterval(refresh, 300000);
    return () => { active = false; clearInterval(timer); };
  }, []);
  const cutoff = Date.now() - ranges[range] * 86400000;
  const points = (data?.history || []).filter(p => new Date(p.timestamp).getTime() >= cutoff).map(p => ({ time: new Date(p.timestamp).getTime(), value: p.value }));
  const first = points[0]?.value, last = points[points.length - 1]?.value;
  const change = first != null && last != null && points.length > 1 ? last - first : null;
  const categories = [
    { name: 'Core crypto', color: '#d4af37', match: (a: string) => ['BTC', 'ETH', 'SOL', 'XRP', 'ADA'].includes(a) },
    { name: 'Cash & stablecoins', color: '#a78bfa', match: (a: string) => ['EUR', 'USD', 'GBP', 'CHF', 'USDT', 'USDC', 'DAI', 'EURC'].includes(a) },
    { name: 'Other crypto', color: '#34d399', match: (a: string) => !['BTC', 'ETH', 'SOL', 'XRP', 'ADA', 'EUR', 'USD', 'GBP', 'CHF', 'USDT', 'USDC', 'DAI', 'EURC'].includes(a) },
  ];
  return <section className="card kraken-overview mb-3" aria-label="Kraken account history">
    <div className="overview-heading"><div><span className="login-eyebrow">YOUR KRAKEN ACCOUNT</span><h2>Portfolio overview</h2><p className="text-muted">Spot balances from your saved Kraken API connection</p></div><div className="coin-filters">{Object.keys(ranges).map(r => <button key={r} aria-pressed={range === r} className={range === r ? 'selected' : ''} onClick={() => setRange(r as keyof typeof ranges)}>{r}</button>)}</div></div>
    {error && <p role="alert" className="text-danger">{error}{data && ' Displaying the last successful sync.'}</p>}
    {!data ? error ? <div className="empty">Account data is currently unavailable.</div> : <div className="overview-skeleton" aria-label="Loading Kraken account"><span className="skeleton skeleton-value" /><span className="skeleton skeleton-line" /><span className="skeleton skeleton-chart" /><div className="overview-categories">{[1,2,3].map(i => <span key={i} className="skeleton skeleton-card" />)}</div></div> : !data.connected ? <div className="empty">Connect your Kraken API in <Link to="/settings">Settings</Link> to see balances and start recording account history.</div> : <>
      <div className="overview-total">{data.equity == null ? 'Valuation incomplete' : euro(data.equity)}</div>
      <p className={change != null && change < 0 ? 'text-danger' : 'text-success'}>{change == null ? 'More snapshots needed to show change' : `${change >= 0 ? '+' : ''}${euro(change)}${first ? ` (${(change / first * 100).toFixed(2)}%)` : ''} balance change in selected period`}</p>
      <div className="overview-chart">{points.length > 1 ? <ResponsiveContainer width="100%" height={280}><AreaChart data={points}><defs><linearGradient id="equityFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="#d4af37" stopOpacity={0.2} /><stop offset="100%" stopColor="#d4af37" stopOpacity={0} /></linearGradient></defs><CartesianGrid stroke="#ffffff0c" vertical={false} /><XAxis dataKey="time" type="number" domain={['dataMin', 'dataMax']} tickFormatter={t => new Date(t).toLocaleDateString('de-AT', { day: '2-digit', month: 'short' })} stroke="#82909e" minTickGap={50} /><YAxis domain={['auto', 'auto']} tickFormatter={n => euro(n)} width={95} stroke="#82909e" /><Tooltip labelFormatter={t => new Date(Number(t)).toLocaleString('de-AT')} formatter={(v: number) => [euro(v), 'Account value']} contentStyle={{ background: '#141b25', border: '1px solid #334155', borderRadius: 10 }} /><Area dataKey="value" type="linear" stroke="#f8fafc" strokeWidth={2} fill="url(#equityFill)" connectNulls={false} isAnimationActive={false} /></AreaChart></ResponsiveContainer> : <div className="empty">{points.length ? 'Your first snapshot is saved. The chart will grow as balances sync.' : 'No snapshots in this date range.'}</div>}</div>
      <div className="overview-categories">{categories.map(c => { const holdings = data.holdings.filter(h => c.match(h.asset)); const complete = holdings.every(h => h.value != null); return <div key={c.name} style={{ borderTopColor: c.color }}><span>{c.name}</span><strong>{complete ? euro(holdings.reduce((v, h) => v + (h.value || 0), 0)) : 'Partly unpriced'}</strong><small>{holdings.length} assets</small></div>; })}</div>
      <details className="overview-holdings"><summary>Account holdings · {data.holdings.length} assets</summary><div className="table-wrap"><table><thead><tr><th>Asset</th><th>Balance</th><th>Price (EUR)</th><th>Value</th></tr></thead><tbody>{data.holdings.map(h => <tr key={h.asset}><td>{h.asset}</td><td>{coin(h.quantity)}</td><td>{h.price != null ? coin(h.price) : 'Unavailable'}</td><td>{h.value != null ? euro(h.value) : 'Unpriced'}</td></tr>)}</tbody></table></div></details>
      <p className="coin-footnote">Last synced: {data.captured_at ? new Date(data.captured_at).toLocaleString('de-AT') : '—'}. Syncs every 5 minutes while this dashboard is open. History starts at first sync; past account history is not imported. Balance changes include deposits and withdrawals and are not trading returns. Assets without a direct EUR conversion remain unpriced.</p>
    </>}
  </section>;
}
