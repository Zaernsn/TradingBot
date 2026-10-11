import { useState } from 'react';
import { Play, TrendingUp } from 'lucide-react';
import { marketApi } from '../services/api';
import type { BacktestResult } from '../types';

export default function BacktestPanel() {
  const [symbol, setSymbol] = useState('PORTFOLIO');
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const run = async () => {
    setLoading(true);
    try { const response = await marketApi.backtest(symbol); setResult(response.data); setError(''); }
    catch (err: any) { setError(err.response?.data?.detail || 'Backtest failed.'); }
    finally { setLoading(false); }
  };
  return <section className="card backtest-panel" aria-labelledby="backtest-title">
    <div className="card-header"><div className="card-title"><TrendingUp size={18} /> <span id="backtest-title">Backtest evidence</span></div><span className="badge badge-ghost">Research only</span></div>
    <p className="text-muted">Historical results are evidence, not a live-trading approval or a guarantee of future returns.</p>
    <div className="backtest-controls"><label>Market<input value={symbol} onChange={event => setSymbol(event.target.value.toUpperCase())} placeholder="PORTFOLIO or DOGE/EUR" /></label><button className="btn-primary" onClick={run} disabled={loading}><Play size={16} />{loading ? 'Running…' : 'Run backtest'}</button></div>
    {error && <p className="text-danger" role="alert">{error}</p>}
    {result && <><div className="backtest-metrics">
      <div><span>Net return</span><strong className={result.total_return_pct >= 0 ? 'text-success' : 'text-danger'}>{(result.total_return_pct * 100).toFixed(2)}%</strong></div>
      <div><span>Trades</span><strong>{result.num_trades}</strong></div><div><span>Win rate</span><strong>{(result.win_rate * 100).toFixed(1)}%</strong></div>
      <div><span>Max drawdown</span><strong className="text-danger">{(result.max_drawdown_pct * 100).toFixed(2)}%</strong></div>
      <div><span>Fees</span><strong>€{result.total_fees.toFixed(2)}</strong></div><div><span>Net expectancy</span><strong>€{result.expectancy.toFixed(2)}</strong></div>
    </div>{result.warnings.map(warning => <p className="text-muted" key={warning}>{warning}</p>)}</>}
  </section>;
}
