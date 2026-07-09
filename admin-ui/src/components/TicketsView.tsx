import { useState, type FormEvent } from 'react';
import { LifeBuoy, Plus } from 'lucide-react';
import { api, ApiTicket } from '../api/client';
import {
  Badge, Btn, Field, FilterChips, inputCls, Panel, RefreshBtn, TableShell, tdCls, toast, useList, ViewHeader, fmtDateTime,
} from './ui';

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

export default function TicketsView() {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('open');
  const [showForm, setShowForm] = useState(false);
  const [subject, setSubject] = useState('');
  const [description, setDescription] = useState('');
  const [priority, setPriority] = useState<ApiTicket['priority']>('normal');
  const { rows, count, error, reload } = useList(
    () => api.tickets.list(filter === 'all' ? '' : `?status=${filter}`),
    [filter]
  );

  const create = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.tickets.create({ subject, description, priority });
      toast('success', 'Ticket created.');
      setSubject('');
      setDescription('');
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
        <RefreshBtn onClick={reload} />
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
          </form>
        </Panel>
      )}

      <FilterChips options={FILTERS} value={filter} onChange={setFilter} right={<span className="text-[11px] font-mono text-[#141414]/50">{count} tickets</span>} />

      <TableShell
        headers={['#', 'Subject', 'Client', 'Priority', 'Status', 'Created', '']}
        loading={rows === null}
        error={error}
        empty="No tickets here — that's a good thing."
      >
        {(rows ?? []).map((t) => (
          <tr key={t.id} className="hover:bg-[#f0efec]/40 transition">
            <td className={`${tdCls} font-mono`}>#{t.id}</td>
            <td className={tdCls}>
              <span className="font-bold">{t.subject}</span>
              {t.description && <span className="block text-[11px] text-[#141414]/60 max-w-[20rem] truncate">{t.description}</span>}
            </td>
            <td className={`${tdCls} font-mono`}>{t.subscriber_phone || '—'}</td>
            <td className={tdCls}><Badge color={PRIORITY_COLOR[t.priority]}>{t.priority}</Badge></td>
            <td className={tdCls}><Badge color={STATUS_COLOR[t.status]}>{t.status.replace('_', ' ')}</Badge></td>
            <td className={`${tdCls} font-mono whitespace-nowrap`}>{fmtDateTime(t.created_at)}</td>
            <td className={tdCls}>
              {NEXT_STATUS[t.status] && (
                <Btn variant="outline" onClick={() => advance(t)}>{NEXT_STATUS[t.status]!.label}</Btn>
              )}
            </td>
          </tr>
        ))}
      </TableShell>
    </div>
  );
}
