import { Fragment, useEffect, useMemo, useState } from 'react';
import { ShieldCheck, Loader2, RotateCcw, Lock, Save } from 'lucide-react';
import {
  api, ApiError, ROLE_META,
  type AccessControlData, type Capability, type Role, type RoleState,
} from '../api/client';
import { toast } from './ui';

// Column order for the editable roles.
const COLS: Role[] = ['tenant_admin', 'tenant_care', 'tenant_technician'];

type CapMap = Record<string, Set<Capability>>;

function toMap(roles: RoleState[]): CapMap {
  const m: CapMap = {};
  for (const r of roles) m[r.role] = new Set(r.capabilities);
  return m;
}

export default function AccessControlView() {
  const [data, setData] = useState<AccessControlData | null>(null);
  const [error, setError] = useState('');
  const [caps, setCaps] = useState<CapMap>({});
  const [saved, setSaved] = useState<CapMap>({});   // last-persisted snapshot, to detect changes
  const [busy, setBusy] = useState(false);

  const load = () => {
    api.rbac.get()
      .then((d) => { setData(d); setCaps(toMap(d.roles)); setSaved(toMap(d.roles)); })
      .catch(() => setError('Could not load access control.'));
  };
  useEffect(load, []);

  // Which roles have unsaved changes.
  const dirtyRoles = useMemo(() => {
    return COLS.filter((role) => {
      const a = caps[role] ?? new Set();
      const b = saved[role] ?? new Set();
      return a.size !== b.size || [...a].some((c) => !b.has(c));
    });
  }, [caps, saved]);

  const grouped = useMemo(() => {
    const g: { group: string; items: AccessControlData['catalog'] }[] = [];
    for (const entry of data?.catalog ?? []) {
      let bucket = g.find((x) => x.group === entry.group);
      if (!bucket) { bucket = { group: entry.group, items: [] }; g.push(bucket); }
      bucket.items.push(entry);
    }
    return g;
  }, [data]);

  const toggle = (role: Role, cap: Capability) => {
    setCaps((prev) => {
      const next = { ...prev, [role]: new Set(prev[role]) };
      if (next[role].has(cap)) next[role].delete(cap); else next[role].add(cap);
      return next;
    });
  };

  const save = async () => {
    setBusy(true);
    try {
      for (const role of dirtyRoles) {
        await api.rbac.setRole(role, [...(caps[role] ?? new Set())]);
      }
      toast('success', 'Permissions saved. Staff see the change on their next sign-in.');
      load();
    } catch (err) {
      toast('error', err instanceof ApiError ? err.message : 'Could not save permissions.');
    } finally {
      setBusy(false);
    }
  };

  const reset = async (role: Role) => {
    if (!window.confirm(`Reset ${ROLE_META[role].label} to the recommended permissions?`)) return;
    setBusy(true);
    try {
      await api.rbac.resetRole(role);
      toast('success', `${ROLE_META[role].label} reset to recommended.`);
      load();
    } catch (err) {
      toast('error', err instanceof ApiError ? err.message : 'Could not reset.');
    } finally {
      setBusy(false);
    }
  };

  if (error) return <div className="text-sm text-[#B22222]">{error}</div>;
  if (!data) return <div className="text-sm text-[#141414]/50 flex items-center gap-2"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</div>;

  const roleState = (role: Role) => data.roles.find((r) => r.role === role);

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-lg font-bold font-mono uppercase tracking-wide flex items-center gap-2">
            <ShieldCheck className="h-5 w-5" /> Access Control
          </h1>
          <p className="text-sm text-[#141414]/60 max-w-2xl">
            Decide what each role can do. Turning a permission off hides that whole area from anyone
            with the role. The <b>Owner</b> always has full access; withdrawing money and editing
            these permissions stay with the Owner and can't be handed out.
          </p>
        </div>
        <button onClick={save} disabled={busy || dirtyRoles.length === 0}
          className="flex items-center gap-2 px-4 py-2 text-xs font-bold font-mono uppercase border border-[#141414] bg-[#141414] text-white cursor-pointer disabled:opacity-40">
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
          Save{dirtyRoles.length ? ` (${dirtyRoles.length})` : ''}
        </button>
      </div>

      <div className="border border-[#141414] bg-white overflow-x-auto">
        <table className="w-full text-sm min-w-[640px]">
          <thead>
            <tr className="bg-[#E4E3E0] border-b border-[#141414]">
              <th className="text-left px-3 py-2 font-mono text-[10px] uppercase tracking-wider text-[#141414]/60">Permission</th>
              {COLS.map((role) => {
                const st = roleState(role);
                return (
                  <th key={role} className="px-3 py-2 text-center">
                    <div className="flex flex-col items-center gap-1">
                      <span className="text-[10px] font-bold uppercase tracking-wide text-white px-2 py-0.5"
                            style={{ background: ROLE_META[role].color }}>{ROLE_META[role].label}</span>
                      <button onClick={() => reset(role)} disabled={busy || !st?.is_custom} title="Reset to recommended"
                        className="flex items-center gap-1 text-[9px] font-mono uppercase text-[#141414]/50 hover:text-[#141414] disabled:opacity-30 cursor-pointer">
                        <RotateCcw className="h-3 w-3" /> {st?.is_custom ? 'custom' : 'default'}
                      </button>
                    </div>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {grouped.map((grp) => (
              <Fragment key={grp.group}>
                <tr className="bg-[#f0efec]">
                  <td colSpan={COLS.length + 1} className="px-3 py-1.5 font-mono text-[10px] uppercase tracking-widest text-[#141414]/50">{grp.group}</td>
                </tr>
                {grp.items.map((entry) => (
                  <tr key={entry.capability} className="border-t border-[#141414]/10 hover:bg-[#f0efec]/40">
                    <td className="px-3 py-2">{entry.label}</td>
                    {COLS.map((role) => {
                      const on = caps[role]?.has(entry.capability) ?? false;
                      return (
                        <td key={role} className="px-3 py-2 text-center">
                          <input type="checkbox" checked={on} onChange={() => toggle(role, entry.capability)}
                            className="h-4 w-4 accent-[#141414] cursor-pointer" />
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-[11px] text-[#141414]/50 flex items-center gap-1.5 font-mono">
        <Lock className="h-3.5 w-3.5" />
        Withdrawing funds and editing access control are Owner-only and never appear above.
      </p>
    </div>
  );
}
