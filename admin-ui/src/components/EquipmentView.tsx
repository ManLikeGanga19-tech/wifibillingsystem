import { useMemo, useState, type FormEvent } from 'react';
import { HardDrive, Pencil, Plus, Trash2 } from 'lucide-react';
import { api, ApiEquipment, ApiError } from '../api/client';
import { Badge, Btn, Field, FilterChips, inputCls, Panel, toast, ViewHeader, fmtKsh } from './ui';
import DataTable, { type Column } from './DataTable';

const TYPES = ['router', 'antenna', 'switch', 'cpe', 'cable', 'power', 'other'] as const;
const FILTERS = ['all', 'in_store', 'deployed', 'faulty', 'retired'] as const;
const STATUS_COLOR: Record<ApiEquipment['status'], 'green' | 'gray' | 'amber' | 'red' | 'blue'> = {
  in_store: 'blue',
  deployed: 'green',
  faulty: 'amber',
  retired: 'gray',
};

const BLANK = {
  name: '', equipment_type: 'other' as ApiEquipment['equipment_type'], serial_number: '', cost: '',
};

export default function EquipmentView() {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('all');
  const [showForm, setShowForm] = useState(false);
  const [editing, setEditing] = useState<ApiEquipment | null>(null);
  const [form, setForm] = useState({ ...BLANK });
  // Bumping this reloads the DataTable (after a create / edit / delete / status change).
  const [refresh, setRefresh] = useState(0);
  const reload = () => setRefresh((n) => n + 1);

  const openNew = () => { setEditing(null); setForm({ ...BLANK }); setShowForm(true); };
  const openEdit = (item: ApiEquipment) => {
    setEditing(item);
    setForm({
      name: item.name, equipment_type: item.equipment_type,
      serial_number: item.serial_number, cost: item.cost ? String(item.cost) : '',
    });
    setShowForm(true);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const body = { ...form, cost: form.cost || null };
    try {
      if (editing) {
        await api.equipment.update(editing.id, body);
        toast('success', 'Equipment updated.');
      } else {
        await api.equipment.create(body);
        toast('success', 'Equipment added to inventory.');
      }
      setForm({ ...BLANK }); setEditing(null); setShowForm(false);
      reload();
    } catch (err) {
      toast('error', err instanceof ApiError ? err.message : 'Failed to save equipment.');
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

  const remove = async (item: ApiEquipment) => {
    if (!confirm(`Delete "${item.name}" from inventory?`)) return;
    try {
      await api.equipment.remove(item.id);
      toast('success', 'Equipment deleted.');
      reload();
    } catch (err) {
      toast('error', err instanceof ApiError ? err.message : 'Could not delete the equipment.');
    }
  };

  const columns = useMemo<Column<ApiEquipment>[]>(() => [
    { header: 'Name', sortKey: 'name', render: (i) => <span className="font-bold">{i.name}</span> },
    { header: 'Type', render: (i) => <Badge color="gray">{i.equipment_type}</Badge> },
    { header: 'Serial', render: (i) => <span className="font-mono">{i.serial_number || '—'}</span> },
    { header: 'Site', render: (i) => i.router_name || '—' },
    {
      header: 'Cost', className: 'text-right',
      render: (i) => <span className="font-mono whitespace-nowrap">{fmtKsh(i.cost)}</span>,
    },
    {
      header: 'Status',
      render: (i) => <Badge color={STATUS_COLOR[i.status]}>{i.status.replace('_', ' ')}</Badge>,
    },
    {
      header: '',
      render: (i) => (
        <div className="flex items-center gap-1.5">
          <select
            value={i.status}
            onChange={(e) => setStatus(i, e.target.value as ApiEquipment['status'])}
            className="border border-[#141414]/40 bg-white text-[11px] font-mono p-1 outline-none cursor-pointer"
            title="Change status"
          >
            {(['in_store', 'deployed', 'faulty', 'retired'] as const).map((s) => (
              <option key={s} value={s}>{s.replace('_', ' ')}</option>
            ))}
          </select>
          <Btn variant="outline" onClick={() => openEdit(i)} title="Edit equipment"><Pencil className="h-3.5 w-3.5" /></Btn>
          <Btn variant="danger" onClick={() => remove(i)} title="Delete equipment"><Trash2 className="h-3.5 w-3.5" /></Btn>
        </div>
      ),
    },
  ], []); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="space-y-5 text-[#141414]">
      <ViewHeader
        icon={<HardDrive className="h-4.5 w-4.5" />}
        title="Equipment"
        subtitle="Inventory of radios, antennas and network gear — what's in store, deployed, or faulty."
      >
        <Btn onClick={openNew}>
          <Plus className="h-3.5 w-3.5" /> Add Equipment
        </Btn>
      </ViewHeader>

      {showForm && (
        <Panel title={editing ? `Edit ${editing.name}` : 'Add equipment'}>
          <form onSubmit={submit} className="grid grid-cols-1 md:grid-cols-5 gap-3 items-end">
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
            <div className="flex gap-2">
              <Btn type="submit" variant="green">Save</Btn>
              {editing && <Btn type="button" variant="outline" onClick={() => { setShowForm(false); setEditing(null); }}>Cancel</Btn>}
            </div>
          </form>
        </Panel>
      )}

      <DataTable<ApiEquipment>
        fetcher={(q) => api.equipment.list(q)}
        columns={columns}
        rowKey={(i) => i.id}
        searchPlaceholder="Search equipment…"
        emptyMessage="No equipment recorded yet."
        filters={{ status: filter === 'all' ? undefined : filter }}
        refreshSignal={refresh}
        toolbar={<FilterChips options={FILTERS} value={filter} onChange={setFilter} />}
      />
    </div>
  );
}
