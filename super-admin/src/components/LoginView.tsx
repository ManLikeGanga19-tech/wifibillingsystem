import { useState, type FormEvent } from 'react';
import { Loader2, ShieldCheck } from 'lucide-react';
import { api, login, logout } from '../api/client';
import { Btn } from './ui';

/** Platform staff only. A tenant's credentials authenticate fine against the
 * shared backend, so we check the role here and refuse — this console must never
 * open for an ISP user. */
export default function LoginView({ onLoggedIn }: { onLoggedIn: () => void }) {
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError('');
    try {
      await login(phone.trim(), password);
      const me = await api.me();
      if (!me.is_platform_staff) {
        logout();
        setError('This console is for platform staff. Use your ISP console instead.');
        return;
      }
      onLoggedIn();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign-in failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <form onSubmit={submit} className="panel sheen p-7 w-full max-w-sm space-y-5">
        <div className="text-center space-y-2">
          <div
            className="h-11 w-11 rounded-xl mx-auto flex items-center justify-center"
            style={{ background: 'var(--accent-dim)' }}
          >
            <ShieldCheck className="h-5 w-5" style={{ color: 'var(--accent)' }} />
          </div>
          <h1 className="text-lg font-semibold tracking-tight">WIFI.OS</h1>
          <p
            className="text-[11px] uppercase tracking-[0.2em]"
            style={{ color: 'var(--accent)' }}
          >
            Platform Control
          </p>
        </div>

        <label className="block">
          <span
            className="text-[11px] uppercase tracking-wider"
            style={{ color: 'var(--text-muted)' }}
          >
            Phone
          </span>
          <input
            autoFocus
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="254700000000"
            className="mt-1 tnum"
          />
        </label>

        <label className="block">
          <span
            className="text-[11px] uppercase tracking-wider"
            style={{ color: 'var(--text-muted)' }}
          >
            Password
          </span>
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1"
          />
        </label>

        {error && (
          <p className="text-xs" style={{ color: '#f07373' }}>
            {error}
          </p>
        )}

        <Btn variant="primary" type="submit" disabled={busy || !phone || !password}>
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          {busy ? 'Signing in…' : 'Sign in'}
        </Btn>
      </form>
    </div>
  );
}
