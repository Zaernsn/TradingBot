import type { ExecutionCostsReport } from '../types';

const money = (value: number | null | undefined) => value == null || !Number.isFinite(value) ? 'Unavailable' : `€${value.toFixed(2)}`;
const percent = (value: number | null | undefined) => value == null || !Number.isFinite(value) ? 'Unavailable' : `${(value * 100).toFixed(3)}%`;

export default function ExecutionCosts({ report, error }: { report: ExecutionCostsReport | null; error?: string }) {
  const live = report?.live_execution;
  const markets = report?.public_markets;
  return <section className="card span-12" aria-labelledby="execution-costs-title">
    <span className="page-eyebrow">EXECUTION EVIDENCE</span><h3 id="execution-costs-title">What trading costs</h3>
    <p className="text-muted">Public spread and liquidity samples every five minutes. Recorded conditions can change before a trade.</p>
    {error ? <p role="status">{error}</p> : !report ? <p>Loading cost evidence…</p> : <>
      <div className="learning-evidence-metrics">
        <span>Market samples, last day <strong>{markets?.observations ?? 0}</strong></span>
        <span>Median valid recorded spread <strong>{percent(markets?.median_valid_spread_pct)}</strong></span>
        <span>Actual live quote fees, last 30 days <strong>{money(live?.quote_fee_eur)}</strong></span>
        <span>Execution vs decision quote <strong>{money(live?.adverse_vs_touch_eur)}</strong></span>
      </div>
      <p>{live?.fresh_quote_matched_orders ?? 0}/{live?.filled_orders ?? 0} filled live orders have a fresh recorded decision quote. Paper fills are excluded; base-currency fees are reported separately by the API.</p>
      {markets && Object.keys(markets.latest).length ? <div style={{ overflowX: 'auto' }}><table>
        <thead><tr><th>Market</th><th>Recorded spread</th><th>Bid / ask depth</th><th>Sample age</th><th>Quality at collection</th></tr></thead>
        <tbody>{Object.entries(markets.latest).map(([symbol, sample]) => <tr key={symbol}>
          <td>{symbol}</td><td>{percent(sample.spread_pct)}</td>
          <td>{money(sample.bid_depth_eur)} / {money(sample.ask_depth_eur)}</td>
          <td>{Math.floor(sample.age_seconds / 60)} min</td><td>{sample.status.toLowerCase().replace(/_/g, ' ')}</td>
        </tr>)}</tbody></table></div> : <p>No market observations yet. Collection begins after the upgraded backend is running with Automatic mode selected.</p>}
      <p className="text-muted">Depth covers at most 20 price levels. Five-minute snapshots are evidence samples, not a continuous replay or a guarantee of available liquidity.</p>
    </>}
  </section>;
}
