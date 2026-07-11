import { useState, type FormEvent } from 'react';
import { Router as RouterIcon, Plus, Plug, RefreshCw, Copy, Check, Loader2, X } from 'lucide-react';
import { api, ApiRouter } from '../api/client';
import {
  Badge, Btn, Field, inputCls, Panel, RefreshBtn, TableShell, tdCls, toast, useList, ViewHeader, fmtDateTime,
} from './ui';

export default function RoutersView() {
  const [showAdd, setShowAdd] = useState(false);
  const [name, setName] = useState('');
  const [busy, setBusy] = useState(false);
  const [scriptFor, setScriptFor] = useState<ApiRouter | null>(null);
  const [script, setScript] = useState('');
  const [copied, setCopied] = useState(false);
  const [testing, setTesting] = useState<number | null>(null);
  const { rows, error, reload } = useList(() => api.routers.list());

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
        <RefreshBtn onClick={reload} />
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

      <TableShell
        headers={['Site', 'Status', 'RouterOS', 'Last seen', 'Last sync', '']}
        loading={rows === null}
        error={error}
        empty="No routers yet — add your first site to generate its setup script."
      >
        {(rows ?? []).map((r) => (
          <tr key={r.id} className="hover:bg-[#f0efec]/40 transition">
            <td className={`${tdCls} font-bold`}>
              {r.name}
              {r.management_host && <span className="block text-[11px] font-mono text-[#141414]/50">{r.management_host}</span>}
            </td>
            <td className={tdCls}>
              {r.needs_onboarding ? (
                <Badge color="amber">needs setup</Badge>
              ) : (
                <Badge color={r.status === 'online' ? 'green' : r.status === 'offline' ? 'red' : 'gray'}>
                  {r.status}
                </Badge>
              )}
            </td>
            <td className={`${tdCls} font-mono`}>{r.routeros_version || '—'}</td>
            <td className={`${tdCls} font-mono whitespace-nowrap`}>{fmtDateTime(r.last_seen_at)}</td>
            <td className={`${tdCls} font-mono whitespace-nowrap`}>{fmtDateTime(r.last_sync_at)}</td>
            <td className={`${tdCls} whitespace-nowrap space-x-1.5`}>
              {r.needs_onboarding ? (
                // Never set up, OR factory-reset (API user wiped) — same remedy.
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
                  <button
                    onClick={() => openScript(r)}
                    className="text-[11px] font-mono underline text-[#141414]/50 hover:text-[#141414]"
                    title="Show the setup script again"
                  >
                    script
                  </button>
                </>
              )}
            </td>
          </tr>
        ))}
      </TableShell>

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
    </div>
  );
}
