import { useState, type FormEvent } from 'react';
import { Wifi, Lock, Loader2, Building2, CheckCircle2 } from 'lucide-react';
import { login, signup, ApiError } from '../api/client';

export default function LoginView({ onLoggedIn }: { onLoggedIn: () => void }) {
  const [mode, setMode] = useState<'login' | 'signup' | 'signup-done'>('login');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  // login fields
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');

  // signup fields
  const [form, setForm] = useState({
    business_name: '',
    owner_name: '',
    phone: '',
    email: '',
    password: '',
  });

  const doLogin = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      // Send it as typed. Stripping non-digits used to be safe when this box only
      // took a phone number; it would now shred an email address into nothing. The
      // server canonicalises either identifier.
      await login(phone.trim(), password);
      onLoggedIn();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
      setBusy(false);
    }
  };

  const doSignup = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await signup(form);
      setMode('signup-done');
    } catch (err) {
      if (err instanceof ApiError && typeof err.body === 'object' && err.body) {
        const fields = Object.entries(err.body as Record<string, unknown>)
          .map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(' ') : String(v)}`)
          .join(' · ');
        setError(fields || err.message);
      } else {
        setError(err instanceof Error ? err.message : 'Signup failed');
      }
    } finally {
      setBusy(false);
    }
  };

  const input = 'w-full border border-[#141414] p-2.5 text-sm font-mono outline-none focus:bg-[#f8f8f6]';
  const label = 'text-xs font-bold font-mono uppercase text-[#141414]/60 block mb-1';

  return (
    <div className="min-h-screen w-full bg-[#E4E3E0] text-[#141414] flex items-center justify-center p-4 font-sans">
      <div className="w-full max-w-sm bg-white border border-[#141414] p-6 space-y-5">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 bg-[#141414] flex items-center justify-center">
            <Wifi className="h-5 w-5 text-[#E4E3E0]" />
          </div>
          <div>
            <h1 className="font-bold text-lg font-mono tracking-tighter uppercase leading-none">WIFI.OS</h1>
            <p className="text-xs text-[#141414]/60 font-mono">
              {mode === 'login' ? 'Operator Console — Sign in' : 'Register your ISP'}
            </p>
          </div>
        </div>

        {mode === 'signup-done' ? (
          <div className="text-center space-y-3 py-4">
            <CheckCircle2 className="h-10 w-10 text-[#228B22] mx-auto" />
            <p className="text-sm font-bold">Application received!</p>
            <p className="text-xs text-[#141414]/70 leading-relaxed">
              Your ISP account is pending approval by the platform. You will be able to
              sign in once it is approved.
            </p>
            <button onClick={() => setMode('login')} className="text-xs font-mono underline cursor-pointer">
              Back to sign in
            </button>
          </div>
        ) : mode === 'login' ? (
          <form onSubmit={doLogin} className="space-y-4">
            <div>
              <label className={label}>Phone or Email</label>
              <input type="text" autoComplete="username" autoFocus required value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="07XX… or you@company.co.ke" className={input} />
            </div>
            <div>
              <label className={label}>Password</label>
              <input type="password" required value={password} onChange={(e) => setPassword(e.target.value)} className={input} />
            </div>
            {error && <p className="text-xs text-[#B22222] font-mono">{error}</p>}
            <button type="submit" disabled={busy} className="w-full bg-[#141414] disabled:opacity-40 text-[#E4E3E0] font-bold font-mono uppercase py-3 flex items-center justify-center gap-2 hover:bg-[#228B22] transition cursor-pointer">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Lock className="h-4 w-4" />}
              {busy ? 'Signing in…' : 'Sign in'}
            </button>
            <p className="text-xs font-mono text-center text-[#141414]/60">
              New ISP?{' '}
              <button type="button" onClick={() => { setMode('signup'); setError(''); }} className="underline font-bold cursor-pointer">
                Register your business
              </button>
            </p>
          </form>
        ) : (
          <form onSubmit={doSignup} className="space-y-3">
            <div>
              <label className={label}>Business Name</label>
              <input required value={form.business_name} onChange={(e) => setForm({ ...form, business_name: e.target.value })} placeholder="e.g. Mtandao Wireless" className={input} />
              {form.business_name && (
                <p className="text-[11px] font-mono text-[#141414]/50 mt-1">
                  Your console: <b>{form.business_name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '')}</b>.wifios.co.ke
                </p>
              )}
            </div>
            <div>
              <label className={label}>Your Name</label>
              <input required value={form.owner_name} onChange={(e) => setForm({ ...form, owner_name: e.target.value })} className={input} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className={label}>Phone (login)</label>
                <input type="tel" required value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} placeholder="07XX…" className={input} />
              </div>
              <div>
                <label className={label}>Password</label>
                <input type="password" required minLength={8} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} className={input} />
              </div>
            </div>
            <div>
              <label className={label}>Email</label>
              <input type="email" required value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} className={input} />
            </div>
            {error && <p className="text-xs text-[#B22222] font-mono leading-snug">{error}</p>}
            <button type="submit" disabled={busy} className="w-full bg-[#228B22] disabled:opacity-40 text-white font-bold font-mono uppercase py-3 flex items-center justify-center gap-2 hover:opacity-90 transition cursor-pointer">
              {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Building2 className="h-4 w-4" />}
              {busy ? 'Submitting…' : 'Apply for an account'}
            </button>
            <p className="text-xs font-mono text-center text-[#141414]/60">
              Already registered?{' '}
              <button type="button" onClick={() => { setMode('login'); setError(''); }} className="underline font-bold cursor-pointer">
                Sign in
              </button>
            </p>
          </form>
        )}
      </div>
    </div>
  );
}
