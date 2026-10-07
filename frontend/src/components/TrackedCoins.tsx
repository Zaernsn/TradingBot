import { useState } from 'react';
import { ArrowDownRight, ArrowUpRight, Search, Flame, TrendingUp, TrendingDown, Layers, Wallet } from 'lucide-react';
import type { Position, Signal, BotState, EntryDecision } from '../types';

const freshCheck = (stamp: string | undefined, now: number) => {
  const age = stamp ? now - new Date(stamp).getTime() : Infinity;
  return Number.isFinite(age) && age >= -30000 && age <= 120000;
};
export function readiness(held: boolean, running: boolean | undefined, decision?: EntryDecision, now = Date.now()) {
  const eligible = !held && running === true && decision?.model_status === 'ready' &&
    freshCheck(decision.checked_at, now) && decision.eligibility?.eligible === true &&
    freshCheck(decision.eligibility.checked_at, now) &&
    !['risk_halt','position_cap','daily_limit','allocation','execution_error','fee_reserve','order_size','liquidity','selection_unavailable'].includes(decision.code);
  return { eligible, buy: eligible && decision?.buy_candidate === true };
}

function ModelDetails({ decision }: { decision?: EntryDecision }) {
  const d = decision?.diagnostics;
  if (!d) return null;
  const time = (value?: string | null) => value ? new Date(value).toLocaleString() : 'Not available';
  return <details className="coin-model-details"><summary>Model and recovery details</summary>
    <div>History: {d.history_rows ?? '—'} hourly candles</div>
    <div>Active features: {d.feature_schema ?? 'Not trained yet'}</div>
    <div>Last trained: {time(d.trained_at)}</div>
    <div>Training observations: {time(d.training_start)} to {time(d.fit_window_end)}</div>
    <div>Latest completed candle: {time(d.latest_candle)}</div>
    {d.recovery && <div>Recovery: {d.recovery.state}{d.recovery.state !== 'ready' && d.recovery.retry_after && ` · Next retry requires fresh data after ${time(d.recovery.retry_after)}`}</div>}
    {d.recovery?.selection && <div>{d.recovery.selection}</div>}
    {d.candidate_comparison?.map(c => <div key={c.feature_schema}>{c.feature_schema}: {c.qualified ? 'qualified' : c.reason || (c.drift_detected ? 'drift remains' : 'validation not passed')} · Validation error {c.brier_score?.toFixed(3) ?? '—'}</div>)}
    {d.validation?.brier_score != null && <div>Validation error: {d.validation.brier_score.toFixed(3)} · Baseline: {d.validation.baseline_brier?.toFixed(3) ?? '—'} (lower is better)</div>}
    {d.drift_features?.map(f => <div key={f.feature}><strong>{f.feature}: {f.deviation.toFixed(1)}× deviation</strong><br />Observed {f.value.toPrecision(5)} · Training mean {f.training_mean.toPrecision(5)} · Scale {f.training_scale.toPrecision(5)}</div>)}
  </details>;
}

export function entryHint(held: boolean, running: boolean | undefined, decision?: { message: string; checked_at: string }, now = Date.now()) {
  if (held) return 'Already in your portfolio. The bot is monitoring its exit rules.';
  if (running === false) return 'Bot stopped. Start it to evaluate new entries.';
  if (!decision) return 'Waiting for the first entry evaluation.';
  const age = now - new Date(decision.checked_at).getTime();
  if (!Number.isFinite(age) || age > 120000 || age < -30000) return `Last recorded check (not current): ${decision.message}`;
  return decision.message;
}

