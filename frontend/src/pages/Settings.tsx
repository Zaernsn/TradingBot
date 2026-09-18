import { useEffect, useState } from 'react';
import {
  Shield,
  TrendingUp,
  RotateCcw,
  Key,
  Activity,
  AlertTriangle,
  Play,
  Save,
  TestTube,
} from 'lucide-react';
import { RiskConfig, BacktestResult } from '../types';
import { settingsApi, marketApi } from '../services/api';

export default function Settings() {
  const [risk, setRisk] = useState<RiskConfig | null>(null);
  const [safety, setSafety] = useState<any>(null);
  const [exchange, setExchange] = useState<{ connected: boolean; masked_key: string } | null>(null);
  const [pairs, setPairs] = useState<string[]>([]);
  const [krakenKey, setKrakenKey] = useState('');
  const [krakenSecret, setKrakenSecret] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [backtestSymbol, setBacktestSymbol] = useState('BTC/EUR');
  const [backtestLoading, setBacktestLoading] = useState(false);
  const [backtestResult, setBacktestResult] = useState<BacktestResult | null>(null);

  useEffect(() => {
    load();
  }, []);

  const load = async () => {
    try {
      const [riskRes, safetyRes, pairsRes, exchangeRes] = await Promise.all([
        settingsApi.getRisk(),
        settingsApi.getSafety(),
        marketApi.getPairs(),
        settingsApi.getExchange(),
      ]);
      setRisk(riskRes.data);
      setSafety(safetyRes.data);
      setPairs(pairsRes.data);
      setExchange(exchangeRes.data);
      setError('');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to load settings');
    }
  };

  const updateRisk = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!risk) return;
    try {
      await settingsApi.updateRisk({
        max_position_pct: risk.max_position_pct,
        stop_loss_pct: risk.stop_loss_pct,
        take_profit_pct: risk.take_profit_pct,
        fee_pct: risk.fee_pct,
        max_daily_trades: risk.max_daily_trades,
        trading_pair: risk.trading_pair,
        prediction_horizon: risk.prediction_horizon,
      });
      setMessage('Risk settings saved');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to save settings');
    }
  };

  const resetPaper = async () => {
    if (!confirm('WARNING: This will reset your paper portfolio to €500 and delete all paper-trading history. Continue?')) return;
    try {
      await settingsApi.resetPaper();
      setMessage('Paper portfolio reset');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Reset failed');
    }
  };

  const enableLive = async () => {
    if (!confirm('WARNING: Live trading uses real money and can result in losses. Only proceed if you understand the risks.')) return;
    try {
      await settingsApi.enableLive();
      setMessage('Live trading enabled');
      load();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Live mode not enabled');
    }
  };

  const disableLive = async () => {
    try {
      await settingsApi.disableLive();
      setMessage('Switched to paper mode');
      load();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to disable live mode');
    }
  };

  const runBacktest = async () => {
    setBacktestLoading(true);
    try {
      const res = await marketApi.backtest(backtestSymbol);
      setBacktestResult(res.data);
      setError('');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Backtest failed');
    } finally {
      setBacktestLoading(false);
    }
  };

  const saveKraken = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await settingsApi.saveExchange(krakenKey, krakenSecret);
      setKrakenKey('');
      setKrakenSecret('');
      setMessage('Kraken credentials saved');
      load();
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to save credentials');
    }
  };

  const testKraken = async () => {
    try {
      const res = await settingsApi.testExchange();
      setMessage(res.data.detail);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Connection test failed');
    }
  };

  return (
    <div>
      <h2 className="section-title">Settings</h2>

      {message && (
        <div className="card mb-2" style={{ borderColor: 'rgba(16,185,129,0.4)', background: 'var(--success-dim)' }}>
          <div className="flex items-center gap-2 text-success">
            <Activity size={18} />
            {message}
          </div>
        </div>
      )}

      {error && (
        <div className="card mb-2" style={{ borderColor: 'rgba(239,68,68,0.4)', background: 'var(--danger-dim)' }}>
          <div className="flex items-center gap-2 text-danger">
            <AlertTriangle size={18} />
            {error}
          </div>
        </div>
      )}

      <div className="grid grid-12 mb-3">
        {/* Risk Parameters */}
        <div className="card span-6">
          <div className="card-header">
            <div className="card-title">
              <Shield className="card-title-icon" size={18} />
              Risk Parameters
            </div>
          </div>
          {risk && (
            <form onSubmit={updateRisk} className="grid" style={{ gap: '1rem', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
              <label>
                Trading Pair
                <select value={risk.trading_pair} onChange={(e) => setRisk({ ...risk, trading_pair: e.target.value })}>
                  {pairs.map((pair) => (
                    <option key={pair} value={pair}>{pair}</option>
                  ))}
                </select>
              </label>
              <label>
                Max Position (%)
                <input type="number" step="0.01" value={risk.max_position_pct} onChange={(e) => setRisk({ ...risk, max_position_pct: parseFloat(e.target.value) })} />
              </label>
              <label>
                Stop Loss (%)
                <input type="number" step="0.01" value={risk.stop_loss_pct} onChange={(e) => setRisk({ ...risk, stop_loss_pct: parseFloat(e.target.value) })} />
              </label>
              <label>
                Take Profit (%)
                <input type="number" step="0.01" value={risk.take_profit_pct} onChange={(e) => setRisk({ ...risk, take_profit_pct: parseFloat(e.target.value) })} />
              </label>
              <label>
                Fee (%)
                <input type="number" step="0.0001" value={risk.fee_pct} onChange={(e) => setRisk({ ...risk, fee_pct: parseFloat(e.target.value) })} />
              </label>
              <label>
                Max Daily Trades
                <input type="number" value={risk.max_daily_trades} onChange={(e) => setRisk({ ...risk, max_daily_trades: parseInt(e.target.value) })} />
              </label>
              <label>
                Prediction Horizon
                <input type="number" value={risk.prediction_horizon} onChange={(e) => setRisk({ ...risk, prediction_horizon: parseInt(e.target.value) })} />
              </label>
              <div style={{ gridColumn: '1 / -1' }}>
                <button className="btn-primary" type="submit">
                  <Save size={16} />
                  Save Risk Settings
                </button>
              </div>
            </form>
          )}
        </div>

        {/* Kraken Connection */}
        <div className="card span-6">
          <div className="card-header">
            <div className="card-title">
              <Key className="card-title-icon" size={18} />
              Kraken Connection
            </div>
            <span className={`badge ${exchange?.connected ? 'badge-success' : 'badge-warning'}`}>
              {exchange?.connected ? 'Connected' : 'Not Connected'}
            </span>
          </div>
          <p className="text-muted" style={{ fontSize: '0.9rem', marginBottom: '1rem' }}>
            Stored key: <span className="mono">{exchange?.masked_key || '****'}</span>
          </p>
          <form onSubmit={saveKraken} className="grid" style={{ gap: '1rem', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
            <label>
              API Key
              <input type="password" value={krakenKey} onChange={(e) => setKrakenKey(e.target.value)} placeholder="Enter API key" />
            </label>
            <label>
              API Secret
              <input type="password" value={krakenSecret} onChange={(e) => setKrakenSecret(e.target.value)} placeholder="Enter API secret" />
            </label>
            <div style={{ gridColumn: '1 / -1', display: 'flex', gap: '0.75rem' }}>
              <button className="btn-primary" type="submit">
                <Save size={16} />
                Save Credentials
              </button>
              <button className="btn-ghost" type="button" onClick={testKraken} disabled={!exchange?.connected}>
                <TestTube size={16} />
                Test Connection
              </button>
            </div>
          </form>
        </div>

        {/* Backtest */}
        <div className="card span-6">
          <div className="card-header">
            <div className="card-title">
              <TrendingUp className="card-title-icon" size={18} />
              Backtest
            </div>
          </div>
          <div className="flex gap-2 mb-2">
            <input value={backtestSymbol} onChange={(e) => setBacktestSymbol(e.target.value)} placeholder="Symbol" style={{ maxWidth: '160px' }} />
            <button className="btn-primary" onClick={runBacktest} disabled={backtestLoading}>
              <Play size={16} />
              {backtestLoading ? 'Running...' : 'Run Backtest'}
            </button>
          </div>
          {backtestResult && (
            <div className="grid" style={{ gap: '0.75rem', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))' }}>
              <div className="card" style={{ padding: '0.75rem' }}>
                <div className="metric-label">Initial</div>
                <div className="mono" style={{ fontSize: '1.1rem' }}>€{backtestResult.initial_cash.toFixed(2)}</div>
              </div>
              <div className="card" style={{ padding: '0.75rem' }}>
                <div className="metric-label">Final</div>
                <div className="mono" style={{ fontSize: '1.1rem' }}>€{backtestResult.final_equity.toFixed(2)}</div>
              </div>
              <div className="card" style={{ padding: '0.75rem' }}>
                <div className="metric-label">Return</div>
                <div className={`mono ${backtestResult.total_return_pct >= 0 ? 'text-success' : 'text-danger'}`} style={{ fontSize: '1.1rem' }}>
                  {(backtestResult.total_return_pct * 100).toFixed(2)}%
                </div>
              </div>
              <div className="card" style={{ padding: '0.75rem' }}>
                <div className="metric-label">Trades</div>
                <div className="mono" style={{ fontSize: '1.1rem' }}>{backtestResult.num_trades}</div>
              </div>
              <div className="card" style={{ padding: '0.75rem' }}>
                <div className="metric-label">Win Rate</div>
                <div className="mono" style={{ fontSize: '1.1rem' }}>{(backtestResult.win_rate * 100).toFixed(1)}%</div>
              </div>
              <div className="card" style={{ padding: '0.75rem' }}>
                <div className="metric-label">Max DD</div>
                <div className="mono text-danger" style={{ fontSize: '1.1rem' }}>{(backtestResult.max_drawdown_pct * 100).toFixed(2)}%</div>
              </div>
            </div>
          )}
        </div>

        {/* Live Trading Safety */}
        <div className="card span-6">
          <div className="card-header">
            <div className="card-title">
              <Activity className="card-title-icon" size={18} />
              Live Trading Safety
            </div>
          </div>
          <div className="grid" style={{ gap: '0.75rem', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', marginBottom: '1rem' }}>
            <div className="card" style={{ padding: '0.75rem' }}>
              <div className="metric-label">Environment</div>
              <div className={`badge ${safety?.enable_live_trading_env ? 'badge-success' : 'badge-warning'}`}>
                {safety?.enable_live_trading_env ? 'Enabled' : 'Disabled'}
              </div>
            </div>
            <div className="card" style={{ padding: '0.75rem' }}>
              <div className="metric-label">Credentials</div>
              <div className={`badge ${safety?.api_credentials_present ? 'badge-success' : 'badge-danger'}`}>
                {safety?.api_credentials_present ? 'Present' : 'Missing'}
              </div>
            </div>
          </div>
          <div className="flex gap-2">
            <button className="btn-success" onClick={enableLive} disabled={!safety?.live_possible}>
              <Play size={16} />
              Enable Live Trading
            </button>
            <button className="btn-warning" onClick={disableLive}>
              <RotateCcw size={16} />
              Switch to Paper
            </button>
          </div>
          <p className="text-muted mt-1" style={{ fontSize: '0.82rem' }}>
            Live trading requires the server env flag, valid API credentials, and your explicit confirmation. Withdrawal permissions are rejected.
          </p>
        </div>
      </div>

      {/* Paper Portfolio Reset */}
      <div className="card">
        <div className="card-header">
          <div className="card-title">
            <RotateCcw className="card-title-icon" size={18} />
            Paper Portfolio
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button className="btn-danger" onClick={resetPaper}>
            <RotateCcw size={16} />
            Reset to €500
          </button>
          <span className="text-muted" style={{ fontSize: '0.85rem' }}>Deletes all paper-trading history. Cannot be undone.</span>
        </div>
      </div>
    </div>
  );
}
