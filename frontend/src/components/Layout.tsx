import { Outlet, Link, useNavigate } from 'react-router-dom';

export default function Layout() {
  const navigate = useNavigate();

  const logout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

  return (
    <div className="container">
      <nav style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
        <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
          <h1 style={{ margin: 0 }}>AI Trading Bot</h1>
          <Link to="/">Dashboard</Link>
          <Link to="/settings">Settings</Link>
        </div>
        <button className="btn-danger" onClick={logout}>Logout</button>
      </nav>
      <Outlet />
    </div>
  );
}
