export interface Portfolio {
  id: number;
  currency: string;
  cash: number;
  equity: number;
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

export interface BotState {
  id: number;
  is_running: boolean;
  last_run_at: string | null;
  last_error: string | null;
  health: string;
  updated_at: string;
}

export interface RiskConfig {
  id: number;
  max_position_pct: number;
  stop_loss_pct: number;
  take_profit_pct: number;
  fee_pct: number;
  max_daily_trades: number;
  trading_pair: string;
  prediction_horizon: number;
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
