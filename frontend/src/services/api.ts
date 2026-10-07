import axios, { AxiosError } from 'axios';

const API_URL = (import.meta.env.VITE_API_URL || '/').replace(/\/$/, '');

const api = axios.create({
  baseURL: `${API_URL}/api/v1`,
  headers: {
    'Content-Type': 'application/json',
  },
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem('token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      localStorage.removeItem('token');
      window.location.href = '/login';
    }
    return Promise.reject(error);
  }
);

export default api;

export const authApi = {
  forgotPassword: (email: string) => api.post('/auth/forgot-password', { email }),
  resetPassword: (token: string, password: string) => api.post('/auth/reset-password', { token, password }),
  login: (email: string, password: string) =>
    api.post('/auth/login', new URLSearchParams({ username: email, password }), {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    }),
  register: (email: string, password: string) =>
    api.post('/auth/register', { email, password }),
};

export const portfolioApi = {
  getOrders: () => api.get('/portfolio/orders'),
  getPortfolio: () => api.get('/portfolio/me'),
  getPositions: () => api.get('/portfolio/positions'),
  getTrades: () => api.get('/portfolio/trades'),
  getSignals: () => api.get('/portfolio/signals'),
};

export const marketApi = {
  getPrice: (symbol: string) => api.get(`/market/price/${symbol}`),
  getOHLCV: (symbol: string, timeframe = '1h', limit = 100) =>
    api.get(`/market/ohlcv/${symbol}?timeframe=${timeframe}&limit=${limit}`),
  backtest: (symbol: string, initialCash = 500, feePct = 0.0026) =>
    api.post('/market/backtest', { symbol, initial_cash: initialCash, fee_pct: feePct }),
  getPairs: () => api.get<string[]>('/market/pairs'),
};

export const botApi = {
  getState: () => api.get('/bot/state'),
  getResearchStatus: () => api.get('/bot/research/status'),
  exportResearchMetadata: () => api.get('/bot/research/metadata/export'),
  importResearchMetadata: (payload: unknown) => api.post('/bot/research/metadata/import', payload),
  start: () => api.post('/bot/start'),
  stop: () => api.post('/bot/stop'),
  emergencyStop: () => api.post('/bot/emergency-stop'),
};

export const settingsApi = {
  resumeRisk: () => api.post('/settings/resume-risk?confirm=true'),
  getRisk: () => api.get('/settings/risk'),
  updateRisk: (data: Partial<{
    entry_strategy: 'model' | 'momentum' | 'fast_momentum' | 'auto';
    buy_probability_threshold: number;
    max_invest_per_trade_eur: number;
    risk_per_trade_pct: number;
    discovery_limit: number;
    watchlist_limit: number;
    max_holding_hours: number;
  max_position_pct: number;
    stop_loss_pct: number;
    take_profit_pct: number;
    fee_pct: number;
    max_daily_trades: number;
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

  }>) => api.put('/settings/risk', data),
  resetPaper: () => api.post('/settings/reset-paper?confirm=true'),
  getSafety: () => api.get('/settings/safety'),
  enableLive: () => api.post('/settings/enable-live?confirm=true'),
  disableLive: () => api.post('/settings/disable-live'),
  getExchange: () => api.get<{ connected: boolean; masked_key: string }>('/settings/exchange'),
  saveExchange: (api_key: string, api_secret: string) =>
    api.post('/settings/exchange', { api_key, api_secret }),
  testExchange: () => api.post('/settings/exchange/test'),
};
