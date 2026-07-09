import { useState, type FormEvent } from 'react';
import { HardDrive, Plus } from 'lucide-react';
import { api, ApiEquipment } from '../api/client';
import {
  Badge, Btn, Field, FilterChips, inputCls, Panel, RefreshBtn, TableShell, tdCls, toast, useList, ViewHeader, fmtKsh,
} from './ui';

const TYPES = ['router', 'antenna', 'switch', 'cpe', 'cable', 'power', 'other'] as const;
const FILTERS = ['all', 'in_store', 'deployed', 'faulty', 'retired'] as const;
const STATUS_COLOR: Record<ApiEquipment['status'], 'green' | 'gray' | 'amber' | 'red' | 'blue'> = {
  in_store: 'blue',
  deployed: 'green',
  faulty: 'amber',
  retired: 'gray',
};

export default function EquipmentView() {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('all');
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    name: '',
    equipment_type: 'other' as ApiEquipment['equipment_type'],
    serial_number: '',
    cost: '',
  });
  const { rows, count, error, reload } = useList(
    () => api.equipment.list(filter === 'all' ? '' : `?status=${filter}`),
    [filter]
  );

  const create = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.equipment.create({ ...form, cost: form.cost || null });
      toast('success', 'Equipment added to inventory.');
      setForm({ name: '', equipment_type: 'other', serial_number: '', cost: '' });
      setShowForm(false);
      reload();
    } catch {
      toast('error', 'Failed to add equipment.');
    }
  };

  const setStatus = async (item: ApiEquipment, status: ApiEquipment['status']) => {
    try {
      await api.equipment.update(item.id, { status });
      reload();
    } catch {
      toast('error', 'Failed to update equipment.');
    }
  };

  return (
    <div className="space-y-5 text-[#141414]">
      <ViewHeader
        icon={<HardDrive className="h-4.5 w-4.5" />}
        title="Equipment"
        subtitle="Inventory of radios, antennas and network gear — what's in store, deployed, or faulty."
      >
        <Btn onClick={() => setShowForm(!showForm)}>
          <Plus className="h-3.5 w-3.5" /> Add Equipment
        </Btn>
        <RefreshBtn onClick={reload} />
      </ViewHeader>

      {showForm && (
        <Panel title="Add equipment">
          <form onSubmit={create} className="grid grid-cols-1 md:grid-cols-5 gap-3 items-end">
            <Field label="Name">
              <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={inputCls} placeholder="e.g. LiteBeam AC" />
            </Field>
            <Field label="Type">
              <select value={form.equipment_type} onChange={(e) => setForm({ ...form, equipment_type: e.target.value as ApiEquipment['equipment_type'] })} className={inputCls}>
                {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
            </Field>
            <Field label="Serial number">
              <input value={form.serial_number} onChange={(e) => setForm({ ...form, serial_number: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Cost (KSh, optional)">
              <input type="number" min="0" step="0.01" value={form.cost} onChange={(e) => setForm({ ...form, cost: e.target.value })} className={inputCls} />
            </Field>
            <Btn type="submit" variant="green">Save</Btn>
          </form>
        </Panel>
      )}

      <FilterChips options={FILTERS} value={filter} onChange={setFilter} right={<span className="text-[11px] font-mono text-[#141414]/50">{count} items</span>} />

      <TableShell
        headers={['Name', 'Type', 'Serial', 'Site', 'Cost', 'Status', '']}
        loading={rows === null}
        error={error}
        empty="No equipment recorded yet."
      >
        {(rows ?? []).map((item) => (
          <tr key={item.id} className="hover:bg-[#f0efec]/40 transition">
            <td className={`${tdCls} font-bold`}>{item.name}</td>
            <td className={tdCls}><Badge color="gray">{item.equipment_type}</Badge></td>
            <td className={`${tdCls} font-mono`}>{item.serial_number || '—'}</td>
            <td className={tdCls}>{item.router_name || '—'}</td>
            <td className={`${tdCls} font-mono whitespace-nowrap`}>{fmtKsh(item.cost)}</td>
            <td className={tdCls}><Badge color={STATUS_COLOR[item.status]}>{item.status.replace('_', ' ')}</Badge></td>
            <td className={tdCls}>
              <select
                value={item.status}
                onChange={(e) => setStatus(item, e.target.value as ApiEquipment['status'])}
                className="border border-[#141414]/40 bg-white text-[11px] font-mono p-1 outline-none cursor-pointer"
                title="Change status"
              >
                {(['in_store', 'deployed', 'faulty', 'retired'] as const).map((s) => (
                  <option key={s} value={s}>{s.replace('_', ' ')}</option>
                ))}
              </select>
            </td>
          </tr>
        ))}
      </TableShell>
    </div>
  );
}
