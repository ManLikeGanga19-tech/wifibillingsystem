import { useState, type FormEvent } from 'react';
import { Waypoints, Plus, Pencil, Trash2, RotateCcw, Zap, X, Cable, Send, Loader2, HardHat } from 'lucide-react';
import {
  api, ApiError, type FibrePoint, type FibreSpan, type FibreType, type BlastRadius, type NearestTech,
} from '../api/client';
import {
  Badge, Btn, Field, inputCls, Panel, RefreshBtn, TableShell, tdCls, toast, useList, ViewHeader,
} from './ui';
import MapPicker from './MapPicker';
import NavigateButton from './NavigateButton';

const TYPES: { v: FibreType; l: string }[] = [
  { v: 'olt_pop', l: 'OLT / POP' }, { v: 'cabinet', l: 'Cabinet (FDT)' },
  { v: 'splice_closure', l: 'Splice closure' }, { v: 'splitter', l: 'Splitter' },
  { v: 'odp', l: 'ODP' }, { v: 'pole', l: 'Pole' }, { v: 'handhole', l: 'Handhole' },
  { v: 'other', l: 'Other' },
];
const PORTED: FibreType[] = ['odp', 'splitter', 'cabinet'];
const RATIOS = ['', '1:2', '1:4', '1:8', '1:16', '1:32', '1:64'];
const STATUSES: { v: string; l: string }[] = [
  { v: 'ok', l: 'OK' }, { v: 'needs_attention', l: 'Needs attention' }, { v: 'down', l: 'Down' },
];
const CABLES: { v: string; l: string }[] = [
  { v: 'adss', l: 'ADSS (aerial)' }, { v: 'buried', l: 'Buried' }, { v: 'drop', l: 'Drop' },
];
const statusColor = (s: string) => (s === 'down' ? 'red' : s === 'needs_attention' ? 'amber' : 'green') as 'red' | 'amber' | 'green';

const BLANK_POINT = {
  type: 'odp' as FibreType, label: '', gps_lat: null as number | null, gps_lng: null as number | null,
  status: 'ok', port_capacity: '', splitter_ratio: '', notes: '',
};
const BLANK_SPAN = {
  from_point: '', to_point: '', cable_type: 'adss', fibre_count: '', length_m: '', status: 'ok', notes: '',
};

