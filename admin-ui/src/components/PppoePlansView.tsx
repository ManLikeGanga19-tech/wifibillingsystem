import { useState, type FormEvent } from 'react';
import { Gauge, Plus } from 'lucide-react';
import { api, PppoePlan } from '../api/client';
import { Badge, Btn, Field, inputCls, Panel, RefreshBtn, TableShell, tdCls, toast, useList, ViewHeader, fmtKsh } from './ui';

const mbps = (kbps: number) => (kbps >= 1024 ? `${Math.round(kbps / 1024)} Mbps` : `${kbps} Kbps`);

export default function PppoePlansView() {
  const { rows, error, reload } = useList(() => api.pppoe.plans.list());
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    name: '', price: '', download: '', upload: '', mikrotik_profile: '',
  });

  const create = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.pppoe.plans.create({
        name: form.name,
        price: form.price,
        download_kbps: Math.round(Number(form.download) * 1024),
        upload_kbps: Math.round(Number(form.upload) * 1024),
        mikrotik_profile: form.mikrotik_profile || form.name.toLowerCase().replace(/\s+/g, '-'),
      });
      toast('success', 'Broadband plan created.');
      setForm({ name: '', price: '', download: '', upload: '', mikrotik_profile: '' });
      setShowForm(false);
      reload();
    } catch {
      toast('error', 'Failed to create plan.');
    }
  };

  return (
    <div className="space-y-5 text-[#141414]">
      <ViewHeader
        icon={<Gauge className="h-4.5 w-4.5" />}
        title="Broadband Plans"
        subtitle="Monthly PPPoE packages — separate from hotspot plans. The MikroTik profile sets the speed on the router."
      >
        <Btn onClick={() => setShowForm(!showForm)}>
          <Plus className="h-3.5 w-3.5" /> New Plan
        </Btn>
        <RefreshBtn onClick={reload} />
      </ViewHeader>

      {showForm && (
        <Panel title="New broadband plan">
          <form onSubmit={create} className="grid grid-cols-1 md:grid-cols-5 gap-3 items-end">
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
            <Btn type="submit" variant="green">Create</Btn>
            <Field label="MikroTik profile (optional)" className="md:col-span-2">
              <input value={form.mikrotik_profile} onChange={(e) => setForm({ ...form, mikrotik_profile: e.target.value })} className={inputCls} placeholder="auto from name" />
            </Field>
          </form>
        </Panel>
      )}

      <TableShell
        headers={['Name', 'Price/mo', 'Download', 'Upload', 'Profile', 'Status']}
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
            <td className={`${tdCls} font-mono`}>{p.mikrotik_profile}</td>
            <td className={tdCls}>
              <Badge color={p.is_active ? 'green' : 'gray'}>{p.is_active ? 'active' : 'inactive'}</Badge>
            </td>
          </tr>
        ))}
      </TableShell>
    </div>
  );
}
