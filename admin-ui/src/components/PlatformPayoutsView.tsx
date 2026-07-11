import { useState } from 'react';
import { Banknote, Check, X } from 'lucide-react';
import { api, ApiPayout } from '../api/client';
import { Badge, Btn, FilterChips, RefreshBtn, TableShell, tdCls, toast, useList, ViewHeader, fmtDateTime, fmtKsh } from './ui';

const FILTERS = ['requested', 'all', 'paid', 'rejected'] as const;

export default function PlatformPayoutsView() {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('requested');
  const { rows, count, error, reload } = useList(
    () => api.platform.payouts.list(filter === 'all' ? '' : `?status=${filter}`),
    [filter]
  );

  const markPaid = async (p: ApiPayout) => {
    const how = p.method === 'bank' ? 'via EFT/Pesalink' : 'via M-Pesa';
    const ref = prompt(
      `Pay ${fmtKsh(p.amount)} ${how} to:\n${p.destination}\n(${p.operator_name})\n\nThen enter the transaction reference:`
    );
    if (!ref?.trim()) return;
    try {
      await api.platform.payouts.markPaid(p.id, ref.trim().toUpperCase());
      toast('success', `Payout to ${p.operator_name} recorded.`);
      reload();
    } catch (e) {
      toast('error', e instanceof Error ? e.message : 'Failed to record payment.');
    }
  };

  const reject = async (p: ApiPayout) => {
    const note = prompt(`Reject ${fmtKsh(p.amount)} payout for ${p.operator_name}? Reason:`);
    if (note === null) return;
    try {
      await api.platform.payouts.reject(p.id, note || 'Rejected');
      toast('warning', 'Payout rejected — funds returned to their wallet.');
      reload();
    } catch (e) {
      toast('error', e instanceof Error ? e.message : 'Failed to reject.');
    }
  };

  return (
    <div className="space-y-5 text-[#141414]">
      <ViewHeader
        icon={<Banknote className="h-4.5 w-4.5" />}
        title="ISP Payouts"
        subtitle="Withdrawals requested by ISPs. Send the M-Pesa yourself, then record the transaction code here."
      >
        <RefreshBtn onClick={reload} />
      </ViewHeader>

      <FilterChips options={FILTERS} value={filter} onChange={setFilter} right={<span className="text-[11px] font-mono text-[#141414]/50">{count} payouts</span>} />

      <TableShell
        headers={['Requested', 'ISP', 'Method', 'Pay To', 'Amount', 'Status', 'Reference', '']}
        loading={rows === null}
        error={error}
        empty="No payouts in this list."
      >
        {(rows ?? []).map((p) => (
          <tr key={p.id} className="hover:bg-[#f0efec]/40 transition">
            <td className={`${tdCls} font-mono whitespace-nowrap`}>{fmtDateTime(p.created_at)}</td>
            <td className={`${tdCls} font-bold`}>{p.operator_name}</td>
            <td className={tdCls}><Badge color={p.method === 'bank' ? 'blue' : 'green'}>{p.method}</Badge></td>
            <td className={`${tdCls} font-mono text-[11px] max-w-[16rem]`}>{p.destination}</td>
            <td className={`${tdCls} font-mono font-bold whitespace-nowrap`}>{fmtKsh(p.amount)}</td>
            <td className={tdCls}>
              <Badge color={p.status === 'paid' ? 'green' : p.status === 'rejected' ? 'red' : 'amber'}>{p.status}</Badge>
              {p.note && <span className="block text-[11px] font-mono text-[#141414]/50 mt-0.5">{p.note}</span>}
            </td>
            <td className={`${tdCls} font-mono`}>{p.mpesa_reference || '—'}</td>
            <td className={`${tdCls} whitespace-nowrap space-x-1.5`}>
              {p.status === 'requested' && (
                <>
                  <Btn variant="green" onClick={() => markPaid(p)}>
                    <Check className="h-3.5 w-3.5" /> Paid
                  </Btn>
                  <Btn variant="danger" onClick={() => reject(p)}>
                    <X className="h-3.5 w-3.5" /> Reject
                  </Btn>
                </>
              )}
            </td>
          </tr>
        ))}
      </TableShell>
    </div>
  );
}