export default function FibrePlantView({ canDispatch = false }: { canDispatch?: boolean }) {
  const points = useList(() => api.fibre.points.list());
  const spans = useList(() => api.fibre.spans.list());
  const [showPoint, setShowPoint] = useState(false);
  const [showSpan, setShowSpan] = useState(false);
  const [editPoint, setEditPoint] = useState<FibrePoint | null>(null);
  const [editSpan, setEditSpan] = useState<FibreSpan | null>(null);
  const [point, setPoint] = useState({ ...BLANK_POINT });
  const [span, setSpan] = useState({ ...BLANK_SPAN });
  const [blast, setBlast] = useState<BlastRadius | null>(null);
  const [blastPoint, setBlastPoint] = useState<FibrePoint | null>(null);   // the point the modal is about
  const [nearest, setNearest] = useState<NearestTech[] | null>(null);      // dispatch: closest live techs
  const [dispatching, setDispatching] = useState(false);

  const reloadAll = () => { points.reload(); spans.reload(); };

  // ---- points ------------------------------------------------------------------
  const newPoint = () => { setEditPoint(null); setPoint({ ...BLANK_POINT }); setShowPoint(true); };
  const startEditPoint = (p: FibrePoint) => {
    setEditPoint(p);
    setPoint({
      type: p.type, label: p.label,
      gps_lat: p.gps_lat ? Number(p.gps_lat) : null, gps_lng: p.gps_lng ? Number(p.gps_lng) : null,
      status: p.status, port_capacity: p.port_capacity ? String(p.port_capacity) : '',
      splitter_ratio: p.splitter_ratio, notes: p.notes,
    });
    setShowPoint(true);
  };
  const submitPoint = async (e: FormEvent) => {
    e.preventDefault();
    const body: Partial<FibrePoint> = {
      type: point.type, label: point.label, status: point.status as FibrePoint['status'],
      notes: point.notes,
      gps_lat: point.gps_lat != null ? String(point.gps_lat) : null,
      gps_lng: point.gps_lng != null ? String(point.gps_lng) : null,
      port_capacity: PORTED.includes(point.type) && point.port_capacity ? Number(point.port_capacity) : 0,
      splitter_ratio: point.type === 'splitter' ? point.splitter_ratio : '',
    };
    try {
      if (editPoint) await api.fibre.points.update(editPoint.id, body);
      else await api.fibre.points.create(body);
      toast('success', editPoint ? 'Point updated.' : 'Point added.');
      setShowPoint(false); setEditPoint(null); points.reload();
    } catch (err) {
      toast('error', err instanceof ApiError ? err.message : 'Failed to save the point.');
    }
  };
  const deactivatePoint = async (p: FibrePoint) => {
    if (!window.confirm(`Deactivate ${p.label}? Its spans and customer links are kept and it can be restored.`)) return;
    try { await api.fibre.points.remove(p.id); toast('success', `${p.label} deactivated.`); reloadAll(); }
    catch (err) { toast('error', err instanceof ApiError ? err.message : 'Could not deactivate.'); }
  };
  const restorePoint = async (p: FibrePoint) => {
    try { await api.fibre.points.restore(p.id); toast('success', `${p.label} restored.`); points.reload(); }
    catch (err) { toast('error', err instanceof ApiError ? err.message : 'Could not restore.'); }
  };
  const showBlast = async (p: FibrePoint) => {
    setBlastPoint(p);
    setNearest(null);
    try { setBlast(await api.fibre.points.affected(p.id)); }
    catch (err) { toast('error', err instanceof ApiError ? err.message : 'Could not load affected customers.'); }
    // Dispatchers also get "who's closest to this fault" — a lookup on the point's coordinate.
    if (canDispatch && p.gps_lat && p.gps_lng) {
      api.fleet.nearest(Number(p.gps_lat), Number(p.gps_lng))
        .then((r) => setNearest(r.technicians)).catch(() => setNearest([]));
    }
  };

  const closeBlast = () => { setBlast(null); setBlastPoint(null); setNearest(null); };

  const dispatchNearest = async () => {
    if (!blastPoint?.gps_lat || !blastPoint?.gps_lng) return;
    const lat = Number(blastPoint.gps_lat), lng = Number(blastPoint.gps_lng);
    setDispatching(true);
    try {
      // One click: raise a ticket for the fault, then assign the nearest live technician to it.
      const ticket = await api.tickets.create({ subject: `Fibre fault: ${blastPoint.label}` });
      const res = await api.fleet.dispatch(ticket.id, lat, lng);
      toast('success', `${res.detail} — ${res.distance_km} km away.`);
      closeBlast();
    } catch (err) {
      const msg = err instanceof ApiError
        ? (err.status === 409 ? 'No technician is sharing their location right now.' : err.message)
        : 'Could not dispatch.';
      toast('error', msg);
    } finally {
      setDispatching(false);
    }
  };

  // ---- spans -------------------------------------------------------------------
  const newSpan = () => { setEditSpan(null); setSpan({ ...BLANK_SPAN }); setShowSpan(true); };
  const startEditSpan = (s: FibreSpan) => {
    setEditSpan(s);
    setSpan({
      from_point: String(s.from_point), to_point: String(s.to_point), cable_type: s.cable_type,
      fibre_count: s.fibre_count ? String(s.fibre_count) : '', length_m: s.length_m ? String(s.length_m) : '',
      status: s.status, notes: s.notes,
    });
    setShowSpan(true);
  };
  const submitSpan = async (e: FormEvent) => {
    e.preventDefault();
    const body: Partial<FibreSpan> = {
      from_point: Number(span.from_point), to_point: Number(span.to_point),
      cable_type: span.cable_type as FibreSpan['cable_type'], status: span.status as FibreSpan['status'],
      fibre_count: span.fibre_count ? Number(span.fibre_count) : 0,
      length_m: span.length_m ? Number(span.length_m) : null, notes: span.notes,
    };
    try {
      if (editSpan) await api.fibre.spans.update(editSpan.id, body);
      else await api.fibre.spans.create(body);
      toast('success', editSpan ? 'Span updated.' : 'Span added.');
      setShowSpan(false); setEditSpan(null); spans.reload();
    } catch (err) {
      toast('error', err instanceof ApiError ? err.message : 'Failed to save the span.');
    }
  };
  const deactivateSpan = async (s: FibreSpan) => {
    if (!window.confirm(`Deactivate the ${s.from_label} → ${s.to_label} span?`)) return;
    try { await api.fibre.spans.remove(s.id); toast('success', 'Span deactivated.'); spans.reload(); }
    catch (err) { toast('error', err instanceof ApiError ? err.message : 'Could not deactivate.'); }
  };

  const pointRows = (points.rows ?? []);
  const placedPoints = pointRows.filter((p) => p.is_active);

  return (
    <div className="space-y-6">
      <ViewHeader
        icon={<Waypoints className="h-4.5 w-4.5" />}
        title="Fibre Plant"
        subtitle="Your ADSS outside plant: points (OLT, splitters, ODPs, poles…) and the spans that connect them. Capacity is counted live; a fault's blast radius shows who goes offline."
      >
        <Btn onClick={newPoint}><Plus className="h-3.5 w-3.5" /> Point</Btn>
        <Btn onClick={newSpan}><Plus className="h-3.5 w-3.5" /> Span</Btn>
        <RefreshBtn onClick={reloadAll} spinning={points.refreshing || spans.refreshing} />
      </ViewHeader>

      {showPoint && (
        <Panel title={editPoint ? `Edit ${editPoint.label}` : 'Add fibre point'}>
          <form onSubmit={submitPoint} className="grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
            <Field label="Type">
              <select value={point.type} onChange={(e) => setPoint({ ...point, type: e.target.value as FibreType })} className={inputCls}>
                {TYPES.map((t) => <option key={t.v} value={t.v}>{t.l}</option>)}
              </select>
            </Field>
            <Field label="Label"><input required value={point.label} onChange={(e) => setPoint({ ...point, label: e.target.value })} className={inputCls} placeholder="e.g. ODP-07" /></Field>
            <Field label="Status">
              <select value={point.status} onChange={(e) => setPoint({ ...point, status: e.target.value })} className={inputCls}>
                {STATUSES.map((s) => <option key={s.v} value={s.v}>{s.l}</option>)}
              </select>
            </Field>
            {PORTED.includes(point.type) && (
              <Field label="Ports / capacity"><input type="number" min="0" value={point.port_capacity} onChange={(e) => setPoint({ ...point, port_capacity: e.target.value })} className={inputCls} placeholder="e.g. 16" /></Field>
            )}
            {point.type === 'splitter' && (
              <Field label="Split ratio">
                <select value={point.splitter_ratio} onChange={(e) => setPoint({ ...point, splitter_ratio: e.target.value })} className={inputCls}>
                  {RATIOS.map((r) => <option key={r} value={r}>{r || '—'}</option>)}
                </select>
              </Field>
            )}
            <Field label="Notes" className="md:col-span-2"><input value={point.notes} onChange={(e) => setPoint({ ...point, notes: e.target.value })} className={inputCls} /></Field>
            <div className="md:col-span-4">
              <label className="text-[11px] font-mono uppercase text-[#141414]/50 block mb-1">Location — drop a pin (or use your location on-site)</label>
              <MapPicker
                lat={point.gps_lat} lng={point.gps_lng}
                onChange={(la, ln) => setPoint((p) => ({
                  ...p, gps_lat: Number.isFinite(la) ? la : null, gps_lng: Number.isFinite(ln) ? ln : null,
                }))}
              />
            </div>
            <div className="flex gap-2">
              <Btn type="submit" variant="green">{editPoint ? 'Save' : 'Add'}</Btn>
              <Btn type="button" variant="outline" onClick={() => { setShowPoint(false); setEditPoint(null); }}>Cancel</Btn>
            </div>
          </form>
        </Panel>
      )}

      {showSpan && (
        <Panel title={editSpan ? 'Edit span' : 'Connect a span'}>
          <form onSubmit={submitSpan} className="grid grid-cols-1 md:grid-cols-6 gap-3 items-end">
            <Field label="From (OLT-side)">
              <select required value={span.from_point} onChange={(e) => setSpan({ ...span, from_point: e.target.value })} className={inputCls}>
                <option value="">Select…</option>
                {placedPoints.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
              </select>
            </Field>
            <Field label="To (customer-side)">
              <select required value={span.to_point} onChange={(e) => setSpan({ ...span, to_point: e.target.value })} className={inputCls}>
                <option value="">Select…</option>
                {placedPoints.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
              </select>
            </Field>
            <Field label="Cable">
              <select value={span.cable_type} onChange={(e) => setSpan({ ...span, cable_type: e.target.value })} className={inputCls}>
                {CABLES.map((c) => <option key={c.v} value={c.v}>{c.l}</option>)}
              </select>
            </Field>
            <Field label="Cores"><input type="number" min="0" value={span.fibre_count} onChange={(e) => setSpan({ ...span, fibre_count: e.target.value })} className={inputCls} placeholder="24" /></Field>
            <Field label="Length (m)"><input type="number" min="0" value={span.length_m} onChange={(e) => setSpan({ ...span, length_m: e.target.value })} className={inputCls} /></Field>
            <Field label="Status">
              <select value={span.status} onChange={(e) => setSpan({ ...span, status: e.target.value })} className={inputCls}>
                {STATUSES.map((s) => <option key={s.v} value={s.v}>{s.l}</option>)}
              </select>
            </Field>
            <div className="flex gap-2 md:col-span-6">
              <Btn type="submit" variant="green">{editSpan ? 'Save' : 'Add'}</Btn>
              <Btn type="button" variant="outline" onClick={() => { setShowSpan(false); setEditSpan(null); }}>Cancel</Btn>
            </div>
          </form>
        </Panel>
      )}

      {/* ---- points table ---- */}
      <TableShell
        headers={['Point', 'Type', 'Status', 'Capacity', 'Location', '']}
        loading={points.rows === null}
        error={points.error}
        empty="No fibre points yet — add your OLT, then splitters and ODPs."
      >
        {pointRows.map((p) => (
          <tr key={p.id} className={`hover:bg-[#f0efec]/40 transition ${!p.is_active ? 'opacity-50' : ''}`}>
            <td className={`${tdCls} font-medium`}>{p.label}{p.notes && <span className="ml-2 text-[11px] text-[#141414]/45">— {p.notes}</span>}</td>
            <td className={tdCls}><Badge color="blue">{p.type_display}</Badge></td>
            <td className={tdCls}><Badge color={statusColor(p.status)}>{p.status.replace('_', ' ')}</Badge></td>
            <td className={tdCls}>
              {p.port_capacity ? (
                <span className="flex items-center gap-2">
                  <span className="w-16 h-2 bg-[#141414]/10"><span className="block h-full" style={{ width: `${Math.min(100, (p.used / p.port_capacity) * 100)}%`, background: p.free === 0 ? '#B22222' : (p.used / p.port_capacity) >= 0.85 ? '#B26B00' : '#228B22' }} /></span>
                  <span className="font-mono text-[11px]">{p.used}/{p.port_capacity}{p.splitter_ratio ? ` · ${p.splitter_ratio}` : ''}</span>
                </span>
              ) : <span className="text-[#141414]/40">—</span>}
            </td>
            <td className={`${tdCls} font-mono text-[11px]`}>{p.gps_lat && p.gps_lng ? `${Number(p.gps_lat).toFixed(4)}, ${Number(p.gps_lng).toFixed(4)}` : <span className="text-[#B26B00]">needs a pin</span>}</td>
            <td className={tdCls}>
              <div className="flex gap-1.5">
                <NavigateButton lat={p.gps_lat ? Number(p.gps_lat) : null} lng={p.gps_lng ? Number(p.gps_lng) : null} label={p.label} compact />
                <Btn variant="outline" onClick={() => showBlast(p)} title="Who's affected if this fails"><Zap className="h-3.5 w-3.5" /></Btn>
                {p.is_active ? (
                  <>
                    <Btn variant="outline" onClick={() => startEditPoint(p)} title="Edit"><Pencil className="h-3.5 w-3.5" /></Btn>
                    <Btn variant="danger" onClick={() => deactivatePoint(p)} title="Deactivate"><Trash2 className="h-3.5 w-3.5" /></Btn>
                  </>
                ) : (
                  <Btn variant="outline" onClick={() => restorePoint(p)} title="Restore"><RotateCcw className="h-3.5 w-3.5" /></Btn>
                )}
              </div>
            </td>
          </tr>
        ))}
      </TableShell>

      {/* ---- spans table ---- */}
      <TableShell
        headers={['Span', 'Cable', 'Cores', 'Length', 'Status', '']}
        loading={spans.rows === null}
        error={spans.error}
        empty="No spans yet — connect two points to draw the route."
      >
        {(spans.rows ?? []).map((s) => (
          <tr key={s.id} className={`hover:bg-[#f0efec]/40 transition ${!s.is_active ? 'opacity-50' : ''}`}>
            <td className={`${tdCls} font-medium`}><Cable className="h-3.5 w-3.5 inline mr-1.5 text-[#0E7490]" />{s.from_label} → {s.to_label}</td>
            <td className={tdCls}><Badge color="gray">{s.cable_type}</Badge></td>
            <td className={`${tdCls} font-mono text-center`}>{s.fibre_count || '—'}</td>
            <td className={`${tdCls} font-mono`}>{s.length_m ? `${s.length_m} m` : '—'}</td>
            <td className={tdCls}><Badge color={statusColor(s.status)}>{s.status.replace('_', ' ')}</Badge></td>
            <td className={tdCls}>
              <div className="flex gap-1.5">
                <Btn variant="outline" onClick={() => startEditSpan(s)} title="Edit"><Pencil className="h-3.5 w-3.5" /></Btn>
                <Btn variant="danger" onClick={() => deactivateSpan(s)} title="Deactivate"><Trash2 className="h-3.5 w-3.5" /></Btn>
              </div>
            </td>
          </tr>
        ))}
      </TableShell>

      <p className="text-[11px] font-mono text-[#141414]/50">{placedPoints.length} active points · {(spans.rows ?? []).filter((s) => s.is_active).length} spans</p>

      {/* ---- blast-radius modal ---- */}
      {blast && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#141414]/40 p-4" onClick={closeBlast}>
          <div className="bg-white border border-[#141414] w-full max-w-lg max-h-[85vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-[#141414] px-4 py-3">
              <h3 className="font-mono font-bold uppercase text-sm flex items-center gap-2"><Zap className="h-4 w-4 text-[#B26B00]" /> Blast radius — {blast.point.label}</h3>
              <button onClick={closeBlast} className="cursor-pointer"><X className="h-4 w-4" /></button>
            </div>
            <div className="p-4">
              <p className="text-sm text-[#141414]/70 mb-3">
                A fault here takes <b>{blast.count}</b> customer{blast.count === 1 ? '' : 's'} offline (this point and everything downstream).
              </p>
              {blast.count === 0 ? (
                <p className="text-sm text-[#141414]/50">No customers are fed from here yet.</p>
              ) : (
                <table className="w-full text-sm">
                  <thead><tr className="text-left font-mono text-[10px] uppercase text-[#141414]/50"><th className="py-1">Customer</th><th>Account</th><th>Phone</th></tr></thead>
                  <tbody>
                    {blast.clients.map((c) => (
                      <tr key={c.id} className="border-t border-[#141414]/10">
                        <td className="py-1.5">{c.full_name}</td>
                        <td className="font-mono text-xs">{c.account_number}</td>
                        <td className="font-mono text-xs">{c.phone || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}

              {/* Dispatch: closest live technicians to this fault (dispatchers only). */}
              {canDispatch && (
                <div className="mt-4 pt-3 border-t border-[#141414]/15">
                  <div className="flex items-center justify-between mb-2">
                    <span className="text-[11px] font-mono uppercase tracking-wider text-[#141414]/50 flex items-center gap-1.5"><HardHat className="h-3.5 w-3.5" /> Nearest technicians</span>
                    {blastPoint?.gps_lat && blastPoint?.gps_lng ? (
                      <Btn variant="green" onClick={dispatchNearest} disabled={dispatching || !(nearest && nearest.length)}>
                        {dispatching ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
                        Dispatch nearest
                      </Btn>
                    ) : (
                      <span className="text-[11px] text-[#B26B00] font-mono">this point needs a pin to dispatch</span>
                    )}
                  </div>
                  {nearest === null ? (
                    <p className="text-xs text-[#141414]/40 font-mono"><Loader2 className="h-3 w-3 animate-spin inline mr-1" /> finding…</p>
                  ) : nearest.length === 0 ? (
                    <p className="text-xs text-[#141414]/50">No technician is sharing their location right now.</p>
                  ) : (
                    <div className="space-y-1">
                      {nearest.slice(0, 5).map((t, i) => (
                        <div key={t.technician_id} className="flex items-center gap-2 text-xs">
                          <span className="font-mono text-[#141414]/40 w-4">{i + 1}.</span>
                          <span className="font-medium">{t.name || t.phone}</span>
                          <span className="font-mono text-[#059669]">{t.distance_km} km</span>
                          <span className="ml-auto"><NavigateButton lat={Number(t.lat)} lng={Number(t.lng)} label={t.name} compact /></span>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
