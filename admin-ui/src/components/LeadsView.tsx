import { useMemo, useState, type FormEvent } from 'react';
import { Pencil, Plus, Trash2, UserPlus } from 'lucide-react';
import { api, ApiError, ApiLead } from '../api/client';
import MapPicker from './MapPicker';
import { Badge, Btn, Field, FilterChips, inputCls, Panel, toast, ViewHeader, fmtDateTime } from './ui';
import DataTable, { type Column } from './DataTable';

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
  const [refresh, setRefresh] = useState(0);
  const reload = () => setRefresh((n) => n + 1);

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

  const columns = useMemo(columnsDef, []); // eslint-disable-line react-hooks/exhaustive-deps

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

      <DataTable<ApiLead>
        fetcher={(q) => api.leads.list(q)}
        columns={columns}
        rowKey={(l) => l.id}
        searchPlaceholder="Search leads…"
        emptyMessage="No leads in this list yet."
        filters={{ status: filter === 'all' ? undefined : filter }}
        refreshSignal={refresh}
        toolbar={<FilterChips options={FILTERS} value={filter} onChange={setFilter} />}
      />
    </div>
  );

  function columnsDef(): Column<ApiLead>[] {
    return [
      { header: 'Name', render: (l) => <span className="font-bold">{l.name}</span> },
      { header: 'Phone', render: (l) => <span className="font-mono">{l.phone || '—'}</span> },
      { header: 'Location', render: (l) => l.location || '—' },
      { header: 'Source', render: (l) => l.source || '—' },
      { header: 'Status', sortKey: 'status', render: (l) => <Badge color={STATUS_COLOR[l.status]}>{l.status}</Badge> },
      { header: 'Added', sortKey: 'created_at', render: (l) => <span className="font-mono whitespace-nowrap">{fmtDateTime(l.created_at)}</span> },
      {
        header: '',
        render: (l) => (
          <div className="flex items-center gap-1.5 whitespace-nowrap">
            {(NEXT[l.status] ?? []).map((n) => (
              <span key={n.to}>
                <Btn variant={n.to === 'lost' ? 'danger' : 'outline'} onClick={() => move(l, n.to)}>
                  {n.label}
                </Btn>
              </span>
            ))}
            <Btn variant="outline" onClick={() => openEdit(l)} title="Edit lead"><Pencil className="h-3.5 w-3.5" /></Btn>
            <Btn variant="danger" onClick={() => remove(l)} title="Delete lead"><Trash2 className="h-3.5 w-3.5" /></Btn>
          </div>
        ),
      },
    ];
  }
}
