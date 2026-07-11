import { useState } from 'react';
import { Eye, ShieldAlert } from 'lucide-react';
import { api, type Tenant } from '../api/client';
import { Btn, toast } from './ui';

const ISP_CONSOLE = 'http://localhost:4600'; // dev; in prod: https://<slug>.wifios.co.ke

/**
 * The one door into a tenant's console — and it is deliberately a door, not a
 * switch. A reason is required and permanently recorded, the grant expires on its
 * own, and the ISP's data stays unreachable until the backend sees that grant.
 *
 * Everything else in this console exists so that you rarely have to open it.
 */
export default function ImpersonateDialog({
  tenant,
  onClose,
  onStarted,
}: {
  tenant: Tenant;
  onClose: () => void;
  onStarted: () => void;
}) {
  const [reason, setReason] = useState('');
  const [minutes, setMinutes] = useState(60);
  const [busy, setBusy] = useState(false);

  const start = async () => {
    setBusy(true);
    try {
      await api.impersonation.start(tenant.slug, reason.trim(), minutes);
      toast('good', `Access to ${tenant.name} opened for ${minutes} minutes — and recorded.`);
      // Hand off to the ISP console; it carries the act-as header, which the
      // backend will now honour because a live grant exists.
      window.open(`${ISP_CONSOLE}/?act_as=${encodeURIComponent(tenant.slug)}`, '_blank');
      onStarted();
    } catch {
      toast('critical', 'Could not open access.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      style={{ background: 'rgba(0,0,0,0.7)' }}
      onClick={onClose}
    >
      <div className="panel p-5 w-full max-w-md space-y-4" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start gap-3">
          <ShieldAlert className="h-5 w-5 shrink-0 mt-0.5" style={{ color: 'var(--warning)' }} />
          <div>
            <h2 className="font-semibold">Enter {tenant.name}'s console</h2>
            <p className="text-xs mt-1 leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
              You are about to look at another company's customers, payments and network. This is
              recorded permanently against your name, with the reason you give below.
            </p>
          </div>
        </div>

        <label className="block">
          <span
            className="text-[11px] uppercase tracking-wider"
            style={{ color: 'var(--text-muted)' }}
          >
            Reason (required)
          </span>
          <textarea
            rows={2}
            autoFocus
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="e.g. Investigating a payment the ISP says never arrived"
            className="mt-1"
          />
        </label>

        <label className="block">
          <span
            className="text-[11px] uppercase tracking-wider"
            style={{ color: 'var(--text-muted)' }}
          >
            Access expires after
          </span>
          <select
            value={minutes}
            onChange={(e) => setMinutes(Number(e.target.value))}
            className="mt-1"
          >
            <option value={15}>15 minutes</option>
            <option value={60}>1 hour</option>
            <option value={240}>4 hours</option>
          </select>
        </label>

        <div className="flex justify-end gap-2 pt-1">
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn variant="primary" onClick={start} disabled={busy || reason.trim().length < 5}>
            <Eye className="h-3.5 w-3.5" />
            {busy ? 'Opening…' : 'Open access'}
          </Btn>
        </div>
      </div>
    </div>
  );
}
