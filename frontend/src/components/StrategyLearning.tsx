import { memo, useState } from 'react';
import { BrainCircuit, FlaskConical, ShieldCheck, CircleCheck, ChevronRight } from 'lucide-react';
import { ResearchStatus } from '../types';

const labels: Record<string, string> = {
  REJECTED: 'Rejected', PAPER_APPROVED: 'Paper testing', LIVE_APPROVED_CANARY: 'Limited live',
  LIVE_APPROVED: 'Live approved', LIVE_SUSPENDED: 'Suspended', IMPORTED_UNVERIFIED: 'Unverified',
};
const families: Record<string, string> = {
  adaptive_momentum: 'Adaptive momentum', volatility_trend: 'Volatility trend',
  breakout_liquidity: 'Liquidity breakout', defensive_mean_reversion: 'Defensive mean reversion',
  intraday_breakout: '15-minute breakout',
};
const reasons: Record<string, string> = {
  development_expectancy_positive: 'Development trades lost money on average',
  validation_expectancy_positive: 'Validation trades lost money on average',
  holdout_expectancy_positive: 'Final-test trades were not profitable on average',
  holdout_beats_cash: 'Did not beat holding cash', holdout_beats_momentum: 'Did not beat the momentum baseline',
  stress_positive: 'Did not remain profitable with doubled costs', drawdown_within_8pct: 'Final-test drawdown exceeded 8%',
  holdout_closed_trades_at_least_30: 'Needs at least 30 closed final-test trades',
  profit_concentration_within_80pct: 'Too much profit came from a few trades',
  minimum_forward_days: 'Still collecting forward-testing days', minimum_closed_trades: 'Still collecting paper trades',
  shadow_expectancy_positive: 'Paper trades are not profitable on average', shadow_return_positive: 'Paper return is not positive',
  shadow_beats_momentum: 'Paper results have not beaten momentum', drawdown_within_5pct: 'Paper drawdown exceeded 5%',
  risk_not_halted: 'Risk protection halted the test',
  validation_windows_positive: 'A validation window lost money or had fewer than five closed trades',
  shadow_profit_concentration_within_80pct: 'Paper profit is concentrated in a few trades or the evidence is missing',
};
const percent = (value?: number | null) => value == null || !Number.isFinite(value) ? '—' : `${(value * 100).toFixed(2)}%`;
const tone = (status: string) => status === 'LIVE_APPROVED' ? 'badge-success' : status === 'LIVE_APPROVED_CANARY' || status === 'PAPER_APPROVED' ? 'badge-warning' : 'badge-ghost';

