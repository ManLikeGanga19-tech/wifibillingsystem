import React, { useState } from 'react';
import { Wifi, Lock, Loader2 } from 'lucide-react';
import { login } from '../api/client';

export default function LoginView({ onLoggedIn }: { onLoggedIn: () => void }) {
  const [phone, setPhone] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      await login(phone.replace(/\D/g, ''), password);
      onLoggedIn();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed');
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen w-full bg-[#E4E3E0] text-[#141414] flex items-center justify-center p-4 font-sans">
      <form onSubmit={submit} className="w-full max-w-sm bg-white border border-[#141414] p-6 space-y-5">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 bg-[#141414] flex items-center justify-center">
            <Wifi className="h-5 w-5 text-[#E4E3E0]" />
          </div>
          <div>
            <h1 className="font-bold text-lg font-mono tracking-tighter uppercase leading-none">WIFI.OS</h1>
            <p className="text-xs text-[#141414]/60 font-mono">Operator Console — Sign in</p>
          </div>
        </div>

        <div className="space-y-1">
          <label className="text-xs font-bold font-mono uppercase text-[#141414]/60 block">Phone Number</label>
          <input
            type="tel"
            autoFocus
            required
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="2547XXXXXXXX"
            className="w-full border border-[#141414] p-2.5 text-sm font-mono outline-none focus:bg-[#f8f8f6]"
          />
        </div>

        <div className="space-y-1">
          <label className="text-xs font-bold font-mono uppercase text-[#141414]/60 block">Password</label>
          <input
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full border border-[#141414] p-2.5 text-sm font-mono outline-none focus:bg-[#f8f8f6]"
          />
        </div>

        {error && <p className="text-xs text-[#B22222] font-mono">{error}</p>}

        <button
          type="submit"
          disabled={busy}
          className="w-full bg-[#141414] disabled:opacity-40 text-[#E4E3E0] font-bold font-mono uppercase py-3 flex items-center justify-center gap-2 hover:bg-[#228B22] transition cursor-pointer"
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Lock className="h-4 w-4" />}
          {busy ? 'Signing in…' : 'Sign in'}
        </button>
      </form>
    </div>
  );
}
