import { useState } from 'react';
import { Receipt } from 'lucide-react';
import { api, PppoeInvoice } from '../api/client';
import { Badge, FilterChips, RefreshBtn, TableShell, tdCls, useList, ViewHeader, fmtDateTime, fmtKsh } from './ui';

const FILTERS = ['all', 'unpaid', 'overdue', 'paid'] as const;
const COLOR: Record<PppoeInvoice['status'], 'green' | 'amber' | 'red' | 'gray'> = {
  paid: 'green',
  unpaid: 'amber',
  overdue: 'red',
  cancelled: 'gray',
};

export default function PppoeInvoicesView() {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('all');
  const { rows, count, error, reload } = useList(
    () => api.pppoe.invoices.list(filter === 'all' ? '' : `?status=${filter}`),
    [filter]
  );

  return (
    <div className="space-y-5 text-[#141414]">
      <ViewHeader
        icon={<Receipt className="h-4.5 w-4.5" />}
        title="Broadband Invoices"
        subtitle="Monthly bills issued to PPPoE clients. Paid automatically when the client pays their account via M-Pesa."
      >
        <RefreshBtn onClick={reload} />
      </ViewHeader>

      <FilterChips options={FILTERS} value={filter} onChange={setFilter} right={<span className="text-[11px] font-mono text-[#141414]/50">{count} invoices</span>} />

      <TableShell
        headers={['Invoice', 'Account', 'Client', 'Period', 'Amount', 'Due', 'Status']}
        loading={rows === null}
        error={error}
        empty="No invoices yet — they issue automatically on each client's billing day."
      >
        {(rows ?? []).map((i: PppoeInvoice) => (
          <tr key={i.id} className="hover:bg-[#f0efec]/40 transition">
            <td className={`${tdCls} font-mono`}>{i.number}</td>
            <td className={`${tdCls} font-mono font-bold`}>{i.account_number}</td>
            <td className={tdCls}>{i.client_name}</td>
            <td className={`${tdCls} font-mono text-[11px] whitespace-nowrap`}>{i.period_start} → {i.period_end}</td>
            <td className={`${tdCls} font-mono font-bold`}>{fmtKsh(i.amount)}</td>
            <td className={`${tdCls} font-mono whitespace-nowrap`}>{i.due_date}</td>
            <td className={tdCls}><Badge color={COLOR[i.status]}>{i.status}</Badge></td>
          </tr>
        ))}
      </TableShell>
    </div>
  );
}
