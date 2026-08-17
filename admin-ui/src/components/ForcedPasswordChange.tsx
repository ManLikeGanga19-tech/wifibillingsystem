import { useState, type FormEvent } from 'react';
import { KeyRound, Loader2 } from 'lucide-react';
import { api, ApiError, ROLE_META, type Me } from '../api/client';

/**
 * Full-screen gate a new hire hits on first login: their temp password (set by the owner/admin)
 * is single-use, so the console makes them choose their own before anything else. Clearing it is
 * a plain change-password; the server drops the must_change_password flag and we reload `me`.
 */
export default function ForcedPasswordChange({ me, onDone }: { me: Me; onDone: () => void }) {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [confirm, setConfirm] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError('');
    if (next.length < 8) return setError('Use at least 8 characters.');
    if (next !== confirm) return setError('The two new passwords do not match.');
    setBusy(true);
    try {
      await api.changePassword(current, next);
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not change your password.');
    } finally {
      setBusy(false);
    }
  };

  const role = ROLE_META[me.role];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#E4E3E0] p-4 text-[#141414]">
      <form onSubmit={submit} className="w-full max-w-sm border border-[#141414] bg-white p-6 font-mono">
        <div className="flex items-center gap-2 mb-1">
          <KeyRound className="h-5 w-5" />
          <h1 className="text-lg font-bold uppercase tracking-tight">Set your password</h1>
        </div>
        <p className="text-xs text-[#141414]/60 mb-4 leading-relaxed font-sans">
          Welcome, <b>{me.name || me.phone}</b>. You're signed in as{' '}
          <span className="font-bold" style={{ color: role.color }}>{role.label}</span>. Choose your
          own password before you start — the temporary one won't work again.
        </p>

        {error && <div className="mb-3 text-xs text-[#B22222] border border-[#B22222]/40 bg-[#B22222]/5 px-2 py-1.5">{error}</div>}

        <label className="block text-[10px] uppercase tracking-wider text-[#141414]/50 mb-1">Temporary password</label>
        <input type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)}
          className="w-full border border-[#141414]/40 px-2 py-1.5 mb-3 text-sm focus:border-[#141414] outline-none" required />

        <label className="block text-[10px] uppercase tracking-wider text-[#141414]/50 mb-1">New password</label>
        <input type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)}
          className="w-full border border-[#141414]/40 px-2 py-1.5 mb-3 text-sm focus:border-[#141414] outline-none" required />

        <label className="block text-[10px] uppercase tracking-wider text-[#141414]/50 mb-1">Confirm new password</label>
        <input type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)}
          className="w-full border border-[#141414]/40 px-2 py-1.5 mb-4 text-sm focus:border-[#141414] outline-none" required />

        <button type="submit" disabled={busy}
          className="w-full bg-[#141414] text-white py-2 text-xs font-bold uppercase tracking-wide flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50">
          {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          Set password &amp; continue
        </button>
      </form>
    </div>
  );
}
