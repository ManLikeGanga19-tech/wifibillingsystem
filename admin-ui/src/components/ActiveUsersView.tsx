import { Fragment, useState } from 'react';
import { Activity, Ban, ChevronDown, Laptop, Smartphone, Tv, Monitor } from 'lucide-react';
import { api, ApiSession, ApiSessionDevice } from '../api/client';
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
  const [expanded, setExpanded] = useState<number | null>(null);
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
        headers={['User', 'Plan', 'Router', 'Status', 'Devices', 'Started', 'Expires', 'MAC', '']}
        loading={rows === null}
        error={error}
        empty="No sessions match this filter."
      >
        {(rows ?? []).map((s) => {
          const total = s.device_allowance ? s.device_allowance.general + s.device_allowance.tv : 1;
          const on = s.devices?.length ?? 0;
          // Only worth expanding when the plan is multi-device (or devices are attached).
          const canExpand = total > 1 || on > 1;
          const isOpen = expanded === s.id;
          return (
            <Fragment key={s.id}>
              <tr className="hover:bg-[#f0efec]/40 transition">
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
                <td className={tdCls}>
                  <DeviceCell
                    session={s}
                    total={total}
                    canExpand={canExpand}
                    isOpen={isOpen}
                    onToggle={() => setExpanded(isOpen ? null : s.id)}
                  />
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
              {isOpen && (
                <tr className="bg-[#faf9f7]">
                  <td colSpan={9} className="px-3 py-2.5 border-t border-[#141414]/10">
                    <DeviceList devices={s.devices ?? []} allowance={s.device_allowance} />
                  </td>
                </tr>
              )}
            </Fragment>
          );
        })}
      </TableShell>
    </div>
  );
}

function DeviceCell({
  session,
  total,
  canExpand,
  isOpen,
  onToggle,
}: {
  session: ApiSession;
  total: number;
  canExpand: boolean;
  isOpen: boolean;
  onToggle: () => void;
}) {
  const on = session.devices?.length ?? 0;
  if (!canExpand) {
    // Single-device plan — just show 1 quietly, nothing to expand.
    return <span className="font-mono text-[11px] text-[#141414]/50">{on || 1}</span>;
  }
  const tvOn = (session.devices ?? []).filter((d) => d.kind === 'tv').length;
  return (
    <button
      onClick={onToggle}
      className="inline-flex items-center gap-1.5 font-mono text-[11px] font-bold border border-[#141414]/25 px-2 py-1 hover:border-[#141414] transition cursor-pointer"
      title="Show devices on this session"
    >
      {on}/{total}
      {session.device_allowance?.tv ? ` · ${tvOn}/${session.device_allowance.tv} TV` : ''}
      <ChevronDown className={`h-3.5 w-3.5 transition-transform ${isOpen ? 'rotate-180' : ''}`} />
    </button>
  );
}

function DeviceList({
  devices,
  allowance,
}: {
  devices: ApiSessionDevice[];
  allowance?: { general: number; tv: number };
}) {
  if (devices.length === 0) {
    return (
      <p className="text-[11px] font-mono text-[#141414]/50">
        No devices recorded yet
        {allowance ? ` · plan allows ${allowance.general} device(s)${allowance.tv ? ` + ${allowance.tv} TV` : ''}` : ''}.
      </p>
    );
  }
  return (
    <div className="flex flex-wrap gap-2">
      {devices.map((d) => (
        <div
          key={d.mac_address}
          className="inline-flex items-center gap-2 bg-white border border-[#141414]/15 px-2.5 py-1.5"
        >
          <KindIcon kind={d.kind} />
          <div className="leading-tight">
            <div className="text-[11px] font-bold">{d.hostname || labelFor(d.kind)}</div>
            <div className="text-[10px] font-mono text-[#141414]/45">{d.mac_address}</div>
          </div>
          {d.is_paying_device && (
            <span className="text-[9px] font-mono font-bold uppercase text-[#228B22] ml-0.5">Paid</span>
          )}
        </div>
      ))}
    </div>
  );
}

function KindIcon({ kind }: { kind: ApiSessionDevice['kind'] }) {
  const cls = 'h-4 w-4 text-[#141414]/55 shrink-0';
  if (kind === 'tv') return <Tv className={cls} />;
  if (kind === 'laptop') return <Laptop className={cls} />;
  if (kind === 'phone') return <Smartphone className={cls} />;
  return <Monitor className={cls} />;
}

function labelFor(kind: ApiSessionDevice['kind']): string {
  return { phone: 'Phone', laptop: 'Laptop', tv: 'TV', other: 'Device' }[kind];
}