export type CoinQuote = { price: number; hour: number | null; day: number | null; week: number | null; volume: number | null };
type Candle = { timestamp: string; close: number; volume: number };
export function summarizeCandles(price: number, candles: Candle[], now = Date.now()): CoinQuote {
  const hour = 3600000;
  const rows = candles.map(c => ({ ...c, end: new Date(/(?:Z|[+-]\d{2}:\d{2})$/.test(c.timestamp) ? c.timestamp : `${c.timestamp}Z`).getTime() + hour }))
    .filter(c => Number.isFinite(c.end) && c.end <= now && c.close > 0).sort((a, b) => a.end - b.end);
  const change = (hours: number) => {
    const target = now - hours * hour;
    const row = [...rows].reverse().find(c => c.end <= target && target - c.end < hour);
    return row && Number.isFinite(price) && price > 0 ? (price / row.close - 1) * 100 : null;
  };
  const latest = rows[rows.length - 1]?.end;
  const daily = rows.filter(c => latest !== undefined && c.end > latest - 24 * hour);
  const complete = latest !== undefined && now - latest < hour && daily.length === 24 && daily.every((c, i) => Number.isFinite(c.volume) && c.volume >= 0 && (!i || c.end - daily[i - 1].end === hour));
  return { price, hour: change(1), day: change(24), week: change(168), volume: complete ? daily.reduce((sum, c) => sum + c.close * c.volume, 0) : null };
}
const names: Record<string, string> = { BTC: 'Bitcoin', ETH: 'Ethereum', SOL: 'Solana', XRP: 'XRP', ADA: 'Cardano', DOGE: 'Dogecoin', SHIB: 'Shiba Inu', PEPE: 'Pepe', BONK: 'Bonk', WIF: 'dogwifhat', FLOKI: 'Floki', POPCAT: 'Popcat', BRETT: 'Brett', MOG: 'Mog Coin', MEW: 'cat in a dogs world', BOME: 'Book of Meme', SNEK: 'Snek', TURBO: 'Turbo', NEIRO: 'Neiro', PNUT: 'Peanut the Squirrel', GOAT: 'Goatseus Maximus', ACT: 'Act I', FARTCOIN: 'Fartcoin', TRUMP: 'Official Trump', MELANIA: 'Melania Meme', SPX: 'SPX6900', PONKE: 'Ponke', MEME: 'Memecoin', DEGEN: 'Degen', GIGA: 'Gigachad' };
const core = new Set(['BTC', 'ETH', 'SOL', 'XRP', 'ADA']);
const filters = [{ key: 'all', label: 'All tracked', icon: Layers }, { key: 'eligible', label: 'Eligible', icon: TrendingUp }, { key: 'buy', label: 'Buy candidates', icon: TrendingUp }, { key: 'waiting', label: 'Waiting / blocked', icon: Layers }, { key: 'meme', label: 'Memecoins', icon: Flame }, { key: 'gainers', label: 'Gainers', icon: TrendingUp }, { key: 'losers', label: 'Losers', icon: TrendingDown }, { key: 'held', label: 'In portfolio', icon: Wallet }] as const;
type Sort = 'day' | 'hour' | 'week' | 'volume' | 'price';
const money = (n: number, compact = false) => n > 0 && n < .0000001 && !compact ? '< €0.0000001' : new Intl.NumberFormat('en-IE', { style: 'currency', currency: 'EUR', notation: compact ? 'compact' : 'standard', maximumFractionDigits: compact ? 2 : 7 }).format(n);
function Change({ value }: { value: number | null | undefined }) {
  if (value == null || !Number.isFinite(value)) return <span className="coin-muted">—</span>;
  return <span className={`coin-change ${value > 0 ? 'positive' : value < 0 ? 'negative' : ''}`}>{value > 0 ? <ArrowUpRight size={14} /> : value < 0 ? <ArrowDownRight size={14} /> : null}{Math.abs(value).toFixed(2)}%</span>;
}
export default function TrackedCoins({ symbols, quotes, signals, positions, decisions, running, discovery, loading = false }: { symbols: string[]; quotes: Record<string, CoinQuote>; signals: Signal[]; positions: Position[]; decisions?: BotState['entry_decisions']; running?: boolean; discovery?: BotState['discovery_stats']; loading?: boolean }) {
  const [filter, setFilter] = useState<string>('all');
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState<Sort>('day');
  const [ascending, setAscending] = useState(false);
  const allSymbols = [...new Set([...symbols, ...positions.map(p => p.symbol)])];
  const now = Date.now();
  const blockers: Record<string, number> = {};
  const labels: Record<string, string> = { training: 'Retraining', blocked: 'Recovery blocked', drift: 'Feature drift', validation_failed: 'Validation failed', model_unavailable: 'Model unavailable', history_unavailable: 'History unavailable', market_unavailable: 'Market unavailable', risk_halt: 'Risk paused', position_cap: 'Position limit', daily_limit: 'Daily limit', allocation: 'Allocation limit', waiting_candle: 'Waiting for candle', ready: 'Waiting for signal' };
  for (const symbol of allSymbols) {
    if (positions.some(p => p.symbol === symbol)) continue;
    const decision = decisions?.[symbol];
    const state = readiness(false, running, decision, now);
    if (state.buy) continue;
    const key = !running ? 'Bot stopped' : !decision || !freshCheck(decision.checked_at, now) ? 'Awaiting current check' :
      labels[decision.code === 'waiting_candle' ? decision.model_status || 'waiting_candle' : decision.code] || 'Entry checks';
    blockers[key] = (blockers[key] || 0) + 1;
  }
  const rows = allSymbols.filter(symbol => {
    const ticker = symbol.split('/')[0];
    const day = quotes[symbol]?.day;
    const held = positions.some(p => p.symbol === symbol);
    const state = readiness(held, running, decisions?.[symbol], now);
    return `${ticker} ${names[ticker] || ''}`.toLowerCase().includes(query.toLowerCase().trim()) &&
      (filter !== 'meme' || !core.has(ticker)) && (filter !== 'gainers' || (day != null && day > 0)) &&
      (filter !== 'losers' || (day != null && day < 0)) && (filter !== 'held' || held) &&
      (filter !== 'eligible' || state.eligible) && (filter !== 'buy' || state.buy) &&
      (filter !== 'waiting' || (!held && !state.buy));
  }).sort((a, b) => {
    const av = quotes[a]?.[sort], bv = quotes[b]?.[sort];
    if (av == null) return bv == null ? a.localeCompare(b) : 1;
    if (bv == null) return -1;
    return (ascending ? av - bv : bv - av) || a.localeCompare(b);
  });
  const columns: { key: Sort; label: string }[] = [{ key: 'hour', label: '1h change' }, { key: 'day', label: '24h change' }, { key: 'week', label: '1w change' }, { key: 'volume', label: '24h volume ≈' }, { key: 'price', label: 'Price' }];
  return <section aria-label="Tracked coin market overview">
    <div className="coin-readiness-summary" aria-label="Entry blocker summary">{Object.entries(blockers).map(([label, count]) => <span key={label}>{label}: <strong>{count}</strong></span>)}</div>
    {discovery && <div className="coin-footnote"><span>Last scan: {discovery.discovered ?? '—'} discovered · {discovery.quoted ?? '—'} quoted · {discovery.market_eligible ?? '—'} passed liquidity · {discovery.history_eligible ?? '—'} with enough history</span><span>{discovery.scan_seconds != null && `${discovery.scan_seconds.toFixed(1)}s quote scan · `}{discovery.quote_failures ?? 0} quote failures{discovery.checked_at && ` · ${new Date(discovery.checked_at).toLocaleString()}`}</span></div>}
    <p className="coin-footnote">Eligible means the latest model and market preflight checks passed; it can still be HOLD or SELL. Final cash, risk and execution checks apply before every buy.</p>
    <div className="coin-toolbar">
      <div className="coin-filters" aria-label="Filter tracked coins">{filters.map(({ key, label, icon: Icon }) => <button key={key} className={filter === key ? 'selected' : ''} aria-pressed={filter === key} onClick={() => { setFilter(key); if (key === 'gainers' || key === 'losers') { setSort('day'); setAscending(key === 'losers'); } }}><Icon size={15} />{label}</button>)}</div>
      <div className="coin-search"><Search size={16} /><input aria-label="Search tracked coins" placeholder="Search coins" value={query} onChange={e => setQuery(e.target.value)} /></div>
    </div>
    {loading ? <div className="table-skeleton table-skeleton-lg" aria-label="Loading tracked coins">{[1,2,3,4,5].map(i => <span key={i} className="skeleton" />)}</div> : <div className="table-wrap coin-table-wrap" tabIndex={0} aria-label="Scrollable tracked coins table"><table className="coin-table">
      <caption className="sr-only">Tracked assets with approximate price changes and EUR pair volume</caption>
      <thead><tr><th scope="col">#</th><th scope="col">Asset</th>{columns.map(c => <th scope="col" key={c.key} aria-sort={sort === c.key ? ascending ? 'ascending' : 'descending' : 'none'}><button onClick={() => { setSort(c.key); setAscending(sort === c.key ? !ascending : false); }}>{c.label}{sort === c.key ? ascending ? ' ↑' : ' ↓' : ''}</button></th>)}<th scope="col">Signal / entry status</th></tr></thead>
      <tbody>{rows.map((symbol, index) => {
        const ticker = symbol.split('/')[0], q = quotes[symbol];
        const signal = signals.find(s => s.symbol === symbol);
        const held = positions.some(p => p.symbol === symbol);
        const hue = [...ticker].reduce((v, c) => v + c.charCodeAt(0), 0) * 47 % 360;
        return <tr key={symbol}><td className="coin-muted">{index + 1}</td><td><div className="coin-identity"><span className="coin-avatar" aria-hidden="true" style={{ background: `hsl(${hue} 45% 22%)`, color: `hsl(${hue} 80% 78%)` }}>{ticker.slice(0, 2)}</span><div><strong>{names[ticker] || ticker}</strong><div className="coin-symbol">{ticker}<span>{core.has(ticker) ? 'CORE' : 'MEME'}</span>{held && <span>HELD</span>}</div></div></div></td><td><Change value={q?.hour} /></td><td><Change value={q?.day} /></td><td><Change value={q?.week} /></td><td className="coin-muted">{q?.volume != null ? money(q.volume, true) : '—'}</td><td className="coin-price">{q?.price > 0 ? money(q.price) : '—'}</td><td><span className={`badge ${signal?.action === 'BUY' ? 'badge-success' : signal?.action === 'SELL' ? 'badge-danger' : 'badge-ghost'}`}>{signal?.action || '—'}</span><div className="coin-entry-hint">{entryHint(held, running, decisions?.[symbol])}</div>{decisions?.[symbol]?.market_note && <div className="coin-entry-hint">{decisions[symbol].market_note}</div>}<ModelDetails decision={decisions?.[symbol]} />{decisions?.[symbol]?.checked_at && <small className="coin-muted">Checked {new Date(decisions[symbol].checked_at).toLocaleTimeString()}</small>}</td></tr>;
      })}</tbody></table>
      {!rows.length && <div className="empty">{symbols.length ? 'No tracked coins match this filter.' : 'No tracked coins yet. Start the bot to build your watchlist.'}</div>}
    </div>}
    <div className="coin-footnote"><span>{rows.length} of {allSymbols.length} tracked / held assets · EUR pairs</span><span>Quotes refresh every 30s. Changes use hourly closes; volume is estimated from 24 completed hourly candles. Unavailable data: —. Market cap is not supplied by this feed.</span></div>
  </section>;
}
