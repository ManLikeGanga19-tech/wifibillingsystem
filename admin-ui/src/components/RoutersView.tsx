import { useEffect, useState, type FormEvent } from 'react';
import { Router as RouterIcon, Plus, Plug, RefreshCw, Copy, Check, Loader2, X, Cpu, Pencil, Trash2, Activity, AlertTriangle } from 'lucide-react';
import { api, ApiError, ApiRouter, DeviceInfo, RouterDiagnostics, RouterHealthTrend } from '../api/client';
import MapPicker from './MapPicker';
import DataTable, { type Column } from './DataTable';
import { Badge, Btn, Field, inputCls, Panel, toast, ViewHeader, fmtDateTime } from './ui';

function mb(bytes: number | null): string {
  return bytes === null ? '—' : `${Math.round(bytes / 1048576)} MB`;
}

export default function RoutersView() {
  const [showAdd, setShowAdd] = useState(false);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [scriptFor, setScriptFor] = useState<ApiRouter | null>(null);
  const [script, setScript] = useState('');
  const [copied, setCopied] = useState(false);
  const [testing, setTesting] = useState<number | null>(null);
  const [infoFor, setInfoFor] = useState<ApiRouter | null>(null);
  const [info, setInfo] = useState<DeviceInfo | null>(null);
  const [diagFor, setDiagFor] = useState<ApiRouter | null>(null);
  const [editRouter, setEditRouter] = useState<ApiRouter | null>(null);
  const [refresh, setRefresh] = useState(0);
  const reload = () => setRefresh((n) => n + 1);

  const deleteRouter = async (r: ApiRouter) => {
    if (!confirm(`Delete router "${r.name}"? Clients and sessions on it must be moved first.`)) return;
    try {
      await api.routers.remove(r.id);
      toast('success', `${r.name} deleted.`);
      reload();
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'Could not delete the router.');
    }
  };

  const openInfo = async (r: ApiRouter) => {
    setInfoFor(r);
    setInfo(null);
    try {
      setInfo(await api.routers.deviceInfo(r.id));
    } catch (e) {
      toast('error', e instanceof Error ? e.message : 'Could not reach the router.');
      setInfoFor(null);
    }
  };

  const addRouter = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    try {
      const router = await api.routers.create({ name });
      toast('success', `Site "${name}" created. Now paste the setup script into its MikroTik.`);
      setName('');
      setShowAdd(false);
      reload();
      openScript(router);
    } catch {
      toast('error', 'Failed to create router.');
    } finally {
      setBusy(false);
    }
  };

  const openScript = async (router: ApiRouter) => {
    setScriptFor(router);
    setScript('');
    setCopied(false);
    try {
      const r = await api.routers.setupScript(router.id);
      setScript(r.script);
    } catch {
      toast('error', 'Could not load the setup script.');
    }
  };

  const copyScript = async () => {
    try {
      await navigator.clipboard.writeText(script);
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    } catch {
      toast('warning', 'Could not copy automatically — select the text and copy manually.');
    }
  };

  const test = async (router: ApiRouter) => {
    setTesting(router.id);
    try {
      const r = await api.routers.testConnection(router.id);
      toast(r.ok ? 'success' : 'error', r.ok ? `${router.name} is reachable.` : `${router.name} did not respond${r.detail ? `: ${r.detail}` : '.'}`);
    } catch (e) {
      toast('error', e instanceof Error ? e.message : 'Test failed.');
    } finally {
      setTesting(null);
      reload();
    }
  };

  const resync = async (router: ApiRouter) => {
    try {
      await api.routers.resync(router.id);
      toast('success', `Re-sync queued for ${router.name}.`);
    } catch (e) {
      toast('error', e instanceof Error ? e.message : 'Re-sync failed.');
    }
  };

  function routerColumns(): Column<ApiRouter>[] {
    return [
      {
        header: 'Site', sortKey: 'name',
        render: (r) => (
          <span className="font-bold">
            {r.name}
            {r.management_host && <span className="block text-[11px] font-mono text-[#141414]/50">{r.management_host}</span>}
          </span>
        ),
      },
      {
        header: 'Model',
        render: (r) => r.board_name ? (
          <>
            <span className="font-mono">{r.board_name}</span>
            {r.serial_number && <span className="block text-[11px] font-mono text-[#141414]/50">SN {r.serial_number}</span>}
          </>
        ) : <span className="text-[#141414]/40">—</span>,
      },
      {
        header: 'Status', sortKey: 'status',
        render: (r) => r.needs_onboarding
          ? <Badge color="amber">needs setup</Badge>
          : <Badge color={r.status === 'online' ? 'green' : r.status === 'offline' ? 'red' : 'gray'}>{r.status}</Badge>,
      },
      { header: 'RouterOS', render: (r) => <span className="font-mono">{r.routeros_version || '—'}</span> },
      { header: 'Last seen', sortKey: 'last_seen_at', render: (r) => <span className="font-mono whitespace-nowrap">{fmtDateTime(r.last_seen_at)}</span> },
      { header: 'Last sync', render: (r) => <span className="font-mono whitespace-nowrap">{fmtDateTime(r.last_sync_at)}</span> },
      {
        header: '', className: 'whitespace-nowrap space-x-1.5',
        render: (r) => (
          <>
            {r.needs_onboarding ? (
              <Btn variant="dark" onClick={() => openScript(r)}>
                <Copy className="h-3.5 w-3.5" /> {r.enrolled_at ? 'Re-run setup' : 'Setup script'}
              </Btn>
            ) : (
              <>
                <Btn variant="outline" onClick={() => test(r)} disabled={testing === r.id}>
                  <Plug className="h-3.5 w-3.5" />
                  {testing === r.id ? 'Testing…' : 'Test'}
                </Btn>
                <Btn variant="outline" onClick={() => resync(r)} title="Push any missing active sessions back onto the router">
                  <RefreshCw className="h-3.5 w-3.5" /> Re-sync
                </Btn>
                <Btn variant="outline" onClick={() => openInfo(r)} title="Live device details">
                  <Cpu className="h-3.5 w-3.5" /> Details
                </Btn>
                <Btn variant="outline" onClick={() => setDiagFor(r)} title="Why are clients slow? Read-only diagnostics">
                  <Activity className="h-3.5 w-3.5" /> Diagnose
                </Btn>
                <button
                  onClick={() => openScript(r)}
                  className="text-[11px] font-mono underline text-[#141414]/50 hover:text-[#141414]"
                  title="Show the setup script again"
                >
                  script
                </button>
              </>
            )}
            <Btn variant="outline" onClick={() => setEditRouter(r)} title="Edit router"><Pencil className="h-3.5 w-3.5" /></Btn>
            <Btn variant="danger" onClick={() => deleteRouter(r)} title="Delete router"><Trash2 className="h-3.5 w-3.5" /></Btn>
          </>
        ),
      },
    ];
  }

  return (
    <div className="space-y-5 text-[#141414]">
      <ViewHeader
        icon={<RouterIcon className="h-4.5 w-4.5" />}
        title="MikroTik Routers"
        subtitle="Add a site, paste the generated script into the router once, and it configures itself and connects back automatically."
      >
        <Btn onClick={() => setShowAdd(!showAdd)}>
          <Plus className="h-3.5 w-3.5" /> Add Router
        </Btn>
      </ViewHeader>

      {showAdd && (
        <Panel title="Add a new site">
          <form onSubmit={addRouter} className="flex flex-col sm:flex-row gap-3 sm:items-end">
            <Field label="Site name" className="flex-1">
              <input required autoFocus value={name} onChange={(e) => setName(e.target.value)} className={inputCls} placeholder="e.g. Kibera Site A" />
            </Field>
            <Btn type="submit" variant="green" disabled={busy}>
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
              Create & get script
            </Btn>
          </form>
        </Panel>
      )}

      <DataTable<ApiRouter>
        fetcher={(q) => api.routers.list(q)}
        columns={routerColumns()}
        rowKey={(r) => r.id}
        searchPlaceholder="Search site / host / serial…"
        emptyMessage="No routers yet — add your first site to generate its setup script."
        initialOrdering="name"
        refreshSignal={refresh}
      />

      {/* Script modal */}
      {scriptFor && (
        <div className="fixed inset-0 z-50 bg-[#141414]/50 flex items-center justify-center p-4" onClick={() => setScriptFor(null)}>
          <div className="bg-white border border-[#141414] w-full max-w-2xl max-h-[85vh] flex flex-col" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b border-[#141414]">
              <h3 className="font-bold font-mono uppercase text-sm">Setup script — {scriptFor.name}</h3>
              <button onClick={() => setScriptFor(null)} className="cursor-pointer"><X className="h-4 w-4" /></button>
            </div>
            <div className="p-4 space-y-3 overflow-y-auto">
              <ol className="text-xs font-mono text-[#141414]/70 space-y-1 list-decimal list-inside">
                <li>Open the router in Winbox → <b>New Terminal</b> (needs RouterOS v7).</li>
                <li>Copy the script below and paste the whole thing into the terminal.</li>
                <li>The router configures itself and appears here as <b>Online</b> within a minute.</li>
              </ol>
              {script ? (
                <pre className="bg-[#141414] text-[#E4E3E0] text-[11px] font-mono p-3 overflow-x-auto max-h-72 whitespace-pre">{script}</pre>
              ) : (
                <div className="flex justify-center py-10"><Loader2 className="h-6 w-6 animate-spin text-[#141414]/40" /></div>
              )}
            </div>
            <div className="p-4 border-t border-[#141414] flex justify-between items-center">
              <span className="text-[11px] font-mono text-[#141414]/50">Safe to paste more than once.</span>
              <Btn variant="green" onClick={copyScript} disabled={!script}>
                {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                {copied ? 'Copied!' : 'Copy script'}
              </Btn>
            </div>
          </div>
        </div>
      )}

      {/* Device details modal */}
      {infoFor && (
        <div className="fixed inset-0 z-50 bg-[#141414]/50 flex items-center justify-center p-4" onClick={() => setInfoFor(null)}>
          <div className="bg-white border border-[#141414] w-full max-w-md" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between p-4 border-b border-[#141414]">
              <h3 className="font-bold font-mono uppercase text-sm flex items-center gap-2">
                <Cpu className="h-4 w-4" /> {infoFor.name}
              </h3>
              <button onClick={() => setInfoFor(null)} className="cursor-pointer"><X className="h-4 w-4" /></button>
            </div>
            {info ? (
              <div className="p-4 font-mono text-xs">
                <div className="grid grid-cols-2 gap-y-2">
                  <InfoRow label="Model" value={info.board_name} />
                  <InfoRow label="Serial" value={info.serial_number} />
                  <InfoRow label="RouterOS" value={info.routeros_version} />
                  <InfoRow label="Architecture" value={info.architecture} />
                  <InfoRow label="Identity" value={info.identity_name} />
                  <InfoRow label="Uptime" value={info.uptime} />
                  <InfoRow label="CPU load" value={info.cpu_load === null ? '—' : `${info.cpu_load}%`} />
                  <InfoRow label="Active users" value={info.active_users === null ? '—' : String(info.active_users)} />
                  <InfoRow label="Free memory" value={mb(info.free_memory)} />
                  <InfoRow label="Total memory" value={mb(info.total_memory)} />
                </div>
                <p className="text-[11px] text-[#141414]/50 mt-4">Live from the router just now.</p>
              </div>
            ) : (
              <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-[#141414]/40" /></div>
            )}
          </div>
        </div>
      )}
      {diagFor && <DiagnoseModal router={diagFor} onClose={() => setDiagFor(null)} />}
      {editRouter && (
        <EditRouterModal
          router={editRouter}
          onClose={() => setEditRouter(null)}
          onSaved={() => { setEditRouter(null); reload(); }}
        />
      )}
    </div>
  );
}

/**
 * Read-only 'why are my clients slow?' panel. Pulls the live diagnostics (CPU, MSS clamp,
 * queues, throughput, oversubscription) plus the 24h CPU peak from the trend, and flags the
 * likely cause. Touches nothing on the router.
 */
function DiagnoseModal({ router, onClose }: { router: ApiRouter; onClose: () => void }) {
  const [diag, setDiag] = useState<RouterDiagnostics | null>(null);
  const [trend, setTrend] = useState<RouterHealthTrend | null>(null);
  const [error, setError] = useState('');
  const [healing, setHealing] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let live = true;
    setDiag(null);
    api.routers.diagnose(router.id)
      .then((d) => { if (live) setDiag(d); })
      .catch((e) => { if (live) setError(e instanceof Error ? e.message : 'Could not reach the router.'); });
    api.routers.healthTrend(router.id).then((t) => { if (live) setTrend(t); }).catch(() => {});
    return () => { live = false; };
  }, [router.id, reloadKey]);

  const healClamp = async () => {
    setHealing(true);
    try {
      const r = await api.routers.healMssClamp(router.id);
      toast('success', r.detail);
      setReloadKey((k) => k + 1);  // re-diagnose so the panel shows it present now
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'Could not restore the clamp.');
    } finally {
      setHealing(false);
    }
  };

  const hits: string[] = [];
  if (diag) {
    if (diag.cpu_load !== null && diag.cpu_load >= 80)
      hits.push(`Router CPU at ${diag.cpu_load}% — the board is the bottleneck; everything slows regardless of per-client limits.`);
    if (diag.mss_clamp_present === false)
      hits.push('The TCP-MSS clamp is missing — PPPoE clients hit a PMTU black hole (HTTPS and big pages crawl / half-load). It self-heals nightly, or re-provision a client to restore it now.');
    if (diag.oversubscription_ratio !== null && diag.oversubscription_ratio >= 10)
      hits.push(`Oversubscription ~${diag.oversubscription_ratio}× — at peak the WAN saturates and every client slows. Raise the uplink or add a fair-queue (PCQ) parent queue.`);
  }
  if (trend?.peak_cpu_24h != null && trend.peak_cpu_24h >= 90)
    hits.push(`CPU peaked at ${trend.peak_cpu_24h}% in the last 24h — a peak-hour saturation spike even if it looks calm right now.`);

  const clamp = diag?.mss_clamp_present;

  return (
    <div className="fixed inset-0 z-50 bg-[#141414]/50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white border border-[#141414] w-full max-w-lg max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b border-[#141414]">
          <h3 className="font-bold font-mono uppercase text-sm flex items-center gap-2">
            <Activity className="h-4 w-4" /> Diagnose — {router.name}
          </h3>
          <button onClick={onClose} className="cursor-pointer"><X className="h-4 w-4" /></button>
        </div>

        {error && (
          <p className="m-4 border border-[#B22222] bg-[#B22222]/5 px-3 py-2 text-xs font-mono text-[#B22222] flex items-center gap-2">
            <AlertTriangle className="h-4 w-4" /> {error}
          </p>
        )}

        {!error && !diag && (
          <div className="flex justify-center py-12"><Loader2 className="h-6 w-6 animate-spin text-[#141414]/40" /></div>
        )}

        {diag && (
          <div className="p-4 space-y-4 font-mono text-xs">
            <div className="grid grid-cols-2 gap-y-2">
              <InfoRow label="CPU load" value={diag.cpu_load === null ? '—' : `${diag.cpu_load}%`} />
              <InfoRow label="Peak CPU (24h)" value={trend?.peak_cpu_24h == null ? '—' : `${trend.peak_cpu_24h}%`} />
              <InfoRow label="Memory used" value={diag.mem_used_pct === null ? '—' : `${diag.mem_used_pct}%`} />
              <InfoRow label="Uptime" value={diag.uptime || '—'} />
              <InfoRow label="PPPoE online" value={diag.pppoe_active_count === null ? '—' : String(diag.pppoe_active_count)} />
              <InfoRow label="Simple queues" value={diag.simple_queue_count === null ? '—' : String(diag.simple_queue_count)} />
            </div>

            {/* MSS clamp */}
            <div className={`flex items-center gap-2 border px-3 py-2 ${clamp === false ? 'border-[#B22222] bg-[#B22222]/5 text-[#B22222]' : 'border-[#141414]/15'}`}>
              {clamp === true && <Check className="h-3.5 w-3.5 text-[#228B22]" />}
              {clamp === false && <AlertTriangle className="h-3.5 w-3.5" />}
              <span className="flex-1">
                TCP-MSS clamp:{' '}
                <b>{clamp === true ? 'present' : clamp === false ? 'MISSING' : 'unknown'}</b>
              </span>
              {clamp === false && (
                <Btn variant="green" onClick={healClamp} disabled={healing}>
                  {healing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
                  Restore now
                </Btn>
              )}
            </div>

            {/* Oversubscription */}
            <div className="border border-[#141414]/15 px-3 py-2 space-y-1">
              <div className="flex justify-between">
                <span className="text-[#141414]/60 uppercase text-[11px]">Sold vs uplink</span>
                <span>
                  {diag.sold_download_mbps} Mbps sold ·{' '}
                  {diag.uplink_mbps ? `${diag.uplink_mbps} Mbps uplink` : 'uplink not set'}
                </span>
              </div>
              {diag.oversubscription_ratio !== null ? (
                <div className={`text-right font-bold ${diag.oversubscription_ratio >= 10 ? 'text-[#B22222]' : ''}`}>
                  {diag.oversubscription_ratio}× oversubscribed
                </div>
              ) : (
                <div className="text-right text-[11px] text-[#141414]/50">Set the WAN uplink (Edit router) for the ratio.</div>
              )}
            </div>

            {/* Throughput */}
            {diag.top_interfaces.length > 0 && (
              <div>
                <p className="text-[11px] uppercase text-[#141414]/60 mb-1">Live throughput</p>
                <div className="space-y-1">
                  {diag.top_interfaces.map((i) => (
                    <div key={i.name} className="flex justify-between">
                      <span>{i.name}</span>
                      <span>↓{i.rx_mbps.toFixed(2)} ↑{i.tx_mbps.toFixed(2)} Mbps</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {hits.length > 0 ? (
              <div className="border border-[#B22222] bg-[#B22222]/5 p-3 space-y-1.5">
                <p className="font-bold text-[#B22222] uppercase text-[11px]">Likely cause</p>
                {hits.map((h, idx) => (
                  <p key={idx} className="text-[#B22222] leading-relaxed font-sans">• {h}</p>
                ))}
              </div>
            ) : (
              <p className="text-[11px] text-[#141414]/55 font-sans leading-relaxed border-t border-[#141414]/10 pt-3">
                No obvious router-side cause in this snapshot. If clients still report slowness, open
                this again <b>at peak (evening)</b> — contention and CPU saturation only show under load.
              </p>
            )}
            {diag.notes.map((n, idx) => (
              <p key={idx} className="text-[11px] text-[#B26B00]">! {n}</p>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

/**
 * Edit a router's details. Most fields self-fill when the router phones home, so the common
 * edit is a rename; the connection fields are here for a hand-configured router. The password
 * is write-only (never returned) — leave it blank to keep the current one.
 */
function EditRouterModal({
  router,
  onClose,
  onSaved,
}: {
  router: ApiRouter;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState({
    name: router.name,
    management_host: router.management_host,
    api_port: String(router.api_port),
    username: router.username,
    password: '',
    use_tls: router.use_tls,
    verify_tls: router.verify_tls,
    is_active: router.is_active,
    uplink_mbps: router.uplink_mbps != null ? String(router.uplink_mbps) : '',
    gps_lat: router.gps_lat ? Number(router.gps_lat) : (null as number | null),
    gps_lng: router.gps_lng ? Number(router.gps_lng) : (null as number | null),
  });
  const [busy, setBusy] = useState(false);

  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    const body: Partial<ApiRouter> & { password?: string } = {
      name: form.name,
      management_host: form.management_host,
      api_port: Number(form.api_port) || 443,
      username: form.username,
      use_tls: form.use_tls,
      verify_tls: form.verify_tls,
      is_active: form.is_active,
      uplink_mbps: form.uplink_mbps.trim() ? Number(form.uplink_mbps) : null,
      gps_lat: form.gps_lat != null ? String(form.gps_lat) : null,
      gps_lng: form.gps_lng != null ? String(form.gps_lng) : null,
    };
    if (form.password) body.password = form.password; // set-only; blank keeps the current one
    try {
      await api.routers.update(router.id, body);
      toast('success', `${form.name} updated.`);
      onSaved();
    } catch (err) {
      toast('error', err instanceof ApiError ? err.message : 'Could not save the router.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-[#141414]/50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white border border-[#141414] w-full max-w-lg max-h-[92vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b border-[#141414]">
          <h3 className="font-bold font-mono uppercase text-sm">Edit — {router.name}</h3>
          <button onClick={onClose} className="cursor-pointer"><X className="h-4 w-4" /></button>
        </div>
        <form onSubmit={save} className="p-4 grid grid-cols-1 sm:grid-cols-2 gap-3">
          <Field label="Site name" className="sm:col-span-2">
            <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={inputCls} />
          </Field>
          <Field label="Management host">
            <input value={form.management_host} onChange={(e) => setForm({ ...form, management_host: e.target.value })} className={inputCls} placeholder="auto when it phones home" />
          </Field>
          <Field label="API port">
            <input type="number" value={form.api_port} onChange={(e) => setForm({ ...form, api_port: e.target.value })} className={inputCls} />
          </Field>
          <Field label="API username">
            <input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} className={inputCls} />
          </Field>
          <Field label="API password (blank = keep)">
            <input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} className={inputCls} placeholder="••••••" />
          </Field>
          <Field label="WAN uplink (Mbps)" className="sm:col-span-2">
            <input type="number" min="1" value={form.uplink_mbps} onChange={(e) => setForm({ ...form, uplink_mbps: e.target.value })} className={inputCls} placeholder="e.g. 100 — powers the oversubscription check" />
          </Field>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.use_tls} onChange={(e) => setForm({ ...form, use_tls: e.target.checked })} /> Use TLS
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.verify_tls} onChange={(e) => setForm({ ...form, verify_tls: e.target.checked })} /> Verify TLS cert
          </label>
          <label className="flex items-center gap-2 text-sm sm:col-span-2">
            <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} /> Active
          </label>
          <div className="sm:col-span-2">
            <label className="text-[11px] font-mono uppercase text-[#141414]/50 block mb-1">Site location (for the Map)</label>
            <MapPicker
              lat={form.gps_lat} lng={form.gps_lng}
              onChange={(la, ln) => setForm((f) => ({
                ...f, gps_lat: Number.isFinite(la) ? la : null, gps_lng: Number.isFinite(ln) ? ln : null,
              }))}
            />
          </div>
          <div className="sm:col-span-2 flex justify-end gap-2 pt-2 border-t border-[#141414]/15">
            <Btn type="button" variant="outline" onClick={onClose}>Cancel</Btn>
            <Btn type="submit" variant="green" disabled={busy}>{busy ? 'Saving…' : 'Save changes'}</Btn>
          </div>
        </form>
      </div>
    </div>
  );
}

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <>
      <span className="text-[#141414]/50 uppercase text-[11px]">{label}</span>
      <span className="font-bold text-right">{value || '—'}</span>
    </>
  );
}
