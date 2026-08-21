import { useMemo } from 'react';
import { Users } from 'lucide-react';
import { api, type ApiSubscriber } from '../api/client';
import { Badge, ViewHeader, fmtDateTime } from './ui';
import DataTable, { type Column } from './DataTable';

export default function UsersView() {
  const columns = useMemo<Column<ApiSubscriber>[]>(() => [
    { header: 'Phone', render: (s) => <span className="font-mono font-bold">{s.phone}</span> },
    { header: 'Name', sortKey: 'name', render: (s) => s.name || '—' },
    { header: 'Email', render: (s) => s.email || '—' },
    {
      header: 'Status',
      render: (s) => s.active_sessions > 0
        ? <Badge color="green">online</Badge>
        : <Badge color="gray">offline</Badge>,
    },
    {
      header: 'Last access until',
      render: (s) => <span className="font-mono whitespace-nowrap">{fmtDateTime(s.last_session_expires)}</span>,
    },
    {
      header: 'Joined', sortKey: 'created_at',
      render: (s) => <span className="font-mono whitespace-nowrap">{fmtDateTime(s.date_joined)}</span>,
    },
  ], []);

  return (
    <div className="space-y-5 text-[#141414]">
      <ViewHeader
        icon={<Users className="h-4.5 w-4.5" />}
        title="Users"
        subtitle="Every client who has ever bought access. Created automatically on first payment."
      />

      <DataTable<ApiSubscriber>
        fetcher={(q) => api.subscribers.list(q)}
        columns={columns}
        rowKey={(s) => s.id}
        searchPlaceholder="Search phone, name or email…"
        emptyMessage="No clients yet — they appear after their first purchase."
      />
    </div>
  );
}
