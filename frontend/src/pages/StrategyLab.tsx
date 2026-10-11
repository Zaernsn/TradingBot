import { useEffect, useState } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import StrategyLearning from '../components/StrategyLearning';
import BacktestPanel from '../components/BacktestPanel';
import { botApi } from '../services/api';
import type { ResearchStatus } from '../types';

export default function StrategyLab() {
  const [research, setResearch] = useState<ResearchStatus | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const load = async () => { setLoading(true); try { setResearch((await botApi.getResearchStatus()).data); setError(''); } catch (err: any) { setError(err.response?.data?.detail || 'Could not load strategy evidence.'); } finally { setLoading(false); } };
  useEffect(() => { void load(); }, []);
  return <div aria-busy={loading}>
    <div className="page-heading"><div><span className="page-eyebrow">RESEARCH & EVIDENCE</span><h2 className="section-title">Strategy Lab</h2><p className="text-muted">Inspect validation, paper evidence, limited-live progress, and historical tests.</p></div><button className="btn-ghost" onClick={load} disabled={loading}><RefreshCw size={16} />Refresh</button></div>
    {error && <div className="safety-banner is-critical" role="alert"><AlertTriangle size={18} />{error}</div>}
    <div className="grid grid-12"><StrategyLearning research={research} /><div className="span-12"><BacktestPanel /></div></div>
  </div>;
}
