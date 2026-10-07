import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Mail, Lock, TrendingUp, ArrowRight, AlertTriangle } from 'lucide-react';
import { authApi } from '../services/api';

export default function Register() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (loading) return;
    setError('');
    setLoading(true);
    try {
      await authApi.register(email, password);
      const res = await authApi.login(email, password);
      localStorage.setItem('token', res.data.access_token);
      navigate('/');
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : Array.isArray(detail) ? detail.map((item: any) => item.msg).join('; ') : !err.response ? 'Cannot reach the backend. Check that Docker reports the backend as healthy.' : 'Registration failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="auth-page">
      <div className="auth-hero">
        <div style={{ maxWidth: '420px' }}>
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp size={32} color="#D4AF37" strokeWidth={2.5} />
            <span style={{ fontFamily: 'var(--font-display)', fontSize: '1.8rem', fontWeight: 700 }}>AI Trading Bot</span>
          </div>
          <h1 style={{ fontSize: '3rem', lineHeight: 1.05, marginBottom: '1rem' }}>
            Start trading<br />
            <span style={{ color: '#D4AF37' }}>with confidence.</span>
          </h1>
          <p style={{ color: 'var(--muted)', fontSize: '1.1rem', lineHeight: 1.6 }}>
            Paper trading is enabled by default. Connect your Kraken API keys only when you are ready for live mode.
          </p>
        </div>
      </div>

      <div className="auth-form-wrap">
        <div className="auth-card" style={{ width: '100%' }}>
          <div className="card" style={{ padding: '2rem' }}>
            <h2 style={{ marginBottom: '0.25rem' }}>Create account</h2>
            <p className="text-muted" style={{ marginBottom: '1.5rem' }}>Set up your account to access the trading dashboard.</p>

            {error && (
              <div className="flex items-center gap-2 text-danger" style={{ marginBottom: '1rem', padding: '0.75rem', background: 'var(--danger-dim)', borderRadius: 'var(--radius-sm)' }}>
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
                    type="password"
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="••••••••"
                    required
                    style={{ paddingLeft: '2.4rem' }}
                  />
                </div>
              </label>
              <button className="btn-primary" type="submit" disabled={loading} aria-busy={loading} style={{ marginTop: '0.5rem' }}>
                {loading ? 'Creating account…' : 'Create Account'}
                <ArrowRight size={18} />
              </button>
            </form>

            <p className="text-muted" style={{ marginTop: '1.25rem', textAlign: 'center', fontSize: '0.9rem' }}>
              Already have an account? <Link to="/login" style={{ color: '#D4AF37', fontWeight: 700 }}>Sign in</Link>
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
