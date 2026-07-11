import { useState } from 'react';
import { Ban, Check } from 'lucide-react';
import { api, dt, ksh, type Payout } from '../api/client';
import {
  Badge,
  Btn,
  Empty,
  ErrorBox,
  Panel,
  RefreshBtn,
  Spinner,
  STATUS_TONE,
  Table,
  td,
  tdStyle,
  toast,
  useLoad,
} from '../components/ui';

const FILTERS = ['requested', 'paid', 'rejected', ''] as const;
const LABEL: Record<string, string> = {
  requested: 'Pending',
  paid: 'Paid',
  rejected: 'Rejected',
  '': 'All',
};

/**
 * The payout queue. Money leaves Danamo's custody here, so this is the most
 * consequential screen in the console: the funds are already debited (held) from
 * the ISP's wallet when they request, so paying is a settlement, and rejecting
 * returns the money to them.
 */
export default function PayoutsPanel() {
  const [filter, setFilter] = useState<string>('requested');
  const { data, error, reload } = useLoad(() => api.payouts.list(filter), [filter]);

  const markPaid = async (p: Payout) => {
    const ref = window.prompt(
      `Pay ${ksh(p.amount)} to ${p.operator_name} via ${p.method}.\n\nDestination: ${p.destination}\n\nEnter the transaction reference once you have sent it:`
    );
    if (!ref?.trim()) return;
    try {
      await api.payouts.markPaid(p.id, ref.trim().toUpperCase());
      toast('good', `Payout to ${p.operator_name} recorded as paid.`);
      reload();
    } catch (e) {
      toast('critical', e instanceof Error ? e.message : 'Could not record the payout.');
    }
  };

  const reject = async (p: Payout) => {
    const note = window.prompt(`Reject this payout? The funds return to ${p.operator_name}'s wallet.\n\nReason:`);
    if (note === null) return;
    try {
      await api.payouts.reject(p.id, note.trim() || 'Rejected');
      toast('warning', 'Payout rejected — funds returned to their wallet.');
      reload();
    } catch (e) {
      toast('critical', e instanceof Error ? e.message : 'Could not reject.');
    }
  };

  if (error) return <ErrorBox message={error} onRetry={reload} />;

  return (
    <Panel
      title="Payout queue"
      subtitle="ISPs withdrawing from their wallet. Funds are already held — pay them, then record the reference."
      right={<RefreshBtn onClick={reload} />}
    >
      <div className="flex gap-1.5 mb-4">
        {FILTERS.map((f) => (
          <Btn key={f} variant={filter === f ? 'primary' : 'ghost'} onClick={() => setFilter(f)}>
            {LABEL[f]}
          </Btn>
        ))}
      </div>

      {!data ? (
        <Spinner />
      ) : data.results.length === 0 ? (
        <Empty message="Nothing in this queue." />
      ) : (
        <Table head={['Requested', 'ISP', 'Amount', 'Method', 'Destination', 'Status', '']}>
          {data.results.map((p) => (
            <tr key={p.id} className="hover:bg-white/[0.03] transition">
              <td
                className={`${td} whitespace-nowrap tnum`}
                style={{ ...tdStyle, color: 'var(--text-muted)' }}
              >
                {dt(p.created_at)}
              </td>
              <td className={td} style={tdStyle}>
                {p.operator_name}
              </td>
              <td className={`${td} tnum font-medium`} style={tdStyle}>
                {ksh(p.amount)}
              </td>
              <td className={td} style={{ ...tdStyle, color: 'var(--text-secondary)' }}>
                {p.method}
              </td>
              <td
                className={`${td} tnum max-w-[16rem] truncate`}
                style={{ ...tdStyle, color: 'var(--text-secondary)' }}
                title={p.destination}
              >
                {p.destination}
              </td>
              <td className={td} style={tdStyle}>
                <Badge tone={STATUS_TONE[p.status] ?? 'neutral'}>{p.status}</Badge>
                {p.mpesa_reference && (
                  <span
                    className="block text-[10px] tnum mt-0.5"
                    style={{ color: 'var(--text-muted)' }}
                  >
                    {p.mpesa_reference}
                  </span>
                )}
              </td>
              <td className={td} style={tdStyle}>
                {p.status === 'requested' && (
                  <div className="flex gap-1.5">
                    <Btn variant="primary" onClick={() => markPaid(p)}>
                      <Check className="h-3.5 w-3.5" /> Mark paid
                    </Btn>
                    <Btn variant="danger" onClick={() => reject(p)}>
                      <Ban className="h-3.5 w-3.5" /> Reject
                    </Btn>
                  </div>
                )}
              </td>
            </tr>
          ))}
        </Table>
      )}
    </Panel>
  );
}
