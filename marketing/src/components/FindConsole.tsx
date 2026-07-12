import { useState, type FormEvent } from 'react';
import { Loader2, Mail, Send } from 'lucide-react';

/**
 * "Where do I sign in?"
 *
 * There is no shared front door — every ISP signs in at their own subdomain — so an
 * operator who lost that link has nowhere to go. This is the way back.
 *
 * The response is IDENTICAL whether or not the address is registered. That is not
 * politeness; a lookup that confirms "yes, that ISP banks with us" is an enumeration
 * oracle wearing a helpful face. The real answer goes to the inbox, which is the only
 * thing that can prove it owns the address.
 */
export default function FindConsole() {
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState('');

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    setError('');
    try {
      const resp = await fetch('/api/v1/signup/find-console/', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      });
      if (!resp.ok) {
        const body = await resp.json().catch(() => null);
        throw new Error(body?.detail ?? 'Something went wrong. Try again shortly.');
      }
      setSent(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong.');
    } finally {
      setBusy(false);
    }
  };

  if (sent) {
    return (
      <div className="border border-ink bg-card p-6 text-center">
        <div className="mx-auto grid h-11 w-11 place-items-center border border-money bg-money text-white">
          <Mail className="h-5 w-5" />
        </div>
        <h2 className="mt-4 font-serif text-xl font-bold">Check your inbox.</h2>
        <p className="mx-auto mt-2 max-w-sm text-sm leading-relaxed text-ink/70">
          If <span className="font-mono font-bold">{email}</span> has an account, the link
          to your console is on its way.
        </p>
        <p className="mt-4 font-mono text-[10px] leading-relaxed text-ink/50">
          We say this whether or not the address is registered — so nobody can use this
          page to find out who our customers are.
        </p>
      </div>
    );
  }

  return (
    <form onSubmit={submit} className="border border-ink bg-card p-6">
      <label className="block">
        <span className="font-mono text-[10px] font-bold uppercase tracking-wide text-ink/60">
          The email you signed up with
        </span>
        <input
          type="email"
          required
          autoFocus
          autoComplete="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@company.co.ke"
          className="mt-1 w-full border border-ink bg-white p-2.5 font-mono text-sm outline-none focus:bg-hover"
        />
      </label>

      {error && (
        <p role="alert" className="mt-3 font-mono text-xs text-[#B22222]">
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={busy || !email}
        className="mt-4 inline-flex w-full items-center justify-center gap-2 border border-money bg-money px-4 py-3 font-mono text-xs font-bold uppercase text-white transition hover:opacity-85 disabled:opacity-40"
      >
        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
        Email me my console link
      </button>
    </form>
  );
}
