import { useEffect, useState } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import StrategyLearning from '../components/StrategyLearning';
import ExecutionCosts from '../components/ExecutionCosts';
import BacktestPanel from '../components/BacktestPanel';
import { botApi } from '../services/api';
import type { ResearchStatus, ExecutionCostsReport } from '../types';

export default function StrategyLab() {
  const [research, setResearch] = useState<ResearchStatus | null>(null);
  const [costs, setCosts] = useState<ExecutionCostsReport | null>(null);
  const [costError, setCostError] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const load = async () => {
    setLoading(true);
    const [researchResult, costResult] = await Promise.allSettled([botApi.getResearchStatus(), botApi.getExecutionCosts()]);
    if (researchResult.status === 'fulfilled') { setResearch(researchResult.value.data); setError(''); }
    else { setError(researchResult.reason.response?.data?.detail || 'Could not load strategy evidence.'); }
    if (costResult.status === 'fulfilled') { setCosts(costResult.value.data); setCostError(''); }
    else { setCostError('Cost evidence is unavailable. Strategy evidence can still be viewed.'); }
    setLoading(false);
  };
  useEffect(() => { void load(); }, []);
  return <div aria-busy={loading}>
    <div className="page-heading"><div><span className="page-eyebrow">RESEARCH & EVIDENCE</span><h2 className="section-title">Strategy Lab</h2><p className="text-muted">Inspect validation, paper evidence, limited-live progress, and historical tests.</p></div><button className="btn-ghost" onClick={load} disabled={loading}><RefreshCw size={16} />Refresh</button></div>
    {error && <div className="safety-banner is-critical" role="alert"><AlertTriangle size={18} />{error}</div>}
    <div className="grid grid-12"><StrategyLearning research={research} /><ExecutionCosts report={costs} error={costError} /><div className="span-12"><BacktestPanel /></div></div>
  </div>;
}
