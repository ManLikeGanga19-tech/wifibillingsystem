import { useState, type FormEvent } from 'react';
import { Gauge, Pencil, Plus, Trash2 } from 'lucide-react';
import { api, ApiError, PppoePlan } from '../api/client';
import { Badge, Btn, Field, inputCls, Panel, RefreshBtn, TableShell, tdCls, toast, useList, ViewHeader, fmtKsh } from './ui';

const mbps = (kbps: number) => (kbps >= 1024 ? `${Math.round(kbps / 1024)} Mbps` : `${kbps} Kbps`);

const BLANK = {
  name: '', price: '', download: '', upload: '', mikrotik_profile: '', data_cap_gb: '', is_active: true,
};

export default function PppoePlansView() {
  const { rows, error, refreshing, reload } = useList(() => api.pppoe.plans.list());
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<PppoePlan | null>(null);
  const [form, setForm] = useState({ ...BLANK });

  const openNew = () => {
    setEditing(null);
    setForm({ ...BLANK });
    setShowForm(true);
  };

  const openEdit = (p: PppoePlan) => {
    setEditing(p);
    setForm({
      name: p.name,
      price: String(p.price),
      download: String(Math.round(p.download_kbps / 1024)),
      upload: String(Math.round(p.upload_kbps / 1024)),
      mikrotik_profile: p.mikrotik_profile,
      data_cap_gb: p.data_cap_gb ? String(p.data_cap_gb) : '',
      is_active: p.is_active,
    });
    setShowForm(true);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const body = {
      name: form.name,
      price: form.price,
      download_kbps: Math.round(Number(form.download) * 1024),
      upload_kbps: Math.round(Number(form.upload) * 1024),
      mikrotik_profile: form.mikrotik_profile || form.name.toLowerCase().replace(/\s+/g, '-'),
      // Blank = unlimited. The cap drives the FUP alerts and the usage bar.
      data_cap_gb: form.data_cap_gb.trim() ? Number(form.data_cap_gb) : null,
      is_active: form.is_active,
    };
    try {
      if (editing) {
        await api.pppoe.plans.update(editing.id, body);
        toast('success', 'Broadband plan updated.');
      } else {
        await api.pppoe.plans.create(body);
        toast('success', 'Broadband plan created.');
      }
      setShowForm(false);
      setEditing(null);
      setForm({ ...BLANK });
      reload();
    } catch (err) {
      toast('error', err instanceof ApiError ? err.message : 'Failed to save the plan.');
    }
  };

  const remove = async (p: PppoePlan) => {
    if (!confirm(`Delete the "${p.name}" plan? Clients on it must be moved to another plan first.`)) return;
    try {
      await api.pppoe.plans.remove(p.id);
      toast('success', 'Plan deleted.');
      reload();
    } catch (err) {
      toast('error', err instanceof ApiError ? err.message : 'Could not delete the plan.');
    }
  };

  return (
    <div className="space-y-5 text-[#141414]">
      <ViewHeader
        icon={<Gauge className="h-4.5 w-4.5" />}
        title="Broadband Plans"
        subtitle="Monthly PPPoE packages — separate from hotspot plans. The MikroTik profile sets the speed on the router."
      >
        <Btn onClick={openNew}>
          <Plus className="h-3.5 w-3.5" /> New Plan
        </Btn>
        <RefreshBtn onClick={reload} spinning={refreshing} />
      </ViewHeader>

      {showForm && (
        <Panel title={editing ? `Edit ${editing.name}` : 'New broadband plan'}>
          <form onSubmit={submit} className="grid grid-cols-1 md:grid-cols-5 gap-3 items-end">
            <Field label="Name">
              <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={inputCls} placeholder="Home 10Mbps" />
            </Field>
            <Field label="Monthly price (KSh)">
              <input type="number" required value={form.price} onChange={(e) => setForm({ ...form, price: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Download (Mbps)">
              <input type="number" required value={form.download} onChange={(e) => setForm({ ...form, download: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Upload (Mbps)">
              <input type="number" required value={form.upload} onChange={(e) => setForm({ ...form, upload: e.target.value })} className={inputCls} />
            </Field>
            <Btn type="submit" variant="green">{editing ? 'Save changes' : 'Create'}</Btn>
            <Field label="Data cap (GB) — blank = unlimited">
              <input type="number" min="1" value={form.data_cap_gb} onChange={(e) => setForm({ ...form, data_cap_gb: e.target.value })} className={inputCls} placeholder="Unlimited" />
            </Field>
            <Field label="MikroTik profile (optional)" className="md:col-span-2">
              <input value={form.mikrotik_profile} onChange={(e) => setForm({ ...form, mikrotik_profile: e.target.value })} className={inputCls} placeholder="auto from name" />
            </Field>
            <label className="flex items-center gap-2 text-sm md:self-center">
              <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
              Active (offered to new clients)
            </label>
            {editing && (
              <Btn type="button" variant="outline" onClick={() => { setShowForm(false); setEditing(null); }}>
                Cancel
              </Btn>
            )}
          </form>
        </Panel>
      )}

      <TableShell
        headers={['Name', 'Price/mo', 'Download', 'Upload', 'Data cap', 'Profile', 'Status', '']}
        loading={rows === null}
        error={error}
        empty="No broadband plans yet — create one to start signing up clients."
      >
        {(rows ?? []).map((p: PppoePlan) => (
          <tr key={p.id} className="hover:bg-[#f0efec]/40 transition">
            <td className={`${tdCls} font-bold`}>{p.name}</td>
            <td className={`${tdCls} font-mono`}>{fmtKsh(p.price)}</td>
            <td className={`${tdCls} font-mono`}>{mbps(p.download_kbps)}</td>
            <td className={`${tdCls} font-mono`}>{mbps(p.upload_kbps)}</td>
            <td className={`${tdCls} font-mono`}>
              {p.data_cap_gb ? `${p.data_cap_gb} GB` : <span className="text-[#141414]/40">Unlimited</span>}
            </td>
            <td className={`${tdCls} font-mono`}>{p.mikrotik_profile}</td>
            <td className={tdCls}>
              <Badge color={p.is_active ? 'green' : 'gray'}>{p.is_active ? 'active' : 'inactive'}</Badge>
            </td>
            <td className={tdCls}>
              <div className="flex gap-1.5">
                <Btn variant="outline" onClick={() => openEdit(p)} title="Edit plan">
                  <Pencil className="h-3.5 w-3.5" />
                </Btn>
                <Btn variant="danger" onClick={() => remove(p)} title="Delete plan">
                  <Trash2 className="h-3.5 w-3.5" />
                </Btn>
              </div>
            </td>
          </tr>
        ))}
      </TableShell>
    </div>
  );
}
