import axios, { AxiosError } from 'axios';

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';

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
  login: (email: string, password: string) =>
    api.post('/auth/login', new URLSearchParams({ username: email, password }), {
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    }),
  register: (email: string, password: string) =>
    api.post('/auth/register', { email, password }),
};

export const portfolioApi = {
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
  start: () => api.post('/bot/start'),
  stop: () => api.post('/bot/stop'),
  emergencyStop: () => api.post('/bot/emergency-stop'),
};

export const settingsApi = {
  getRisk: () => api.get('/settings/risk'),
  updateRisk: (data: Partial<{
    max_position_pct: number;
    stop_loss_pct: number;
    take_profit_pct: number;
    fee_pct: number;
    max_daily_trades: number;
    trading_pair: string;
    prediction_horizon: number;
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
