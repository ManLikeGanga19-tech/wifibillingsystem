import { useMemo, useState } from 'react';
import { Users, Search } from 'lucide-react';
import { api } from '../api/client';
import { Badge, inputCls, RefreshBtn, TableShell, tdCls, useList, ViewHeader, fmtDateTime } from './ui';

export default function UsersView() {
  const { rows, count, error, reload } = useList(() => api.subscribers.list());
  const [query, setQuery] = useState('');

  const filtered = useMemo(() => {
    if (!rows) return null;
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (s) => s.phone.includes(q) || s.name.toLowerCase().includes(q) || s.email.toLowerCase().includes(q)
    );
  }, [rows, query]);

  return (
    <div className="space-y-5 text-[#141414]">
      <ViewHeader
        icon={<Users className="h-4.5 w-4.5" />}
        title="Users"
        subtitle="Every client who has ever bought access. Created automatically on first payment."
      >
        <RefreshBtn onClick={reload} />
      </ViewHeader>

      <div className="relative max-w-sm">
        <Search className="h-4 w-4 absolute left-2.5 top-2.5 text-[#141414]/40" />
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search phone, name or email…"
          className={`${inputCls} pl-8`}
        />
      </div>

      <TableShell
        headers={['Phone', 'Name', 'Email', 'Status', 'Last access until', 'Joined']}
        loading={filtered === null}
        error={error}
        empty={query ? 'No clients match your search.' : 'No clients yet — they appear after their first purchase.'}
      >
        {(filtered ?? []).map((s) => (
          <tr key={s.id} className="hover:bg-[#f0efec]/40 transition">
            <td className={`${tdCls} font-mono font-bold`}>{s.phone}</td>
            <td className={tdCls}>{s.name || '—'}</td>
            <td className={tdCls}>{s.email || '—'}</td>
            <td className={tdCls}>
              {s.active_sessions > 0 ? <Badge color="green">online</Badge> : <Badge color="gray">offline</Badge>}
            </td>
            <td className={`${tdCls} font-mono whitespace-nowrap`}>{fmtDateTime(s.last_session_expires)}</td>
            <td className={`${tdCls} font-mono whitespace-nowrap`}>{fmtDateTime(s.date_joined)}</td>
          </tr>
        ))}
      </TableShell>
      <p className="text-[11px] font-mono text-[#141414]/50">{count} clients total</p>
    </div>
  );
}
