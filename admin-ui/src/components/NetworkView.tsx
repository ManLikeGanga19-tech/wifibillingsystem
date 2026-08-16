import { Fragment, useEffect, useState, type FormEvent } from 'react';
import { Pencil, Plus, RadioTower, Trash2 } from 'lucide-react';
import { api, ApiError, Tower, AccessPoint, ApiRouter } from '../api/client';
import MapPicker from './MapPicker';
import { Badge, Btn, Field, inputCls, Panel, RefreshBtn, TableShell, tdCls, toast, useList, ViewHeader } from './ui';

const BLANK_TOWER = { name: '', notes: '',
  gps_lat: null as number | null, gps_lng: null as number | null };
const BLANK_AP = { tower: '', name: '', mode: 'ap', capacity: '', band: '', router: '' };

export default function NetworkView() {
  const towers = useList(() => api.pppoe.towers.list());
  const aps = useList(() => api.pppoe.accessPoints.list());
  const [routers, setRouters] = useState<ApiRouter[]>([]);
  const [showTower, setShowTower] = useState(false);
  const [showAp, setShowAp] = useState(false);
  const [editingTower, setEditingTower] = useState<Tower | null>(null);
  const [editingAp, setEditingAp] = useState<AccessPoint | null>(null);
  const [tower, setTower] = useState({ ...BLANK_TOWER });
  const [ap, setAp] = useState({ ...BLANK_AP });

  useEffect(() => {
    api.routers.list().then((r) => setRouters(r.results)).catch(() => {});
  }, []);

  const newTower = () => { setEditingTower(null); setTower({ ...BLANK_TOWER }); setShowTower(true); };
  const editTower = (t: Tower) => {
    setEditingTower(t);
    setTower({ name: t.name, notes: t.notes,
      gps_lat: t.gps_lat ? Number(t.gps_lat) : null, gps_lng: t.gps_lng ? Number(t.gps_lng) : null });
    setShowTower(true);
  };
  const newAp = () => { setEditingAp(null); setAp({ ...BLANK_AP }); setShowAp(true); };
  const editAp = (a: AccessPoint) => {
    setEditingAp(a);
    setAp({
      tower: String(a.tower), name: a.name, mode: a.mode,
      capacity: a.capacity ? String(a.capacity) : '', band: a.band,
      router: a.router ? String(a.router) : '',
    });
    setShowAp(true);
  };

  const submitTower = async (e: FormEvent) => {
    e.preventDefault();
    try {
      if (editingTower) await api.pppoe.towers.update(editingTower.id, tower);
      else await api.pppoe.towers.create(tower);
      toast('success', editingTower ? 'Tower updated.' : 'Tower added.');
      setShowTower(false); setEditingTower(null); setTower({ ...BLANK_TOWER });
      towers.reload();
    } catch (err) {
      toast('error', err instanceof ApiError ? err.message : 'Failed to save the tower.');
    }
  };

  const submitAp = async (e: FormEvent) => {
    e.preventDefault();
    const body = {
      tower: Number(ap.tower), name: ap.name, mode: ap.mode as AccessPoint['mode'],
      capacity: Number(ap.capacity) || 0, band: ap.band,
      router: ap.router ? Number(ap.router) : null,
    };
    try {
      if (editingAp) await api.pppoe.accessPoints.update(editingAp.id, body);
      else await api.pppoe.accessPoints.create(body);
      toast('success', editingAp ? 'Access point updated.' : 'Access point added.');
      setShowAp(false); setEditingAp(null); setAp({ ...BLANK_AP });
      aps.reload();
    } catch (err) {
      toast('error', err instanceof ApiError ? err.message : 'Failed to save the access point.');
    }
  };

  const deleteTower = async (t: Tower) => {
    if (!confirm(`Delete tower "${t.name}" and its sectors? Sectors with clients must be cleared first.`)) return;
    try {
      await api.pppoe.towers.remove(t.id);
      toast('success', 'Tower deleted.');
      towers.reload(); aps.reload();
    } catch (err) {
      toast('error', err instanceof ApiError ? err.message : 'Could not delete the tower.');
    }
  };

  const deleteAp = async (a: AccessPoint) => {
    if (!confirm(`Delete sector "${a.name}"? Clients on it must be moved first.`)) return;
    try {
      await api.pppoe.accessPoints.remove(a.id);
      toast('success', 'Access point deleted.');
      aps.reload();
    } catch (err) {
      toast('error', err instanceof ApiError ? err.message : 'Could not delete the access point.');
    }
  };

  return (
    <div className="space-y-6 text-[#141414]">
      <ViewHeader
        icon={<RadioTower className="h-4.5 w-4.5" />}
        title="Network"
        subtitle="Towers and access points (sectors) for your wireless PTP/PTMP clients. Track capacity so you don't oversubscribe a sector."
      >
        <Btn onClick={newTower}><Plus className="h-3.5 w-3.5" /> Tower</Btn>
        <Btn onClick={newAp}><Plus className="h-3.5 w-3.5" /> Access Point</Btn>
        <RefreshBtn onClick={() => { towers.reload(); aps.reload(); }} spinning={towers.refreshing || aps.refreshing} />
      </ViewHeader>

      {showTower && (
        <Panel title={editingTower ? `Edit ${editingTower.name}` : 'Add tower / site'}>
          <form onSubmit={submitTower} className="grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
            <Field label="Name"><input required value={tower.name} onChange={(e) => setTower({ ...tower, name: e.target.value })} className={inputCls} placeholder="e.g. Kibera Mast" /></Field>
            <Field label="Notes" className="md:col-span-2"><input value={tower.notes} onChange={(e) => setTower({ ...tower, notes: e.target.value })} className={inputCls} /></Field>
            <div className="md:col-span-4">
              <label className="text-[11px] font-mono uppercase text-[#141414]/50 block mb-1">Tower location</label>
              <MapPicker
                lat={tower.gps_lat} lng={tower.gps_lng}
                onChange={(la, ln) => setTower((t) => ({
                  ...t, gps_lat: Number.isFinite(la) ? la : null, gps_lng: Number.isFinite(ln) ? ln : null,
                }))}
              />
            </div>
            <div className="flex gap-2">
              <Btn type="submit" variant="green">{editingTower ? 'Save' : 'Add'}</Btn>
              {editingTower && <Btn type="button" variant="outline" onClick={() => { setShowTower(false); setEditingTower(null); }}>Cancel</Btn>}
            </div>
          </form>
        </Panel>
      )}

      {showAp && (
        <Panel title={editingAp ? `Edit ${editingAp.name}` : 'Add access point / sector'}>
          <form onSubmit={submitAp} className="grid grid-cols-1 md:grid-cols-6 gap-3 items-end">
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
            <div className="flex gap-2">
              <Btn type="submit" variant="green">{editingAp ? 'Save' : 'Add'}</Btn>
              {editingAp && <Btn type="button" variant="outline" onClick={() => { setShowAp(false); setEditingAp(null); }}>Cancel</Btn>}
            </div>
          </form>
        </Panel>
      )}

      <TableShell
        headers={['Tower / Sector', 'Mode', 'Band', 'Clients', 'Capacity', 'Utilisation', 'Status', '']}
        loading={towers.rows === null || aps.rows === null}
        error={towers.error || aps.error}
        empty="No towers yet — add one to get started, then its sectors."
      >
        {/* Grouped by tower, so a tower with no sectors still shows up the moment you add
            it — the table is driven by towers, not only access points. */}
        {(towers.rows ?? []).map((t: Tower) => {
          const sectors = (aps.rows ?? []).filter((a: AccessPoint) => a.tower === t.id);
          return (
            <Fragment key={`tower-${t.id}`}>
              <tr className="bg-[#f0efec]/60">
                <td className={`${tdCls} font-bold`} colSpan={8}>
                  <span className="flex items-center justify-between gap-2">
                    <span className="inline-flex items-center gap-2">
                      <RadioTower className="h-3.5 w-3.5" /> {t.name}
                      <span className="font-mono text-[11px] text-[#141414]/50">
                        {sectors.length} sector{sectors.length === 1 ? '' : 's'}
                      </span>
                      {t.notes && <span className="text-[11px] text-[#141414]/45">— {t.notes}</span>}
                    </span>
                    <span className="flex gap-1.5">
                      <Btn variant="outline" onClick={() => editTower(t)} title="Edit tower"><Pencil className="h-3.5 w-3.5" /></Btn>
                      <Btn variant="danger" onClick={() => deleteTower(t)} title="Delete tower"><Trash2 className="h-3.5 w-3.5" /></Btn>
                    </span>
                  </span>
                </td>
              </tr>
              {sectors.length === 0 && (
                <tr>
                  <td className={`${tdCls} italic text-[#141414]/40`} colSpan={8}>
                    No sectors yet — add an access point to this tower.
                  </td>
                </tr>
              )}
              {sectors.map((a: AccessPoint) => (
                <tr key={a.id} className="hover:bg-[#f0efec]/40 transition">
                  <td className={tdCls}>
                    <span className="pl-5 text-[#141414]/50">/</span> {a.name}
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
                  <td className={tdCls}>
                    <div className="flex gap-1.5">
                      <Btn variant="outline" onClick={() => editAp(a)} title="Edit sector"><Pencil className="h-3.5 w-3.5" /></Btn>
                      <Btn variant="danger" onClick={() => deleteAp(a)} title="Delete sector"><Trash2 className="h-3.5 w-3.5" /></Btn>
                    </div>
                  </td>
                </tr>
              ))}
            </Fragment>
          );
        })}
      </TableShell>
      <p className="text-[11px] font-mono text-[#141414]/50">{(towers.rows ?? []).length} towers · {(aps.rows ?? []).length} access points</p>
    </div>
  );
}
