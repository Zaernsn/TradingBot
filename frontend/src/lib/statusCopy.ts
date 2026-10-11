import type { EntryDecision } from '../types';

export type StatusSeverity = 'info' | 'waiting' | 'action' | 'blocked' | 'critical';

type StatusCopy = {
  title: string;
  explanation: string;
  action: string;
  severity: StatusSeverity;
};

const STATUS: Record<string, StatusCopy> = {
  ready: { title: 'Waiting for a buy signal', explanation: 'The market passed the current entry checks.', action: 'No action needed.', severity: 'info' },
  waiting_candle: { title: 'Waiting for the next candle', explanation: 'Signals only use completed market candles.', action: 'Check again after the strategy’s next completed candle.', severity: 'waiting' },
  training: { title: 'Model is retraining', explanation: 'Fresh evidence is being evaluated before another entry.', action: 'Wait for training to finish.', severity: 'waiting' },
  blocked: { title: 'Model recovery is blocked', explanation: 'The model could not recover safely with the available data.', action: 'Review model diagnostics in Markets.', severity: 'blocked' },
  drift: { title: 'Market behavior changed', explanation: 'Recent inputs differ too much from the model training data.', action: 'Wait for a qualified retrain.', severity: 'blocked' },
  validation_failed: { title: 'Model validation failed', explanation: 'The latest model did not beat its validation baseline.', action: 'Keep this market in observation.', severity: 'blocked' },
  model_unavailable: { title: 'No qualified model', explanation: 'A safe model is not currently available for this market.', action: 'Wait for enough fresh evidence.', severity: 'blocked' },
  history_unavailable: { title: 'Not enough market history', explanation: 'The bot cannot evaluate this market with sufficient completed data.', action: 'Wait for more candles.', severity: 'waiting' },
  market_unavailable: { title: 'Market data unavailable', explanation: 'A fresh quote or active EUR market is missing.', action: 'Check the connection and wait for fresh data.', severity: 'blocked' },
  risk_halt: { title: 'New buys paused by risk controls', explanation: 'A portfolio safety limit is active. Protective exits can continue.', action: 'Stop the bot and review Safety & recovery.', severity: 'critical' },
  position_cap: { title: 'Position limit reached', explanation: 'All configured position slots are currently in use.', action: 'Wait for a position to close or review the limit.', severity: 'waiting' },
  daily_limit: { title: 'Daily trade limit reached', explanation: 'The configured entry allowance for today is exhausted.', action: 'Wait for the limit window to reset.', severity: 'waiting' },
  allocation: { title: 'Exposure limit reached', explanation: 'The remaining portfolio allocation is too small for another entry.', action: 'Review the effective limit in Settings.', severity: 'waiting' },
  fee_reserve: { title: 'Not enough cash after costs', explanation: 'Fees and slippage reserve leave too little for a valid order.', action: 'Keep more cash available or reduce exposure.', severity: 'waiting' },
  order_size: { title: 'Order would be too small', explanation: 'The estimated order is below the exchange minimum.', action: 'Review wallet size and effective limits.', severity: 'waiting' },
  liquidity: { title: 'Liquidity check failed', explanation: 'Spread or available market depth is outside the configured limit.', action: 'Wait for better market conditions.', severity: 'waiting' },
  execution_error: { title: 'Order execution needs attention', explanation: 'The latest order attempt did not complete normally.', action: 'Review Safety & recovery before another entry.', severity: 'critical' },
  selection_unavailable: { title: 'No strategy selected', explanation: 'The automatic selector is staying in cash for this market regime.', action: 'No action needed unless this persists unexpectedly.', severity: 'info' },
};

export function statusCopy(code?: string, fallback?: string): StatusCopy {
  if (code && STATUS[code]) return STATUS[code];
  return {
    title: fallback || 'Waiting for an entry check',
    explanation: 'The bot has not provided a current plain-language result yet.',
    action: 'Wait for the next evaluation.',
    severity: 'waiting',
  };
}

export function decisionCopy(decision?: EntryDecision): StatusCopy {
  const code = decision?.code === 'waiting_candle' ? decision.model_status || decision.code : decision?.code;
  const copy = statusCopy(code, decision?.message);
  return decision?.message ? { ...copy, explanation: decision.message } : copy;
}

export function humanizeCode(value: string): string {
  return value.replace(/_/g, ' ').replace(/\b\w/g, character => character.toUpperCase());
}
