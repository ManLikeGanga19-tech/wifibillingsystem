import { useEffect, useState, type FormEvent } from 'react';
import { Radio, Plus, RadioTower } from 'lucide-react';
import { api, Tower, AccessPoint, ApiRouter } from '../api/client';
import { Badge, Btn, Field, inputCls, Panel, RefreshBtn, TableShell, tdCls, toast, useList, ViewHeader } from './ui';

export default function NetworkView() {
  const towers = useList(() => api.pppoe.towers.list());
  const aps = useList(() => api.pppoe.accessPoints.list());
  const [routers, setRouters] = useState<ApiRouter[]>([]);
  const [showTower, setShowTower] = useState(false);
  const [showAp, setShowAp] = useState(false);
  const [tower, setTower] = useState({ name: '', notes: '' });
  const [ap, setAp] = useState({ tower: '', name: '', mode: 'ap', capacity: '', band: '', router: '' });

  useEffect(() => {
    api.routers.list().then((r) => setRouters(r.results)).catch(() => {});
  }, []);

  const createTower = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.pppoe.towers.create(tower);
      toast('success', 'Tower added.');
      setTower({ name: '', notes: '' });
      setShowTower(false);
      towers.reload();
    } catch {
      toast('error', 'Failed to add tower.');
    }
  };

  const createAp = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.pppoe.accessPoints.create({
        tower: Number(ap.tower),
        name: ap.name,
        mode: ap.mode as AccessPoint['mode'],
        capacity: Number(ap.capacity) || 0,
        band: ap.band,
        router: ap.router ? Number(ap.router) : null,
      });
      toast('success', 'Access point added.');
      setAp({ tower: '', name: '', mode: 'ap', capacity: '', band: '', router: '' });
      setShowAp(false);
      aps.reload();
    } catch {
      toast('error', 'Failed to add access point.');
    }
  };

  const utilColor = (u: number | null) => (u === null ? 'gray' : u >= 90 ? 'red' : u >= 70 ? 'amber' : 'green');

  return (
    <div className="space-y-6 text-[#141414]">
      <ViewHeader
        icon={<RadioTower className="h-4.5 w-4.5" />}
        title="Network"
        subtitle="Towers and access points (sectors) for your wireless PTP/PTMP clients. Track capacity so you don't oversubscribe a sector."
      >
        <Btn onClick={() => setShowTower(!showTower)}><Plus className="h-3.5 w-3.5" /> Tower</Btn>
        <Btn onClick={() => setShowAp(!showAp)}><Plus className="h-3.5 w-3.5" /> Access Point</Btn>
        <RefreshBtn onClick={() => { towers.reload(); aps.reload(); }} />
      </ViewHeader>

      {showTower && (
        <Panel title="Add tower / site">
          <form onSubmit={createTower} className="grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
            <Field label="Name"><input required value={tower.name} onChange={(e) => setTower({ ...tower, name: e.target.value })} className={inputCls} placeholder="e.g. Kibera Mast" /></Field>
            <Field label="Notes" className="md:col-span-2"><input value={tower.notes} onChange={(e) => setTower({ ...tower, notes: e.target.value })} className={inputCls} /></Field>
            <Btn type="submit" variant="green">Add</Btn>
          </form>
        </Panel>
      )}

      {showAp && (
        <Panel title="Add access point / sector">
          <form onSubmit={createAp} className="grid grid-cols-1 md:grid-cols-6 gap-3 items-end">
            <Field label="Tower">
              <select required value={ap.tower} onChange={(e) => setAp({ ...ap, tower: e.target.value })} className={inputCls}>
                <option value="">Select…</option>
                {(towers.rows ?? []).map((t: Tower) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
            </Field>
            <Field label="Name"><input required value={ap.name} onChange={(e) => setAp({ ...ap, name: e.target.value })} className={inputCls} placeholder="Sector A" /></Field>
            <Field label="Mode">
              <select value={ap.mode} onChange={(e) => setAp({ ...ap, mode: e.target.value })} className={inputCls}>
                <option value="ap">AP (PTMP)</option>
                <option value="ptp">PTP</option>
                <option value="ptmp">PTMP</option>
              </select>
            </Field>
            <Field label="Capacity"><input type="number" value={ap.capacity} onChange={(e) => setAp({ ...ap, capacity: e.target.value })} className={inputCls} placeholder="max clients" /></Field>
            <Field label="Band"><input value={ap.band} onChange={(e) => setAp({ ...ap, band: e.target.value })} className={inputCls} placeholder="5GHz" /></Field>
            <Btn type="submit" variant="green">Add</Btn>
          </form>
        </Panel>
      )}

      <TableShell
        headers={['Tower / Sector', 'Mode', 'Band', 'Clients', 'Capacity', 'Utilisation', 'Status']}
        loading={aps.rows === null}
        error={aps.error}
        empty="No access points yet — add a tower then its sectors."
      >
        {(aps.rows ?? []).map((a: AccessPoint) => (
          <tr key={a.id} className="hover:bg-[#f0efec]/40 transition">
            <td className={`${tdCls} font-bold`}>
              {a.tower_name} <span className="text-[#141414]/50">/</span> {a.name}
            </td>
            <td className={tdCls}><Badge color="blue">{a.mode}</Badge></td>
            <td className={`${tdCls} font-mono`}>{a.band || '—'}</td>
            <td className={`${tdCls} font-mono text-center`}>{a.client_count}</td>
            <td className={`${tdCls} font-mono text-center`}>{a.capacity || '—'}</td>
            <td className={tdCls}>
              {a.utilization === null ? <span className="text-[#141414]/40">—</span> : (
                <span className="flex items-center gap-2">
                  <span className="w-16 h-2 bg-[#141414]/10"><span className="block h-full" style={{ width: `${Math.min(100, a.utilization)}%`, background: a.utilization >= 90 ? '#B22222' : a.utilization >= 70 ? '#B26B00' : '#228B22' }} /></span>
                  <span className="font-mono text-[11px]">{a.utilization}%</span>
                </span>
              )}
            </td>
            <td className={tdCls}><Badge color={a.utilization !== null && a.utilization >= 90 ? 'red' : 'green'}>{a.utilization !== null && a.utilization >= 90 ? 'full' : 'ok'}</Badge></td>
          </tr>
        ))}
      </TableShell>
      <p className="text-[11px] font-mono text-[#141414]/50">{(towers.rows ?? []).length} towers · {(aps.rows ?? []).length} access points</p>
    </div>
  );
}
