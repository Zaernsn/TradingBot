import { Outlet, Link, useNavigate, useLocation } from 'react-router-dom';
import { LayoutDashboard, Settings, LogOut, TrendingUp } from 'lucide-react';

export default function Layout() {
  const navigate = useNavigate();
  const location = useLocation();

  const logout = () => {
    localStorage.removeItem('token');
    navigate('/login');
  };

  const isActive = (path: string) => location.pathname === path;

  return (
    <div className="app">
      <nav className="nav">
        <div className="nav-inner">
          <Link to="/" className="nav-brand">
            <TrendingUp className="nav-brand-icon" size={24} strokeWidth={2.5} />
            <span>AI Trading Bot</span>
          </Link>
          <div style={{ display: 'flex', alignItems: 'center', gap: '1.5rem' }}>
            <div className="nav-links">
              <Link to="/" className={`nav-link ${isActive('/') ? 'active' : ''}`}>
                <LayoutDashboard size={16} />
                Dashboard
              </Link>
              <Link to="/settings" className={`nav-link ${isActive('/settings') ? 'active' : ''}`}>
                <Settings size={16} />
                Settings
              </Link>
            </div>
            <button className="btn-danger" onClick={logout}>
              <LogOut size={16} />
              Logout
            </button>
          </div>
        </div>
      </nav>
      <main className="container">
        <Outlet />
      </main>
    </div>
  );
}
