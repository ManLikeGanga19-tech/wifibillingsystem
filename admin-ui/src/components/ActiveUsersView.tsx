import { Fragment, useState } from 'react';
import { Activity, Ban, ChevronDown, Laptop, Smartphone, Tv, Monitor } from 'lucide-react';
import { api, LiveConnection, ApiSessionDevice } from '../api/client';
import { Badge, Btn, FilterChips, RefreshBtn, TableShell, tdCls, toast, useList, ViewHeader, fmtDateTime } from './ui';

// The Active Users page shows everyone ONLINE NOW, across every service type — hotspot and
// PPPoE today, static/dynamic/Ruijie as they land. One table, filtered by service.
const FILTERS = ['all', 'hotspot', 'pppoe'] as const;
const SERVICE_COLOR: Record<LiveConnection['service_type'], 'blue' | 'amber'> = {
  hotspot: 'blue',
  pppoe: 'amber',
};

export default function ActiveUsersView() {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('all');
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [expanded, setExpanded] = useState<string | null>(null);

  const { rows, count, error, refreshing, reload } = useList<LiveConnection>(async () => {
    const r = await api.liveConnections(filter);
    setCounts(r.counts);
    return { results: r.results, count: r.results.length };
  }, [filter]);

  const suspend = async (row: LiveConnection) => {
    // Only hotspot sessions can be disconnected from here. A PPPoE line is a billing
    // relationship — suspending it is done deliberately on the Clients page, not by a
    // stray click on the live list.
    if (!confirm(`Disconnect ${row.identifier} from ${row.router_name}?`)) return;
    try {
      await api.sessions.suspend(row.id);
      toast('success', `Suspension queued for ${row.identifier}.`);
      window.setTimeout(reload, 1200);
    } catch (e) {
      toast('error', e instanceof Error ? e.message : 'Failed to suspend session.');
    }
  };

  const total = (counts.hotspot ?? 0) + (counts.pppoe ?? 0);

  return (
    <div className="space-y-5 text-[#141414]">
      <ViewHeader
        icon={<Activity className="h-4.5 w-4.5" />}
        title="Active Users"
        subtitle="Everyone online right now across every service. Suspend disconnects a hotspot session immediately."
      >
        <RefreshBtn onClick={reload} spinning={refreshing} />
      </ViewHeader>

      <FilterChips
        options={FILTERS}
        value={filter}
        onChange={setFilter}
        right={
          <span className="text-[11px] font-mono text-[#141414]/50">
            {total} online · H {counts.hotspot ?? 0} · P {counts.pppoe ?? 0}
          </span>
        }
      />

      <TableShell
        headers={['Service', 'User', 'Name', 'Plan', 'Router', 'Status', 'Online', 'IP', 'Devices', '']}
        loading={rows === null}
        error={error}
        empty="Nobody is online in this view right now."
      >
        {(rows ?? []).map((s) => {
          const key = `${s.service_type}-${s.id}`;
          const allow = s.device_allowance;
          const totalDevices = allow ? allow.general + allow.tv : 1;
          const on = s.devices?.length ?? 0;
          const canExpand = s.service_type === 'hotspot' && (totalDevices > 1 || on > 1);
          const isOpen = expanded === key;
          return (
            <Fragment key={key}>
              <tr className="hover:bg-[#f0efec]/40 transition">
                <td className={tdCls}>
                  <Badge color={SERVICE_COLOR[s.service_type]}>{s.service_type}</Badge>
                </td>
                <td className={`${tdCls} font-mono font-bold`}>{s.identifier}</td>
                <td className={tdCls}>{s.name || '—'}</td>
                <td className={tdCls}>{s.plan_name}</td>
                <td className={tdCls}>{s.router_name}</td>
                <td className={tdCls}>
                  <Badge color="green">{s.status}</Badge>
                  {s.provision_error && (
                    <span className="block text-[10px] text-[#B22222] font-mono mt-0.5 max-w-[12rem] truncate" title={s.provision_error}>
                      {s.provision_error}
                    </span>
                  )}
                </td>
                <td className={`${tdCls} font-mono whitespace-nowrap`} title={s.since ? fmtDateTime(s.since) : ''}>
                  {s.uptime || (s.since ? fmtDateTime(s.since) : '—')}
                </td>
                <td className={`${tdCls} font-mono`}>{s.ip || '—'}</td>
                <td className={tdCls}>
                  {s.service_type === 'hotspot' ? (
                    <DeviceCell
                      row={s}
                      total={totalDevices}
                      canExpand={canExpand}
                      isOpen={isOpen}
                      onToggle={() => setExpanded(isOpen ? null : key)}
                    />
                  ) : (
                    <span className="text-[#141414]/30">—</span>
                  )}
                </td>
                <td className={tdCls}>
                  {s.service_type === 'hotspot' && (
                    <Btn variant="danger" onClick={() => suspend(s)} title="Disconnect this user">
                      <Ban className="h-3.5 w-3.5" />
                      Suspend
                    </Btn>
                  )}
                </td>
              </tr>
              {isOpen && (
                <tr className="bg-[#faf9f7]">
                  <td colSpan={10} className="px-3 py-2.5 border-t border-[#141414]/10">
                    <DeviceList devices={s.devices ?? []} allowance={allow ?? undefined} />
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
  row,
  total,
  canExpand,
  isOpen,
  onToggle,
}: {
  row: LiveConnection;
  total: number;
  canExpand: boolean;
  isOpen: boolean;
  onToggle: () => void;
}) {
  const on = row.devices?.length ?? 0;
  if (!canExpand) {
    return <span className="font-mono text-[11px] text-[#141414]/50">{on || 1}</span>;
  }
  const tvOn = (row.devices ?? []).filter((d) => d.kind === 'tv').length;
  return (
    <button
      onClick={onToggle}
      className="inline-flex items-center gap-1.5 font-mono text-[11px] font-bold border border-[#141414]/25 px-2 py-1 hover:border-[#141414] transition cursor-pointer"
      title="Show devices on this session"
    >
      {on}/{total}
      {row.device_allowance?.tv ? ` · ${tvOn}/${row.device_allowance.tv} TV` : ''}
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
