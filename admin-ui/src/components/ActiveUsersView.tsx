import { useState } from 'react';
import { Activity, Ban } from 'lucide-react';
import { api, ApiSession } from '../api/client';
import { Badge, Btn, FilterChips, RefreshBtn, TableShell, tdCls, toast, useList, ViewHeader, fmtDateTime } from './ui';

const FILTERS = ['active', 'all', 'expired', 'suspended', 'failed'] as const;
const STATUS_COLOR: Record<ApiSession['status'], 'green' | 'gray' | 'red' | 'amber' | 'blue'> = {
  active: 'green',
  pending: 'gray',
  expired: 'gray',
  suspended: 'amber',
  failed: 'red',
};

export default function ActiveUsersView() {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('active');
  const { rows, count, error, reload } = useList(
    () => api.sessions.list(filter === 'all' ? '' : `?status=${filter}`),
    [filter]
  );

  const suspend = async (session: ApiSession) => {
    if (!confirm(`Disconnect ${session.hotspot_username} from ${session.router_name}?`)) return;
    try {
      await api.sessions.suspend(session.id);
      toast('success', `Suspension queued for ${session.hotspot_username}.`);
      window.setTimeout(reload, 1200);
    } catch (e) {
      toast('error', e instanceof Error ? e.message : 'Failed to suspend session.');
    }
  };

  return (
    <div className="space-y-5 text-[#141414]">
      <ViewHeader
        icon={<Activity className="h-4.5 w-4.5" />}
        title="Active Users"
        subtitle="Live hotspot sessions on your routers. Suspend cuts the user off immediately."
      >
        <RefreshBtn onClick={reload} />
      </ViewHeader>

      <FilterChips
        options={FILTERS}
        value={filter}
        onChange={setFilter}
        right={<span className="text-[11px] font-mono text-[#141414]/50">{count} sessions</span>}
      />

      <TableShell
        headers={['User', 'Plan', 'Router', 'Status', 'Started', 'Expires', 'MAC', '']}
        loading={rows === null}
        error={error}
        empty="No sessions match this filter."
      >
        {(rows ?? []).map((s) => (
          <tr key={s.id} className="hover:bg-[#f0efec]/40 transition">
            <td className={`${tdCls} font-mono font-bold`}>{s.hotspot_username}</td>
            <td className={tdCls}>{s.plan_name}</td>
            <td className={tdCls}>{s.router_name}</td>
            <td className={tdCls}>
              <Badge color={STATUS_COLOR[s.status]}>{s.status}</Badge>
              {s.provision_error && (
                <span className="block text-[10px] text-[#B22222] font-mono mt-0.5 max-w-[12rem] truncate" title={s.provision_error}>
                  {s.provision_error}
                </span>
              )}
            </td>
            <td className={`${tdCls} font-mono whitespace-nowrap`}>{fmtDateTime(s.starts_at)}</td>
            <td className={`${tdCls} font-mono whitespace-nowrap`}>{fmtDateTime(s.expires_at)}</td>
            <td className={`${tdCls} font-mono`}>{s.mac_address || '—'}</td>
            <td className={tdCls}>
              {s.status === 'active' && (
                <Btn variant="danger" onClick={() => suspend(s)} title="Disconnect this user">
                  <Ban className="h-3.5 w-3.5" />
                  Suspend
                </Btn>
              )}
            </td>
          </tr>
        ))}
      </TableShell>
    </div>
  );
}
