import { useEffect, useState } from 'react';
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
    await settingsApi.disableLive();
    setMessage('Switched to paper mode');
    load();
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
      <h2>Settings</h2>
      {message && <p style={{ color: 'var(--success)' }}>{message}</p>}
      {error && <p style={{ color: 'var(--danger)' }}>{error}</p>}

      <div className="card">
        <h3>Risk Parameters</h3>
        {risk && (
          <form onSubmit={updateRisk} style={{ display: 'grid', gap: '1rem', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
            <label>
              Trading Pair
              <select value={risk.trading_pair} onChange={(e) => setRisk({ ...risk, trading_pair: e.target.value })}>
                {pairs.map((pair) => (
                  <option key={pair} value={pair}>{pair}</option>
                ))}
              </select>
            </label>
            <label>
              Max Position (% of equity)
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
              Prediction Horizon (candles)
              <input type="number" value={risk.prediction_horizon} onChange={(e) => setRisk({ ...risk, prediction_horizon: parseInt(e.target.value) })} />
            </label>
            <div style={{ gridColumn: '1 / -1' }}>
              <button className="btn-primary" type="submit">Save Risk Settings</button>
            </div>
          </form>
        )}
      </div>

      <div className="card">
        <h3>Kraken Connection</h3>
        <p className="text-muted">Status: {exchange?.connected ? `Connected (${exchange.masked_key})` : 'Not connected'}</p>
        <form onSubmit={saveKraken} style={{ display: 'grid', gap: '1rem', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))' }}>
          <label>
            API Key
            <input type="password" value={krakenKey} onChange={(e) => setKrakenKey(e.target.value)} placeholder="Enter API key" />
          </label>
          <label>
            API Secret
            <input type="password" value={krakenSecret} onChange={(e) => setKrakenSecret(e.target.value)} placeholder="Enter API secret" />
          </label>
          <div style={{ gridColumn: '1 / -1', display: 'flex', gap: '1rem' }}>
            <button className="btn-primary" type="submit">Save Credentials</button>
            <button className="btn-primary" type="button" onClick={testKraken} disabled={!exchange?.connected}>Test Connection</button>
          </div>
        </form>
      </div>

      <div className="card">
        <h3>Backtest</h3>
        <div style={{ display: 'flex', gap: '1rem', marginBottom: '1rem' }}>
          <input value={backtestSymbol} onChange={(e) => setBacktestSymbol(e.target.value)} placeholder="Symbol" />
          <button className="btn-primary" onClick={runBacktest} disabled={backtestLoading}>
            {backtestLoading ? 'Running...' : 'Run Backtest'}
          </button>
        </div>
        {backtestResult && (
          <div className="grid grid-4">
            <div>Initial: €{backtestResult.initial_cash.toFixed(2)}</div>
            <div>Final: €{backtestResult.final_equity.toFixed(2)}</div>
            <div>Return: {(backtestResult.total_return_pct * 100).toFixed(2)}%</div>
            <div>Trades: {backtestResult.num_trades}</div>
            <div>Win Rate: {(backtestResult.win_rate * 100).toFixed(1)}%</div>
            <div>Max DD: {(backtestResult.max_drawdown_pct * 100).toFixed(2)}%</div>
            <div>Sharpe: {backtestResult.sharpe_ratio.toFixed(2)}</div>
          </div>
        )}
      </div>

      <div className="card">
        <h3>Paper Portfolio</h3>
        <button className="btn-danger" onClick={resetPaper}>Reset Paper Portfolio to €500</button>
        <p className="text-muted">This deletes all paper-trading history and cannot be undone.</p>
      </div>

      <div className="card">
        <h3>Live Trading Safety</h3>
        <p className="text-muted">Live trading status: {safety?.enable_live_trading_env ? 'Enabled in environment' : 'Disabled in environment'}</p>
        <p className="text-muted">API credentials: {safety?.api_credentials_present ? 'Present' : 'Missing'}</p>
        <div style={{ display: 'flex', gap: '1rem' }}>
          <button className="btn-success" onClick={enableLive} disabled={!safety?.live_possible}>
            Enable Live Trading
          </button>
          <button className="btn-warning" onClick={disableLive}>Switch to Paper</button>
        </div>
        <p className="text-muted" style={{ marginTop: '0.5rem' }}>
          Live trading requires the server env flag, valid API credentials, and your explicit confirmation.
          Withdrawal permissions are rejected.
        </p>
      </div>
    </div>
  );
}
