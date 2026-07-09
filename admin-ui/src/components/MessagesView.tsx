import { useState } from 'react';
import { MessageSquare } from 'lucide-react';
import { api, ApiMessage } from '../api/client';
import { Badge, FilterChips, RefreshBtn, TableShell, tdCls, useList, ViewHeader, fmtDateTime } from './ui';

const FILTERS = ['all', 'sms', 'whatsapp', 'email'] as const;
const STATUS_COLOR: Record<ApiMessage['status'], 'green' | 'gray' | 'red' | 'amber' | 'blue'> = {
  sent: 'green',
  queued: 'gray',
  failed: 'red',
};

export default function MessagesView() {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('all');
  const { rows, count, error, reload } = useList(
    () => api.messages.list(filter === 'all' ? '' : `?channel=${filter}`),
    [filter]
  );

  return (
    <div className="space-y-5 text-[#141414]">
      <ViewHeader
        icon={<MessageSquare className="h-4.5 w-4.5" />}
        title="Messages"
        subtitle="Every individual SMS, WhatsApp and email the system has sent — delivery status included."
      >
        <RefreshBtn onClick={reload} />
      </ViewHeader>

      <FilterChips options={FILTERS} value={filter} onChange={setFilter} right={<span className="text-[11px] font-mono text-[#141414]/50">{count} messages</span>} />

      <TableShell
        headers={['To', 'Channel', 'Message', 'Status', 'Sent']}
        loading={rows === null}
        error={error}
        empty="No messages sent yet — use Campaigns or Emails to reach your clients."
      >
        {(rows ?? []).map((m) => (
          <tr key={m.id} className="hover:bg-[#f0efec]/40 transition">
            <td className={`${tdCls} font-mono font-bold whitespace-nowrap`}>{m.to_email || m.to_phone}</td>
            <td className={tdCls}><Badge color={m.channel === 'email' ? 'blue' : 'gray'}>{m.channel}</Badge></td>
            <td className={tdCls}>
              {m.subject && <span className="font-bold block">{m.subject}</span>}
              <span className="text-[#141414]/70 block max-w-[24rem] truncate" title={m.body}>{m.body}</span>
              {m.error && <span className="block text-[11px] text-[#B22222] font-mono">{m.error}</span>}
            </td>
            <td className={tdCls}><Badge color={STATUS_COLOR[m.status]}>{m.status}</Badge></td>
            <td className={`${tdCls} font-mono whitespace-nowrap`}>{fmtDateTime(m.sent_at ?? m.created_at)}</td>
          </tr>
        ))}
      </TableShell>
    </div>
  );
}
