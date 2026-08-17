import { useCallback, useEffect, useState, type FC, type FormEvent } from 'react';
import {
  UsersRound, UserPlus, Loader2, KeyRound, UserX, UserCheck, ShieldCheck,
} from 'lucide-react';
import { api, ApiError, ROLE_META, type Me, type Role, type StaffMember } from '../api/client';
import { toast } from './ui';

// The only roles an Owner/Admin may hand out here (the server enforces this too).
const ASSIGNABLE: Role[] = ['tenant_admin', 'tenant_care', 'tenant_technician'];

const FIELD = 'w-full border border-[#141414]/40 px-2 py-1.5 text-sm focus:border-[#141414] outline-none';

function RoleBadge({ role }: { role: Role }) {
  const meta = ROLE_META[role];
  return (
    <span className="inline-flex items-center px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide text-white"
          style={{ background: meta.color }}>
      {meta.label}
    </span>
  );
}

interface AddStaffProps {
  onCreated: () => void;
}

function AddStaff({ onCreated }: AddStaffProps) {
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<Role>('tenant_technician');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.staff.create({ name, phone, email: email || undefined, role, password });
      toast('success', `${name || phone} added. They'll set their own password on first login.`);
      onCreated();
    } catch (err) {
      toast('error', err instanceof ApiError ? err.message : 'Could not add that employee.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="border border-[#141414] bg-white p-4 grid gap-3 sm:grid-cols-2">
      <div>
        <label className="block text-[10px] font-mono uppercase tracking-wider text-[#141414]/50 mb-1">Name</label>
        <input className={FIELD} value={name} onChange={(e) => setName(e.target.value)} required />
      </div>
      <div>
        <label className="block text-[10px] font-mono uppercase tracking-wider text-[#141414]/50 mb-1">Phone (their login)</label>
        <input className={FIELD} value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="0712345678" required />
      </div>
      <div>
        <label className="block text-[10px] font-mono uppercase tracking-wider text-[#141414]/50 mb-1">Email (optional)</label>
        <input className={FIELD} type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
      </div>
      <div>
        <label className="block text-[10px] font-mono uppercase tracking-wider text-[#141414]/50 mb-1">Role</label>
        <select className={FIELD} value={role} onChange={(e) => setRole(e.target.value as Role)}>
          {ASSIGNABLE.map((r) => <option key={r} value={r}>{ROLE_META[r].label}</option>)}
        </select>
      </div>
      <div className="sm:col-span-2">
        <label className="block text-[10px] font-mono uppercase tracking-wider text-[#141414]/50 mb-1">Temporary password</label>
        <input className={FIELD} type="text" value={password} onChange={(e) => setPassword(e.target.value)}
          placeholder="At least 8 characters — share it with them once" minLength={8} required />
      </div>
      <div className="sm:col-span-2 flex justify-end">
        <button type="submit" disabled={busy}
          className="flex items-center gap-2 px-4 py-2 text-xs font-bold font-mono uppercase border border-[#141414] bg-[#141414] text-white cursor-pointer disabled:opacity-50">
          {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />} Create login
        </button>
      </div>
    </form>
  );
}

interface StaffRowProps {
  staff: StaffMember;
  isSelf: boolean;
  onChanged: () => void;
}

