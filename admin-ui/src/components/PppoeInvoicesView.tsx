import { useMemo, useState } from 'react';
import { Receipt } from 'lucide-react';
import { api, PppoeInvoice } from '../api/client';
import { Badge, FilterChips, ViewHeader, fmtKsh } from './ui';
import DataTable, { type Column } from './DataTable';

const FILTERS = ['all', 'unpaid', 'overdue', 'paid'] as const;
const COLOR: Record<PppoeInvoice['status'], 'green' | 'amber' | 'red' | 'gray'> = {
  paid: 'green',
  unpaid: 'amber',
  overdue: 'red',
  cancelled: 'gray',
};

export default function PppoeInvoicesView() {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('all');

  const columns = useMemo<Column<PppoeInvoice>[]>(() => [
    { header: 'Invoice', render: (i) => <span className="font-mono">{i.number}</span> },
    { header: 'Account', render: (i) => <span className="font-mono font-bold">{i.account_number}</span> },
    { header: 'Client', render: (i) => i.client_name },
    {
      header: 'Period',
      render: (i) => <span className="font-mono text-[11px] whitespace-nowrap">{i.period_start} → {i.period_end}</span>,
    },
    { header: 'Amount', sortKey: 'amount', render: (i) => <span className="font-mono font-bold">{fmtKsh(i.amount)}</span> },
    { header: 'Due', sortKey: 'due_date', render: (i) => <span className="font-mono whitespace-nowrap">{i.due_date}</span> },
    { header: 'Status', sortKey: 'status', render: (i) => <Badge color={COLOR[i.status]}>{i.status}</Badge> },
  ], []);

  return (
    <div className="space-y-5 text-[#141414]">
      <ViewHeader
        icon={<Receipt className="h-4.5 w-4.5" />}
        title="Broadband Invoices"
        subtitle="Monthly bills issued to PPPoE clients. Paid automatically when the client pays their account via M-Pesa."
      />

      <DataTable<PppoeInvoice>
        fetcher={(q) => api.pppoe.invoices.list(q)}
        columns={columns}
        rowKey={(i) => i.id}
        searchPlaceholder="Search invoice / account / client…"
        emptyMessage="No invoices yet — they issue automatically on each client's billing day."
        filters={{ status: filter === 'all' ? undefined : filter }}
        toolbar={<FilterChips options={FILTERS} value={filter} onChange={setFilter} />}
      />
    </div>
  );
}
