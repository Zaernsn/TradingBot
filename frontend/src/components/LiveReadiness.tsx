import { Check, Clock3, AlertTriangle, Link2, Bot, Radio, BrainCircuit, ShoppingCart } from 'lucide-react';
import type { BotState, Portfolio, ResearchStatus } from '../types';

type StepState = 'complete' | 'waiting' | 'blocked';
type Step = { label: string; detail: string; state: StepState; icon: typeof Check };

export function readinessSteps(portfolio: Portfolio | null, bot: BotState | null, research: ResearchStatus | null): Step[] {
  const live = portfolio?.mode === 'LIVE';
  const accountReady = portfolio != null && !portfolio.risk_halted;
  const botReady = bot?.is_running === true;
  const marketReady = bot?.market_data_status?.connected !== false;
  const strategyReady = !live || research?.live_candidate != null || research == null;
  const halted = bot?.entry_halt?.halted === true || portfolio?.risk_halted === true;
  const upstream = [accountReady, botReady, marketReady, strategyReady];
  const stateFor = (ready: boolean, before: number) => ready ? 'complete' : upstream.slice(0, before).every(Boolean) ? 'blocked' : 'waiting';
  return [
    { label: 'Account', detail: portfolio ? `${portfolio.mode.replace('_', ' ').toLowerCase()} book active` : 'Loading account', state: portfolio ? 'complete' : 'waiting', icon: Link2 },
    { label: 'Safety', detail: accountReady ? 'Portfolio checks clear' : 'Risk protection needs attention', state: stateFor(accountReady, 0), icon: Check },
    { label: 'Bot', detail: botReady ? 'Entry loop is running' : 'Start the bot to evaluate entries', state: stateFor(botReady, 1), icon: Bot },
    { label: 'Market data', detail: marketReady ? 'Fresh data connection available' : 'Market feed unavailable', state: stateFor(marketReady, 2), icon: Radio },
    { label: 'Strategy', detail: strategyReady ? 'A strategy can evaluate entries' : 'No live-approved automatic candidate', state: stateFor(strategyReady, 3), icon: BrainCircuit },
    { label: 'New entry', detail: halted ? 'New buys are paused' : upstream.every(Boolean) ? 'Ready to evaluate signals' : 'Waiting for earlier checks', state: halted ? 'blocked' : upstream.every(Boolean) ? 'complete' : 'waiting', icon: ShoppingCart },
  ];
}

export default function LiveReadiness({ portfolio, bot, research }: { portfolio: Portfolio | null; bot: BotState | null; research: ResearchStatus | null }) {
  const steps = readinessSteps(portfolio, bot, research);
  const firstBlocked = steps.find(step => step.state === 'blocked');
  return <section className="card readiness-card" aria-labelledby="readiness-title">
    <div className="card-header"><div><span className="page-eyebrow">ENTRY READINESS</span><h3 id="readiness-title">{firstBlocked ? 'Action needed before new buys' : 'Ready to evaluate entries'}</h3></div>
      <span className={`badge ${firstBlocked ? 'badge-warning' : 'badge-success'}`}>{firstBlocked ? firstBlocked.label : 'Checks clear'}</span></div>
    <div className="readiness-chain">{steps.map(step => { const Icon = step.state === 'complete' ? Check : step.state === 'blocked' ? AlertTriangle : Clock3; return <div className={`readiness-step is-${step.state}`} key={step.label}>
      <span className="readiness-icon"><Icon size={17} /></span><div><strong>{step.label}</strong><small>{step.detail}</small></div>
    </div>; })}</div>
    {firstBlocked && <div className="primary-blocker" role="status"><AlertTriangle size={18} /><div><strong>{firstBlocked.detail}</strong><span>{firstBlocked.label === 'Bot' ? 'Start the bot when you are ready.' : firstBlocked.label === 'Strategy' ? 'Open Strategy Lab to inspect the evidence.' : 'Open Settings → Safety & recovery for the next safe action.'}</span></div></div>}
  </section>;
}
