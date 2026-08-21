import { useEffect, useState, type FormEvent } from 'react';
import { LifeBuoy, Plus } from 'lucide-react';
import { api, ApiTicket, TicketAssignee } from '../api/client';
import { Badge, Btn, Field, FilterChips, inputCls, Panel, toast, ViewHeader, fmtDateTime } from './ui';
import DataTable, { type Column } from './DataTable';
import MapPicker from './MapPicker';
import NavigateButton from './NavigateButton';

const FILTERS = ['open', 'all', 'in_progress', 'resolved', 'closed'] as const;
const STATUS_COLOR: Record<ApiTicket['status'], 'green' | 'gray' | 'amber' | 'blue' | 'red'> = {
  open: 'amber',
  in_progress: 'blue',
  resolved: 'green',
  closed: 'gray',
};
const PRIORITY_COLOR: Record<ApiTicket['priority'], 'green' | 'gray' | 'amber' | 'red' | 'blue'> = {
  low: 'gray',
  normal: 'blue',
  high: 'amber',
  urgent: 'red',
};
const NEXT_STATUS: Partial<Record<ApiTicket['status'], { to: ApiTicket['status']; label: string }>> = {
  open: { to: 'in_progress', label: 'Start' },
  in_progress: { to: 'resolved', label: 'Resolve' },
  resolved: { to: 'closed', label: 'Close' },
};

export default function TicketsView({ canAssign = false }: { canAssign?: boolean }) {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('open');
  const [showForm, setShowForm] = useState(false);
  const [subject, setSubject] = useState('');
  const [description, setDescription] = useState('');
  const [priority, setPriority] = useState<ApiTicket['priority']>('normal');
  const [gps, setGps] = useState<{ lat: number | null; lng: number | null }>({ lat: null, lng: null });
  const [assignees, setAssignees] = useState<TicketAssignee[]>([]);
  const [refresh, setRefresh] = useState(0);
  const reload = () => setRefresh((n) => n + 1);

  // Dispatchers (tickets.assign) get the technician list for the "assign to" picker.
  useEffect(() => {
    if (canAssign) api.tickets.assignees().then(setAssignees).catch(() => {});
  }, [canAssign]);

  const assign = async (t: ApiTicket, userId: number | null) => {
    try {
      await api.tickets.update(t.id, { assigned_to: userId });
      toast('success', userId ? 'Ticket assigned.' : 'Ticket unassigned.');
      reload();
    } catch {
      toast('error', 'Failed to assign the ticket.');
    }
  };

  const create = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.tickets.create({
        subject, description, priority,
        gps_lat: gps.lat != null ? String(gps.lat) : null,
        gps_lng: gps.lng != null ? String(gps.lng) : null,
      });
      toast('success', 'Ticket created.');
      setSubject('');
      setDescription('');
      setGps({ lat: null, lng: null });
      setShowForm(false);
      reload();
    } catch {
      toast('error', 'Failed to create ticket.');
    }
  };

  const advance = async (t: ApiTicket) => {
    const next = NEXT_STATUS[t.status];
    if (!next) return;
    try {
      await api.tickets.update(t.id, { status: next.to });
      reload();
    } catch {
      toast('error', 'Failed to update ticket.');
    }
  };

  return (
    <div className="space-y-5 text-[#141414]">
      <ViewHeader
        icon={<LifeBuoy className="h-4.5 w-4.5" />}
        title="Support Tickets"
        subtitle="Track client complaints and site issues from report to resolution."
      >
        <Btn onClick={() => setShowForm(!showForm)}>
          <Plus className="h-3.5 w-3.5" /> New Ticket
        </Btn>
      </ViewHeader>

      {showForm && (
        <Panel title="New ticket">
          <form onSubmit={create} className="grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
            <Field label="Subject" className="md:col-span-2">
              <input required value={subject} onChange={(e) => setSubject(e.target.value)} className={inputCls} placeholder="e.g. No internet at Site B" />
            </Field>
            <Field label="Priority">
              <select value={priority} onChange={(e) => setPriority(e.target.value as ApiTicket['priority'])} className={inputCls}>
                {(['low', 'normal', 'high', 'urgent'] as const).map((p) => <option key={p} value={p}>{p}</option>)}
              </select>
            </Field>
            <Btn type="submit" variant="green">Create</Btn>
            <Field label="Details (optional)" className="md:col-span-4">
              <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} className={inputCls} />
            </Field>
            <div className="md:col-span-4">
              <label className="text-[11px] font-mono uppercase text-[#141414]/50 block mb-1">Job location (optional) — pin it so the technician can navigate there</label>
              <MapPicker
                lat={gps.lat} lng={gps.lng}
                onChange={(la, ln) => setGps({
                  lat: Number.isFinite(la) ? la : null, lng: Number.isFinite(ln) ? ln : null,
                })}
              />
            </div>
          </form>
        </Panel>
      )}

      <DataTable<ApiTicket>
        fetcher={(q) => api.tickets.list(q)}
        columns={ticketColumns()}
        rowKey={(t) => t.id}
        searchPlaceholder="Search subject / details…"
        emptyMessage="No tickets here — that's a good thing."
        filters={{ status: filter === 'all' ? undefined : filter }}
        refreshSignal={refresh}
        toolbar={<FilterChips options={FILTERS} value={filter} onChange={setFilter} />}
      />
    </div>
  );

  function ticketColumns(): Column<ApiTicket>[] {
    return [
      { header: '#', render: (t) => <span className="font-mono">#{t.id}</span> },
      {
        header: 'Subject',
        render: (t) => (
          <>
            <span className="font-bold">{t.subject}</span>
            {t.description && <span className="block text-[11px] text-[#141414]/60 max-w-[20rem] truncate">{t.description}</span>}
          </>
        ),
      },
      { header: 'Client', render: (t) => <span className="font-mono">{t.subscriber_phone || '—'}</span> },
      { header: 'Priority', sortKey: 'priority', render: (t) => <Badge color={PRIORITY_COLOR[t.priority]}>{t.priority}</Badge> },
      { header: 'Status', render: (t) => <Badge color={STATUS_COLOR[t.status]}>{t.status.replace('_', ' ')}</Badge> },
      {
        header: 'Assigned to',
        render: (t) => canAssign ? (
          <select
            value={t.assigned_to ?? ''}
            onChange={(e) => assign(t, e.target.value ? Number(e.target.value) : null)}
            className="border border-[#141414]/30 px-1.5 py-1 text-xs bg-white cursor-pointer max-w-[9rem]"
          >
            <option value="">Unassigned</option>
            {assignees.map((a) => <option key={a.id} value={a.id}>{a.name || a.phone}</option>)}
          </select>
        ) : (
          <span className="text-xs">{t.assigned_to_name || '—'}</span>
        ),
      },
      { header: 'Created', sortKey: 'created_at', render: (t) => <span className="font-mono whitespace-nowrap">{fmtDateTime(t.created_at)}</span> },
      {
        header: '',
        render: (t) => (
          <div className="flex items-center gap-1.5">
            {t.gps_lat && t.gps_lng && (
              <NavigateButton lat={Number(t.gps_lat)} lng={Number(t.gps_lng)} label={t.subject} compact />
            )}
            {NEXT_STATUS[t.status] && (
              <Btn variant="outline" onClick={() => advance(t)}>{NEXT_STATUS[t.status]!.label}</Btn>
            )}
          </div>
        ),
      },
    ];
  }
}
