import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import TrackedCoins, { CoinQuote, summarizeCandles } from '../components/TrackedCoins';
import { botApi, marketApi, portfolioApi } from '../services/api';
import type { BotState, Position, Signal } from '../types';

export default function Markets() {
  const [bot, setBot] = useState<BotState | null>(null);
  const [positions, setPositions] = useState<Position[]>([]);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [quotes, setQuotes] = useState<Record<string, CoinQuote>>({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState('');
  const mounted = useRef(true);

  const load = async () => {
    setRefreshing(true);
    try {
      const [botRes, positionRes, signalRes] = await Promise.all([botApi.getState(), portfolioApi.getPositions(), portfolioApi.getSignals()]);
      if (!mounted.current) return;
      setBot(botRes.data); setPositions(positionRes.data); setSignals(signalRes.data); setError('');
      const symbols = [...new Set<string>([...(botRes.data.watchlist || []), ...positionRes.data.map((position: Position) => position.symbol)])];
      const rows = await Promise.all(symbols.map(async symbol => {
        try {
          const [price, candles] = await Promise.all([marketApi.getPrice(symbol), marketApi.getOHLCV(symbol, '1h', 170)]);
          return [symbol, summarizeCandles(price.data.price, candles.data)] as const;
        } catch { return null; }
      }));
      if (mounted.current) setQuotes(Object.fromEntries(rows.filter((row): row is readonly [string, CoinQuote] => row !== null)));
    } catch (err: any) {
      if (mounted.current) setError(err.response?.data?.detail || 'Could not load tracked markets.');
    } finally {
      if (mounted.current) { setLoading(false); setRefreshing(false); }
    }
  };

  useEffect(() => {
    mounted.current = true; void load();
    const interval = setInterval(load, 30000);
    return () => { mounted.current = false; clearInterval(interval); };
  }, []);

  return <div aria-busy={loading}>
    <div className="page-heading"><div><span className="page-eyebrow">MARKET SCANNER</span><h2 className="section-title">Markets</h2><p className="text-muted">What the bot is watching, and why each market can or cannot be entered.</p></div>
      <button className="btn-ghost" onClick={load} disabled={refreshing}><RefreshCw size={16} />{refreshing ? 'Refreshing…' : 'Refresh'}</button></div>
    {error && <div className="safety-banner is-critical" role="alert"><AlertTriangle size={18} />{error}</div>}
    <section className="card tracked-panel">
      <div className="card-header"><div className="card-title">Tracked markets</div><span className="badge badge-ghost">{bot?.watchlist?.length ?? 0} tracked</span></div>
      <p className="text-muted">Tracked does not mean eligible to buy. Expand a market’s diagnostics to inspect model and recovery evidence.</p>
      <TrackedCoins symbols={bot?.watchlist || []} quotes={quotes} signals={signals} positions={positions} decisions={bot?.entry_decisions} running={bot?.is_running} discovery={bot?.discovery_stats} loading={loading} />
    </section>
  </div>;
}
