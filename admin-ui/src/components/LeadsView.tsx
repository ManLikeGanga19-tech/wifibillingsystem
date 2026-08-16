import { useState, type FormEvent } from 'react';
import { Pencil, Plus, Trash2, UserPlus } from 'lucide-react';
import { api, ApiError, ApiLead } from '../api/client';
import MapPicker from './MapPicker';
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

const BLANK = { name: '', phone: '', location: '', source: '',
  gps_lat: null as number | null, gps_lng: null as number | null };

export default function LeadsView() {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('new');
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<ApiLead | null>(null);
  const [form, setForm] = useState({ ...BLANK });
  const { rows, count, error, refreshing, reload } = useList(
    () => api.leads.list(filter === 'all' ? '' : `?status=${filter}`),
    [filter]
  );

  const openNew = () => { setEditing(null); setForm({ ...BLANK }); setShowForm(true); };
  const openEdit = (l: ApiLead) => {
    setEditing(l);
    setForm({ name: l.name, phone: l.phone, location: l.location, source: l.source,
      gps_lat: l.gps_lat ? Number(l.gps_lat) : null, gps_lng: l.gps_lng ? Number(l.gps_lng) : null });
    setShowForm(true);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    try {
      if (editing) {
        await api.leads.update(editing.id, form);
        toast('success', 'Lead updated.');
      } else {
        await api.leads.create(form);
        toast('success', `Lead "${form.name}" saved.`);
      }
      setForm({ ...BLANK }); setEditing(null); setShowForm(false);
      reload();
    } catch (err) {
      toast('error', err instanceof ApiError ? err.message : 'Failed to save the lead.');
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

  const remove = async (l: ApiLead) => {
    if (!confirm(`Delete lead "${l.name}"?`)) return;
    try {
      await api.leads.remove(l.id);
      toast('success', 'Lead deleted.');
      reload();
    } catch (err) {
      toast('error', err instanceof ApiError ? err.message : 'Could not delete the lead.');
    }
  };

  return (
    <div className="space-y-5 text-[#141414]">
      <ViewHeader
        icon={<UserPlus className="h-4.5 w-4.5" />}
        title="Leads"
        subtitle="People interested in your WiFi — track them from first contact to paying client."
      >
        <Btn onClick={openNew}>
          <Plus className="h-3.5 w-3.5" /> New Lead
        </Btn>
        <RefreshBtn onClick={reload} spinning={refreshing} />
      </ViewHeader>

      {showForm && (
        <Panel title={editing ? `Edit ${editing.name}` : 'New lead'}>
          <form onSubmit={submit} className="grid grid-cols-1 md:grid-cols-5 gap-3 items-end">
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
            <div className="md:col-span-5">
              <label className="text-[11px] font-mono uppercase text-[#141414]/50 block mb-1">Location on map (for the demand heatmap)</label>
              <MapPicker
                lat={form.gps_lat} lng={form.gps_lng}
                onChange={(la, ln) => setForm((f) => ({
                  ...f, gps_lat: Number.isFinite(la) ? la : null, gps_lng: Number.isFinite(ln) ? ln : null,
                }))}
              />
            </div>
            <div className="flex gap-2">
              <Btn type="submit" variant="green">Save</Btn>
              {editing && <Btn type="button" variant="outline" onClick={() => { setShowForm(false); setEditing(null); }}>Cancel</Btn>}
            </div>
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
            <td className={`${tdCls} whitespace-nowrap`}>
              <div className="flex items-center gap-1.5">
                {(NEXT[l.status] ?? []).map((n) => (
                  <span key={n.to} className="inline-block">
                    <Btn variant={n.to === 'lost' ? 'danger' : 'outline'} onClick={() => move(l, n.to)}>
                      {n.label}
                    </Btn>
                  </span>
                ))}
                <Btn variant="outline" onClick={() => openEdit(l)} title="Edit lead"><Pencil className="h-3.5 w-3.5" /></Btn>
                <Btn variant="danger" onClick={() => remove(l)} title="Delete lead"><Trash2 className="h-3.5 w-3.5" /></Btn>
              </div>
            </td>
          </tr>
        ))}
      </TableShell>
    </div>
  );
}
