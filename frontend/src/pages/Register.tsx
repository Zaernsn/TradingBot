import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { authApi } from '../services/api';

export default function Register() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const navigate = useNavigate();

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await authApi.register(email, password);
      const res = await authApi.login(email, password);
      localStorage.setItem('token', res.data.access_token);
      navigate('/');
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Registration failed');
    }
  };

  return (
    <div className="container" style={{ maxWidth: 400, marginTop: '10vh' }}>
      <div className="card">
        <h2>Create Account</h2>
        {error && <p style={{ color: 'var(--danger)' }}>{error}</p>}
        <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
          <input type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          <input type="password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          <button className="btn-primary" type="submit">Register</button>
        </form>
        <p className="text-muted">Already have an account? <Link to="/login">Login</Link></p>
      </div>
    </div>
  );
}
