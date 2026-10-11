import { AlertTriangle, X } from 'lucide-react';

export default function EmergencyStopDialog({ open, busy, onCancel, onConfirm }: { open: boolean; busy: boolean; onCancel: () => void; onConfirm: () => void }) {
  if (!open) return null;
  return <div className="dialog-backdrop" role="presentation" onMouseDown={event => { if (event.target === event.currentTarget && !busy) onCancel(); }}>
    <div className="dialog-card" role="alertdialog" aria-modal="true" aria-labelledby="emergency-title" aria-describedby="emergency-description">
      <button className="dialog-close" onClick={onCancel} disabled={busy} aria-label="Close"><X size={18} /></button>
      <span className="dialog-danger-icon"><AlertTriangle size={24} /></span>
      <h2 id="emergency-title">Emergency stop the bot?</h2>
      <p id="emergency-description">This stops new orders and starts reconciliation of pending orders. It does not sell existing holdings or switch them to Paper.</p>
      <div className="dialog-actions"><button className="btn-ghost" onClick={onCancel} disabled={busy}>Cancel</button><button className="btn-danger" onClick={onConfirm} disabled={busy} aria-busy={busy}>{busy ? 'Stopping…' : 'Emergency stop'}</button></div>
    </div>
  </div>;
}
