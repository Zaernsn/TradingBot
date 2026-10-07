export interface Portfolio {
  id: number;
  currency: string;
  cash: number;
  equity: number;
  initial_equity: number;
  peak_equity: number;
  risk_halted: boolean;
  mode: 'PAPER' | 'LIVE_DISABLED' | 'LIVE';
  updated_at: string;
}

export interface Position {
  id: number;
  symbol: string;
  quantity: number;
  avg_entry_price: number;
  current_price: number;
  unrealized_pnl: number;
  realized_pnl: number;
  opened_at: string;
  updated_at: string;
}

export interface Trade {
  id: number;
  symbol: string;
  side: 'BUY' | 'SELL';
  quantity: number;
  price: number;
  fee: number;
  slippage: number;
  total_cost: number;
  pnl: number | null;
  mode: string;
  reason: string | null;
  created_at: string;
}

export interface Signal {
  id: number;
  symbol: string;
  model: string;
  action: 'BUY' | 'SELL' | 'HOLD';
  probability: number;
  confidence: number;
  explanation: string | null;
  created_at: string;
}

export interface EntryDecision {
  code: string;
  message: string;
  checked_at: string;
  model_status?: string;
  signal?: string;
  buy_candidate?: boolean;
  market_note?: string;
  eligibility?: { eligible: boolean; checked_at: string; code?: string; message?: string };
  diagnostics?: {
    feature_schema?: string;
    candidate_comparison?: { feature_schema: string; brier_score?: number; baseline_brier?: number; qualified: boolean; drift_detected: boolean; reason?: string }[];
    trained_at?: string | null;
    training_start?: string | null;
    training_end?: string | null;
    fit_window_end?: string | null;
    history_rows?: number;
    latest_candle?: string | null;
    validation?: { brier_score?: number; baseline_brier?: number; validation_rows?: number };
    drift_features?: { feature: string; value: number; training_mean: number; training_scale: number; deviation: number }[];
    recovery?: { state: string; retry_after?: string; attempted_at?: string; selection?: string };
  };
}

export interface BotState {
  entry_decisions?: Record<string, EntryDecision>;
  blocker_summary?: Record<string, number>;
  discovery_stats?: { discovered?: number; quoted?: number; market_eligible?: number; retained?: number; history_eligible?: number; model_qualified?: number; buy_candidates?: number; quote_requests?: number; quote_failures?: number; scan_seconds?: number; cycle_seconds?: number; watchlist_churn?: number; checked_at?: string; coverage?: string } | null;
  id: number;
  is_running: boolean;
  last_run_at: string | null;
  last_error: string | null;
  health: string;
  watchlist: string[] | null;
  watchlist_updated_at: string | null;
  watchlist_refresh_seconds: number;
  memecoin_watchlist_count: number;
  memecoin_watchlist_target: number;
  open_slots: number;
  updated_at: string;
}

export interface ResearchCandidate {
  candidate_id: string;
  family: string;
  status: string;
  tested_at: string;
  shadow_days: number;
  shadow_days_required: number;
  shadow_closed_trades: number;
  shadow_trades_required: number;
  failed_checks: string[];
  canary?: { closed_round_trips?: number; realized_pnl?: number; suspension_reason?: string } | null;
}

export interface ResearchStatus {
  counts: Record<string, number>;
  candidates: ResearchCandidate[];
  live_candidate?: ResearchCandidate | null;
  verified_taker_fee_pct?: number | null;
  verified_taker_fee_at?: string | null;
  watchlist_age_seconds?: number | null;
}

export interface RiskConfig {
  entry_strategy: 'model' | 'momentum' | 'fast_momentum' | 'auto';
  buy_probability_threshold: number;
  discovery_limit: number;
  watchlist_limit: number;
  risk_per_trade_pct: number;
  max_holding_hours: number;
  id: number;
  max_invest_per_trade_eur: number;
  max_position_pct: number;
  stop_loss_pct: number;
  take_profit_pct: number;
  fee_pct: number;
  verified_taker_fee_pct?: number | null;
  verified_taker_fee_at?: string | null;
  max_daily_trades: number;
  trading_pair?: string | null;
  max_open_positions: number;
  allocation_mode: "equal";
  prediction_horizon: number;
    max_drawdown_pct: number;
    max_total_exposure_pct: number;
    max_correlated_exposure_pct: number;
    correlation_threshold: number;
    slippage_pct: number;
    memecoins_enabled: boolean;
    memecoin_max_position_pct: number;
    memecoin_max_exposure_pct: number;
    memecoin_max_spread_pct: number;
    memecoin_min_daily_volume_eur: number;

  updated_at: string;
}

export interface BacktestResult {
  symbol: string;
  initial_cash: number;
  final_equity: number;
  total_return_pct: number;
  num_trades: number;
  win_rate: number;
  max_drawdown_pct: number;
  sharpe_ratio: number;
  expectancy: number;
  total_fees: number;
  evaluated_bars: number;
  benchmarks: Record<string, number | null>;
  warnings: string[];
  trades: Array<{
    timestamp: string;
    side: string;
    quantity: number;
    price: number;
    pnl: number | null;
  }>;
}

export interface OHLCV {
  timestamp: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}
