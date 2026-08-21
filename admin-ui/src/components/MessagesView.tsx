import { useMemo, useState } from 'react';
import { MessageSquare } from 'lucide-react';
import { api, ApiMessage } from '../api/client';
import { Badge, FilterChips, ViewHeader, fmtDateTime } from './ui';
import DataTable, { type Column } from './DataTable';

const FILTERS = ['all', 'sms', 'whatsapp', 'email'] as const;
const STATUS_COLOR: Record<ApiMessage['status'], 'green' | 'gray' | 'red' | 'amber' | 'blue'> = {
  sent: 'green',
  queued: 'gray',
  failed: 'red',
};

export default function MessagesView() {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('all');

  const columns = useMemo<Column<ApiMessage>[]>(() => [
    { header: 'To', render: (m) => <span className="font-mono font-bold whitespace-nowrap">{m.to_email || m.to_phone}</span> },
    { header: 'Channel', render: (m) => <Badge color={m.channel === 'email' ? 'blue' : 'gray'}>{m.channel}</Badge> },
    {
      header: 'Message',
      render: (m) => (
        <>
          {m.subject && <span className="font-bold block">{m.subject}</span>}
          <span className="text-[#141414]/70 block max-w-[24rem] truncate" title={m.body}>{m.body}</span>
          {m.error && <span className="block text-[11px] text-[#B22222] font-mono">{m.error}</span>}
        </>
      ),
    },
    { header: 'Status', sortKey: 'status', render: (m) => <Badge color={STATUS_COLOR[m.status]}>{m.status}</Badge> },
    { header: 'Sent', sortKey: 'sent_at', render: (m) => <span className="font-mono whitespace-nowrap">{fmtDateTime(m.sent_at ?? m.created_at)}</span> },
  ], []);

  return (
    <div className="space-y-5 text-[#141414]">
      <ViewHeader
        icon={<MessageSquare className="h-4.5 w-4.5" />}
        title="Messages"
        subtitle="Every individual SMS, WhatsApp and email the system has sent — delivery status included."
      />

      <DataTable<ApiMessage>
        fetcher={(q) => api.messages.list(q)}
        columns={columns}
        rowKey={(m) => m.id}
        searchPlaceholder="Search recipient / subject…"
        emptyMessage="No messages sent yet — use Campaigns or Emails to reach your clients."
        filters={{ channel: filter === 'all' ? undefined : filter }}
        toolbar={<FilterChips options={FILTERS} value={filter} onChange={setFilter} />}
      />
    </div>
  );
}
