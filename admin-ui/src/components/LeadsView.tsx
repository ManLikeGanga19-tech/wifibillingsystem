import { useState, type FormEvent } from 'react';
import { UserPlus, Plus } from 'lucide-react';
import { api, ApiLead } from '../api/client';
import {
  Badge, Btn, Field, FilterChips, inputCls, Panel, RefreshBtn, TableShell, tdCls, toast, useList, ViewHeader, fmtDateTime,
} from './ui';

const FILTERS = ['new', 'all', 'contacted', 'converted', 'lost'] as const;
const STATUS_COLOR: Record<ApiLead['status'], 'green' | 'gray' | 'amber' | 'blue' | 'red'> = {
  new: 'amber',
  contacted: 'blue',
  converted: 'green',
  lost: 'gray',
};
const NEXT: Partial<Record<ApiLead['status'], { to: ApiLead['status']; label: string }[]>> = {
  new: [{ to: 'contacted', label: 'Mark contacted' }],
  contacted: [
    { to: 'converted', label: 'Converted' },
    { to: 'lost', label: 'Lost' },
  ],
};

export default function LeadsView() {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('new');
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ name: '', phone: '', location: '', source: '' });
  const { rows, count, error, reload } = useList(
    () => api.leads.list(filter === 'all' ? '' : `?status=${filter}`),
    [filter]
  );

  const create = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.leads.create(form);
      toast('success', `Lead "${form.name}" saved.`);
      setForm({ name: '', phone: '', location: '', source: '' });
      setShowForm(false);
      reload();
    } catch {
      toast('error', 'Failed to save lead.');
    }
  };

  const move = async (lead: ApiLead, to: ApiLead['status']) => {
    try {
      await api.leads.update(lead.id, { status: to });
      reload();
    } catch {
      toast('error', 'Failed to update lead.');
    }
  };

  return (
    <div className="space-y-5 text-[#141414]">
      <ViewHeader
        icon={<UserPlus className="h-4.5 w-4.5" />}
        title="Leads"
        subtitle="People interested in your WiFi — track them from first contact to paying client."
      >
        <Btn onClick={() => setShowForm(!showForm)}>
          <Plus className="h-3.5 w-3.5" /> New Lead
        </Btn>
        <RefreshBtn onClick={reload} />
      </ViewHeader>

      {showForm && (
        <Panel title="New lead">
          <form onSubmit={create} className="grid grid-cols-1 md:grid-cols-5 gap-3 items-end">
            <Field label="Name">
              <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Phone">
              <input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} className={inputCls} placeholder="07XX…" />
            </Field>
            <Field label="Location">
              <input value={form.location} onChange={(e) => setForm({ ...form, location: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Source">
              <input value={form.source} onChange={(e) => setForm({ ...form, source: e.target.value })} className={inputCls} placeholder="referral, flyer…" />
            </Field>
            <Btn type="submit" variant="green">Save</Btn>
          </form>
        </Panel>
      )}

      <FilterChips options={FILTERS} value={filter} onChange={setFilter} right={<span className="text-[11px] font-mono text-[#141414]/50">{count} leads</span>} />

      <TableShell
        headers={['Name', 'Phone', 'Location', 'Source', 'Status', 'Added', '']}
        loading={rows === null}
        error={error}
        empty="No leads in this list yet."
      >
        {(rows ?? []).map((l) => (
          <tr key={l.id} className="hover:bg-[#f0efec]/40 transition">
            <td className={`${tdCls} font-bold`}>{l.name}</td>
            <td className={`${tdCls} font-mono`}>{l.phone || '—'}</td>
            <td className={tdCls}>{l.location || '—'}</td>
            <td className={tdCls}>{l.source || '—'}</td>
            <td className={tdCls}><Badge color={STATUS_COLOR[l.status]}>{l.status}</Badge></td>
            <td className={`${tdCls} font-mono whitespace-nowrap`}>{fmtDateTime(l.created_at)}</td>
            <td className={`${tdCls} space-x-1.5 whitespace-nowrap`}>
              {(NEXT[l.status] ?? []).map((n) => (
                <span key={n.to} className="inline-block">
                  <Btn variant={n.to === 'lost' ? 'danger' : 'outline'} onClick={() => move(l, n.to)}>
                    {n.label}
                  </Btn>
                </span>
              ))}
            </td>
          </tr>
        ))}
      </TableShell>
    </div>
  );
}