function StrategyLearning({ research }: { research: ResearchStatus | null }) {
  const [filter, setFilter] = useState('all');
  const candidates = research?.candidates ?? [];
  const counts = research?.counts ?? {};
  const visible = candidates.filter(c => filter === 'all' || (filter === 'live' ? c.status.startsWith('LIVE_') : c.status === filter));
  const enabled = research?.learning_policy?.enabled;
  const failed = research?.research?.status === 'error';
  const active = research?.live_candidate;
  const stages = [
    { icon: BrainCircuit, title: 'Generate', text: 'Bounded variations across five families, including 15-minute breakouts' },
    { icon: FlaskConical, title: 'Test', text: 'Multiple chronological windows, unseen data and doubled-cost stress' },
    { icon: ShieldCheck, title: 'Paper prove', text: '30 closed forward trades and passing results; no fixed day wait' },
    { icon: CircleCheck, title: 'Auto-promote', text: 'One limited-live winner, with risk checks' },
  ];
  return <section className="card span-12 learning-panel" aria-labelledby="learning-title">
    <div className="learning-heading">
      <div><span className="page-eyebrow">AUTONOMOUS RESEARCH</span><h3 id="learning-title">Strategy lab</h3>
        <p className="text-muted">Learn from results. Keep the evidence. Promote only proven candidates.</p></div>
      <span className={`badge ${failed ? 'badge-warning' : enabled ? 'badge-success' : 'badge-ghost'}`}>
        {research == null ? 'Loading research' : failed ? 'Research needs attention' : enabled ? 'Automatic learning on' : 'Automatic mode not selected'}
      </span>
    </div>
    <div className="learning-stages">{stages.map(({ icon: Icon, title, text }, index) =>
      <div className="learning-stage" key={title}><span className="learning-stage-icon"><Icon size={18} /></span>
        <div><strong>{index + 1}. {title}</strong><p>{text}</p></div><ChevronRight className="learning-stage-arrow" size={16} /></div>)}</div>
    <div className="learning-metrics">
      <div><span>Evaluated</span><strong>{research ? candidates.length : '—'}<small> / {research?.learning_policy?.maximum_strategy_identities ?? 128} budget</small></strong></div>
      <div><span>Rejected & retained</span><strong>{research ? counts.REJECTED ?? 0 : '—'}</strong></div>
      <div><span>Paper testing</span><strong>{research ? counts.PAPER_APPROVED ?? 0 : '—'}</strong></div>
      <div><span>Live controller</span><strong className="learning-controller">{active ? labels[active.status] ?? active.status : 'No qualified winner'}</strong></div>
    </div>
    <div className="learning-policy"><ShieldCheck size={17} /><span>No manual approval. Passing candidates automatically enter a small live pilot: at most one position and 5% total exposure, within your existing limits. A realized loss of 1% of pilot starting equity suspends new entries; gaps can exceed this limit. No winner means no approved automatic live entries.</span></div>
    {failed && <p role="status" className="text-danger">{research?.research?.message || 'Research could not complete its latest pass.'}</p>}
    <div className="learning-list-heading"><h4>Candidate evidence</h4><div className="learning-filters" role="group" aria-label="Filter strategy candidates">
      {[['all','All'], ['PAPER_APPROVED','Paper'], ['live','Live / suspended'], ['REJECTED','Rejected']].map(([value, label]) =>
        <button type="button" key={value} aria-pressed={filter === value} onClick={() => setFilter(value)}>{label}</button>)}
    </div></div>
    <div className="learning-candidates">{visible.length ? visible.map(candidate =>
      <details className="learning-candidate" key={candidate.candidate_id}>
        <summary><div><strong>{families[candidate.family] ?? candidate.family}</strong><span>{candidate.timeframe === '15m' ? '15-minute' : 'Hourly'} evidence · Tested {new Date(candidate.tested_at).toLocaleString()} · {candidate.research_revisions ?? 0} retests</span></div>
          <div className="learning-return"><span>Final test</span><strong>{percent(candidate.holdout?.total_return_pct)}</strong></div>
          <span className={`badge ${tone(candidate.status)}`}>{labels[candidate.status] ?? candidate.status}</span></summary>
        <div className="learning-evidence"><div className="learning-evidence-metrics">
          <span>Doubled-cost return <strong>{percent(candidate.stress?.total_return_pct)}</strong></span>
          <span>Final-test drawdown <strong>{percent(candidate.holdout?.max_drawdown_pct)}</strong></span>
          <span>Paper evidence <strong>{candidate.shadow_days.toFixed(1)} days observed · {candidate.shadow_closed_trades}/{candidate.shadow_trades_required} trades · no minimum days</strong></span>
        </div>
          {candidate.failed_checks.length > 0 && <ul>{candidate.failed_checks.map(reason => <li key={reason}>{reasons[reason] ?? reason.replace(/_/g,' ')}</li>)}</ul>}
          {candidate.stopped_stage && <p>Stopped early at {candidate.stopped_stage.replace(/_/g, ' ')}; later test stages were skipped.</p>}
          {!!candidate.validation_windows?.length && <p>Validation windows passed: {candidate.validation_windows.filter(window => window.passed).length}/{candidate.validation_windows.length} evaluated.</p>}
          {candidate.promotion_reason && <p>{candidate.promotion_reason}</p>}
          {candidate.shadow_rejection && <p>{candidate.shadow_rejection}</p>}
          {candidate.canary?.suspension_reason && <p>{candidate.canary.suspension_reason}</p>}
          <small className="learning-id">{candidate.candidate_id}</small>
        </div>
      </details>) : <p className="learning-empty">{research ? 'No candidates in this stage yet. Learning waits for enough market evidence; it does not force a winner.' : 'Loading strategy evidence…'}</p>}</div>
    <p className="learning-footnote">Automatic-mode accounts: research every five minutes, up to three historical evaluations per pass. Failing candidates stop early. Each candidate uses its own completed hourly or 15-minute candles for research, paper testing and trading; current execution conditions are rechecked each entry cycle. Verified taker fee: {percent(research?.verified_taker_fee_pct)}. Historical results do not guarantee live profits.</p>
  </section>;
}

export default memo(StrategyLearning);
