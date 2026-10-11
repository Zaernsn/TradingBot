import type { RiskConfig } from '../types';

export type RiskProfile = 'paper' | 'cautious' | 'experimental';

export const PROFILE_LABELS: Record<RiskProfile, { title: string; risk: string; description: string }> = {
  paper: { title: 'Learn in Paper', risk: 'No real orders', description: 'Observe decisions and validate changes without using real funds.' },
  cautious: { title: 'Cautious Live', risk: 'Lower exposure', description: 'Core markets, two positions, and a large cash reserve.' },
  experimental: { title: 'Experimental', risk: 'High risk', description: 'Automatic research and broader markets. Use Paper first.' },
};

export function applyProfile(risk: RiskConfig, profile: RiskProfile): RiskConfig {
  if (profile === 'cautious') return {
    ...risk, entry_strategy: 'momentum', buy_probability_threshold: .55, max_open_positions: 2,
    max_invest_per_trade_eur: 20, max_daily_trades: 4, max_position_pct: .20,
    memecoin_max_position_pct: .10, max_total_exposure_pct: .40, memecoin_max_exposure_pct: .20,
    max_correlated_exposure_pct: .30, correlation_threshold: .70, stop_loss_pct: .04,
    take_profit_pct: .08, max_drawdown_pct: .08, memecoins_enabled: false,
    memecoin_max_spread_pct: .002, memecoin_min_daily_volume_eur: 250000,
    prediction_horizon: 10, risk_per_trade_pct: .01, max_holding_hours: 72,
    discovery_limit: 60, watchlist_limit: 10,
  };
  if (profile === 'experimental') return {
    ...risk, entry_strategy: 'auto', buy_probability_threshold: .40, max_open_positions: 3,
    max_invest_per_trade_eur: 25, max_daily_trades: 15, max_position_pct: .30,
    memecoin_max_position_pct: .25, max_total_exposure_pct: .75, memecoin_max_exposure_pct: .50,
    max_correlated_exposure_pct: .60, correlation_threshold: .70, stop_loss_pct: .035,
    take_profit_pct: .10, max_drawdown_pct: .15, memecoins_enabled: true,
    memecoin_max_spread_pct: .005, memecoin_min_daily_volume_eur: 75000,
    prediction_horizon: 10, risk_per_trade_pct: .03, max_holding_hours: 18,
    discovery_limit: 80, watchlist_limit: 30,
  };
  return { ...risk };
}

export function riskPreview(risk: RiskConfig, equity: number, cash = equity) {
  const byPosition = Math.max(0, equity * risk.max_position_pct);
  const configuredTradeCap = risk.max_invest_per_trade_eur > 0 ? risk.max_invest_per_trade_eur : Infinity;
  const totalExposure = Math.max(0, equity * risk.max_total_exposure_pct);
  const feeReserve = Math.max(0, risk.fee_pct + risk.slippage_pct);
  const cashAfterReserve = Math.max(0, cash / (1 + feeReserve));
  const effectiveOrder = Math.min(byPosition, configuredTradeCap, totalExposure, cashAfterReserve);
  const plannedLoss = effectiveOrder * risk.stop_loss_pct;
  return { byPosition, configuredTradeCap, totalExposure, cashAfterReserve, effectiveOrder, plannedLoss, reserve: Math.max(0, equity - totalExposure) };
}

const RISK_KEYS: Array<keyof RiskConfig> = [
  'max_invest_per_trade_eur', 'max_open_positions', 'max_daily_trades', 'max_position_pct',
  'max_total_exposure_pct', 'max_correlated_exposure_pct', 'max_drawdown_pct',
  'memecoin_max_position_pct', 'memecoin_max_exposure_pct', 'memecoin_max_spread_pct',
];

export function changedRiskFields(saved: RiskConfig, draft: RiskConfig) {
  return (Object.keys(draft) as Array<keyof RiskConfig>).filter(key => JSON.stringify(saved[key]) !== JSON.stringify(draft[key]));
}

export function increasesRisk(saved: RiskConfig, draft: RiskConfig): boolean {
  return RISK_KEYS.some(key => Number(draft[key]) > Number(saved[key])) || (!saved.memecoins_enabled && draft.memecoins_enabled);
}
