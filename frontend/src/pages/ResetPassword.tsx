import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import { authApi } from '../services/api';

export default function ResetPassword() {
  const resetting = useLocation().pathname === '/reset-password';
  const [token] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get('token') || '');
  useEffect(() => {
    if (token) window.history.replaceState(null, '', window.location.pathname);
  }, [token]);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setError(''); setMessage('');
    if (resetting && password !== confirmation) { setError('Passwords do not match.'); return; }
    setBusy(true);
    try {
      const res = resetting ? await authApi.resetPassword(token, password) : await authApi.forgotPassword(email);
      setMessage(res.data.detail);
      if (resetting) { localStorage.removeItem('token'); setDone(true); setPassword(''); setConfirmation(''); }
    } catch (err: any) {
      const detail = err.response?.data?.detail;
      setError(typeof detail === 'string' ? detail : 'Could not complete the request. Check your input and try again.');
    } finally { setBusy(false); }
  }
  return <div className="auth-page"><div className="auth-form-wrap"><div className="card" style={{width: '100%', maxWidth: 480, padding: '2rem'}}>
    <h2>{resetting ? 'Choose a new password' : 'Reset your password'}</h2>
    <p className="text-muted">{resetting ? 'Use at least 12 characters. Resetting signs out existing sessions and stops the bot. Existing live holdings remain on Kraken.' : 'Enter your account email to receive a reset link valid for 30 minutes.'}</p>
    {message && <p role="status" className="text-success">{message}</p>}
    {error && <p role="alert" className="text-danger">{error}</p>}
    {resetting && !token && <p role="alert">Open the link from your reset email. If it expired, request a new one.</p>}
    {!done && <form onSubmit={submit} className="grid" style={{gap: '1rem'}}>
      {resetting ? <><label>New password<input type="password" autoComplete="new-password" required minLength={12} maxLength={72} value={password} onChange={e => setPassword(e.target.value)} /></label>
        <label>Confirm password<input type="password" autoComplete="new-password" required value={confirmation} onChange={e => setConfirmation(e.target.value)} /></label></> :
        <label>Email<input type="email" autoComplete="email" required value={email} onChange={e => setEmail(e.target.value)} /></label>}
      <button className="btn-primary" disabled={busy || (resetting && !token)}>{busy ? 'Please wait…' : resetting ? 'Save new password' : 'Send reset link'}</button>
    </form>}
    <p><Link to="/login">Back to sign in</Link>{resetting && <> · <Link to="/forgot-password">Request another link</Link></>}</p>
  </div></div></div>;
}