const StaffRow: FC<StaffRowProps> = ({ staff, isSelf, onChanged }) => {
  const [busy, setBusy] = useState(false);
  const isOwner = staff.role === 'tenant_owner';
  // The owner and your own row are not editable here (the server enforces this too).
  const locked = isOwner || isSelf;

  const run = async (fn: () => Promise<unknown>, ok: string) => {
    setBusy(true);
    try { await fn(); toast('success', ok); onChanged(); }
    catch (err) { toast('error', err instanceof ApiError ? err.message : 'That did not work.'); }
    finally { setBusy(false); }
  };

  const changeRole = (role: Role) =>
    run(() => api.staff.update(staff.id, { role }), `${staff.name || staff.phone} is now ${ROLE_META[role].label}.`);

  const reset = () => {
    const pw = window.prompt(`New temporary password for ${staff.name || staff.phone} (min 8 chars):`);
    if (!pw) return;
    run(() => api.staff.resetPassword(staff.id, pw), 'Password reset — they must change it next login.');
  };

  const toggleActive = () => staff.is_active
    ? run(() => api.staff.offboard(staff.id), `${staff.name || staff.phone} offboarded.`)
    : run(() => api.staff.update(staff.id, { is_active: true }), `${staff.name || staff.phone} reactivated.`);

  return (
    <tr className={`border-t border-[#141414]/10 ${!staff.is_active ? 'opacity-50' : ''}`}>
      <td className="px-3 py-2 font-medium">{staff.name || '—'}{isSelf && <span className="ml-2 text-[10px] text-[#141414]/40">(you)</span>}</td>
      <td className="px-3 py-2 font-mono text-xs">{staff.phone}</td>
      <td className="px-3 py-2">
        {locked ? <RoleBadge role={staff.role} /> : (
          <select disabled={busy} value={staff.role} onChange={(e) => changeRole(e.target.value as Role)}
            className="border border-[#141414]/30 px-1.5 py-1 text-xs bg-white cursor-pointer">
            {ASSIGNABLE.map((r) => <option key={r} value={r}>{ROLE_META[r].label}</option>)}
          </select>
        )}
      </td>
      <td className="px-3 py-2">
        {staff.is_active
          ? <span className="inline-flex items-center gap-1 text-[11px] text-[#228B22] font-mono"><ShieldCheck className="h-3.5 w-3.5" />Active</span>
          : <span className="text-[11px] text-[#141414]/50 font-mono">Offboarded</span>}
        {staff.must_change_password && staff.is_active && (
          <span className="ml-2 text-[10px] text-[#B26B00] font-mono">must reset</span>
        )}
      </td>
      <td className="px-3 py-2 text-right whitespace-nowrap">
        {locked ? <span className="text-[10px] text-[#141414]/30 font-mono">{isOwner ? 'owner' : 'you'}</span> : (
          <div className="inline-flex items-center gap-1.5">
            <button onClick={reset} disabled={busy} title="Reset password"
              className="p-1.5 border border-[#141414]/30 hover:bg-[#141414] hover:text-white cursor-pointer"><KeyRound className="h-3.5 w-3.5" /></button>
            <button onClick={toggleActive} disabled={busy} title={staff.is_active ? 'Offboard' : 'Reactivate'}
              className="p-1.5 border border-[#141414]/30 hover:bg-[#141414] hover:text-white cursor-pointer">
              {staff.is_active ? <UserX className="h-3.5 w-3.5" /> : <UserCheck className="h-3.5 w-3.5" />}
            </button>
          </div>
        )}
      </td>
    </tr>
  );
};

export default function StaffView({ me }: { me: Me }) {
  const [rows, setRows] = useState<StaffMember[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showAdd, setShowAdd] = useState(false);

  const load = useCallback((): void => {
    setLoading(true);
    api.staff.list()
      .then((r) => setRows(r))
      .catch(() => setError('Could not load your team.'))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-lg font-bold font-mono uppercase tracking-wide flex items-center gap-2">
            <UsersRound className="h-5 w-5" /> Team
          </h1>
          <p className="text-sm text-[#141414]/60">
            Create logins for your staff and set what each can do. Changing a role or removing
            someone logs them out immediately.
          </p>
        </div>
        <button onClick={() => setShowAdd((v) => !v)}
          className="flex items-center gap-1.5 px-3 py-2 text-xs font-bold font-mono uppercase border border-[#141414] bg-[#141414] text-white cursor-pointer hover:opacity-90">
          <UserPlus className="h-4 w-4" /> Add employee
        </button>
      </div>

      {showAdd && <AddStaff onCreated={() => { setShowAdd(false); load(); }} />}

      {error && <div className="text-sm text-[#B22222]">{error}</div>}

      <div className="border border-[#141414] bg-white overflow-x-auto">
        <table className="w-full text-sm min-w-[680px]">
          <thead>
            <tr className="bg-[#E4E3E0] text-left font-mono text-[10px] uppercase tracking-wider text-[#141414]/60">
              <th className="px-3 py-2">Name</th>
              <th className="px-3 py-2">Phone</th>
              <th className="px-3 py-2">Role</th>
              <th className="px-3 py-2">Status</th>
              <th className="px-3 py-2 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {loading ? (
              <tr><td colSpan={5} className="px-3 py-6 text-center text-[#141414]/50">
                <Loader2 className="h-4 w-4 animate-spin inline mr-2" /> Loading…</td></tr>
            ) : rows.length === 0 ? (
              <tr><td colSpan={5} className="px-3 py-6 text-center text-[#141414]/50">No staff yet — add your first employee.</td></tr>
            ) : (
              rows.map((s) => (
                <StaffRow key={s.id} staff={s} isSelf={s.phone === me.phone} onChanged={load} />
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
