import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Mail, Lock, TrendingUp, ArrowRight, AlertTriangle, Eye, EyeOff, ShieldCheck } from 'lucide-react';
import { authApi } from '../services/api';

export default function Login() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [showPassword, setShowPassword] = useState(false);
  const navigate = useNavigate();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (loading) return;
    setError('');
    setLoading(true);
    try {
      const res = await authApi.login(email, password);
      localStorage.setItem('token', res.data.access_token);
      navigate('/');
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((item: any) => item.msg).join('; ') : !err.response ? 'Cannot reach the backend. Please try again in a moment.' : 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page login-page">
      <div className="auth-hero login-hero">
        <div style={{ maxWidth: '420px' }}>
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp size={32} color="#D4AF37" strokeWidth={2.5} />
            <span style={{ fontFamily: 'var(--font-display)', fontSize: '1.8rem', fontWeight: 700 }}>WACG<span className="login-brand-caption">TRADING WORKSPACE</span></span>
          </div>
          <h1 style={{ fontSize: '3rem', lineHeight: 1.05, marginBottom: '1rem' }}>
            The market moves.<br />
            <span style={{ color: '#D4AF37' }}>Keep your perspective.</span>
          </h1>
          <p style={{ color: 'var(--muted)', fontSize: '1.1rem', lineHeight: 1.6 }}>
            Your crypto portfolio, signals and risk controls in one workspace. Follow core markets and a dedicated pool of 30 memecoin candidates.
          </p>
          <div className="login-market-panel">
            <div className="login-panel-heading"><span>MARKET FOCUS</span><span>01 / 02</span></div>
            <div className="login-market-row"><span>Core crypto</span><strong>BTC · ETH · SOL</strong></div>
            <div className="login-market-row"><span>Memecoin radar</span><strong>30 candidates</strong></div>
            <div className="login-tags"><span>DOGE</span><span>SHIB</span><span>PEPE</span><span>BONK</span><span>WIF</span></div>
            <p>Exchange availability and liquidity checks determine eligible markets.</p>
          </div>
          <div className="login-assurance"><ShieldCheck size={18} /> Paper trading first. Live trading by explicit opt-in.</div>
        </div>
      </div>

      <div className="auth-form-wrap">
        <div className="auth-card" style={{ width: '100%' }}>
          <div className="card" style={{ padding: '2rem' }}>
            <div className="login-eyebrow">WACG / YOUR WORKSPACE</div>
            <h2 style={{ marginBottom: '0.25rem' }}>Welcome back</h2>
            <p className="text-muted" style={{ marginBottom: '1.5rem' }}>Sign in to see your portfolio and market radar.</p>

            {error && (
              <div role="alert" className="flex items-center gap-2 text-danger" style={{ marginBottom: '1rem', padding: '0.75rem', background: 'var(--danger-dim)', borderRadius: 'var(--radius-sm)' }}>
                <AlertTriangle size={18} />
                {error}
              </div>
            )}

            <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
              <label>
                Email
                <div style={{ position: 'relative' }}>
                  <Mail size={16} style={{ position: 'absolute', left: '0.85rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--muted)' }} />
                  <input
                    type="email"
                    name="email"
                    autoComplete="username"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    required
                    style={{ paddingLeft: '2.4rem' }}
                  />
                </div>
              </label>
              <label>
                Password
                <div style={{ position: 'relative' }}>
                  <Lock size={16} style={{ position: 'absolute', left: '0.85rem', top: '50%', transform: 'translateY(-50%)', color: 'var(--muted)' }} />
                  <input
                    type={showPassword ? "text" : "password"}
                    name="password"
                    autoComplete="current-password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    required
                    style={{ paddingLeft: '2.4rem', paddingRight: '3rem' }}
                  />
                  <button className="login-password-toggle" type="button" onClick={() => setShowPassword(!showPassword)} aria-label={showPassword ? 'Hide password' : 'Show password'} aria-pressed={showPassword}>{showPassword ? <EyeOff size={18} /> : <Eye size={18} />}</button>
                </div>
              </label>
              <button className="btn-primary" type="submit" disabled={loading} aria-busy={loading} style={{ marginTop: '0.5rem' }}>
                {loading ? 'Signing in…' : 'Sign in to workspace'}
                <ArrowRight size={18} />
              </button>
            </form>

            <p className="text-muted" style={{ marginTop: '1.25rem', textAlign: 'center', fontSize: '0.9rem' }}>
              <Link to="/forgot-password">Forgot password?</Link><br />
              No account? <Link to="/register" style={{ color: '#D4AF37', fontWeight: 700 }}>Create one</Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
