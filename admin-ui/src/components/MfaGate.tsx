import { useEffect, useState, type FormEvent } from 'react';
import { Copy, KeyRound, Loader2, ShieldCheck, Smartphone, X } from 'lucide-react';
import { api, ApiError, type MfaChallenge } from '../api/client';
import { toast } from './ui';

/**
 * The second factor, asked for at the moment it matters.
 *
 * Two states, and which one you get depends on the server, not on us:
 *   NOT ENROLLED -> show the QR code. They are trying to move money and have no
 *                   authenticator; this is the only moment they will ever bother to
 *                   set one up, so we do it here rather than nagging them in Settings.
 *   ENROLLED     -> ask for the six digits.
 *
 * Nothing is stored. The code lives in a React state variable for the length of one
 * request and dies with the component — no browser storage anywhere, the hard rule of
 * this system, and doubly so for something that authorises a withdrawal.
 */
export default function MfaGate({
  challenge,
  onCode,
  onCancel,
}: {
  challenge: MfaChallenge;
  /** Hands the verified-looking code back to whoever opened the gate, to retry with. */
  onCode: (code: string) => void;
  onCancel: () => void;
}) {
  const [enrolled, setEnrolled] = useState(challenge.enrolled);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-[#141414]/60 p-4">
      <div className="w-full max-w-md border border-[#141414] bg-white">
        <div className="flex items-center justify-between border-b border-[#141414] bg-[#141414] px-4 py-2.5">
          <p className="flex items-center gap-2 font-mono text-[11px] font-bold uppercase tracking-widest text-[#E4E3E0]">
            <ShieldCheck className="h-3.5 w-3.5 text-[#228B22]" />
            {enrolled ? 'Confirm it’s you' : 'Secure your wallet'}
          </p>
          <button
            type="button"
            onClick={onCancel}
            aria-label="Cancel"
            className="text-[#E4E3E0]/60 transition hover:text-[#E4E3E0]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="p-5">
          {enrolled ? (
            <CodePrompt detail={challenge.detail} onCode={onCode} />
          ) : (
            <Enrol detail={challenge.detail} onEnrolled={() => setEnrolled(true)} />
          )}
        </div>
      </div>
    </div>
  );
}

/* ---------- enrolled: just ask ------------------------------------------------ */

function CodePrompt({ detail, onCode }: { detail: string; onCode: (code: string) => void }) {
  const [code, setCode] = useState('');

  const submit = (e: FormEvent) => {
    e.preventDefault();
    onCode(code.trim());
  };

  return (
    <form onSubmit={submit} className="space-y-3">
      <p className="text-xs leading-relaxed text-[#141414]/70">{detail}</p>

      <input
        autoFocus
        value={code}
        onChange={(e) => setCode(e.target.value)}
        inputMode="text"
        autoComplete="one-time-code"
        placeholder="123456"
        className="w-full border border-[#141414] bg-white p-3 text-center font-mono text-2xl font-black tracking-[0.3em] outline-none focus:bg-[#f8f8f6]"
      />

      <button
        type="submit"
        disabled={code.length < 6}
        className="inline-flex w-full items-center justify-center gap-2 border border-[#228B22] bg-[#228B22] px-4 py-3 font-mono text-xs font-bold uppercase text-white transition hover:opacity-85 disabled:opacity-40"
      >
        <KeyRound className="h-3.5 w-3.5" />
        Authorise
      </button>

      <p className="font-mono text-[10px] leading-relaxed text-[#141414]/50">
        Lost your phone? Enter one of your recovery codes instead.
      </p>
    </form>
  );
}

/* ---------- not enrolled: set it up, here, now -------------------------------- */

function Enrol({ detail, onEnrolled }: { detail: string; onEnrolled: () => void }) {
  const [setup, setSetup] = useState<{ qr: string; secret: string } | null>(null);
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [codes, setCodes] = useState<string[] | null>(null);

  useEffect(() => {
    api.mfa
      .setup()
      .then(setSetup)
      .catch((err) => toast('error', err instanceof ApiError ? err.message : 'Could not start setup.'));
  }, []);

  const confirm = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    try {
      const result = await api.mfa.confirm(code.trim());
      setCodes(result.recovery_codes); // shown ONCE — never again, by design
    } catch (err) {
      toast('error', err instanceof ApiError ? err.message : 'That code was not right.');
    } finally {
      setBusy(false);
    }
  };

  // The recovery codes. This screen exists because the alternative — an ISP who loses
  // their phone and cannot reach their own money — is the worst thing this system
  // could do to somebody.
  if (codes) {
    return (
      <div className="space-y-3">
        <p className="font-mono text-xs font-bold uppercase text-[#228B22]">
          Your authenticator is on.
        </p>
        <div className="border border-[#B26B00] bg-[#FFF8EC] p-3">
          <p className="font-mono text-[10px] font-bold uppercase tracking-widest text-[#B26B00]">
            Save these now
          </p>
          <p className="mt-1 text-xs leading-relaxed text-[#141414]/75">
            These are the only way back into your money if you lose your phone. We cannot
            show them to you again.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-1.5 border border-[#141414] bg-[#f0efec] p-3">
          {codes.map((c) => (
            <code key={c} className="font-mono text-xs font-bold tracking-wider">
              {c}
            </code>
          ))}
        </div>

        <button
          type="button"
          onClick={() => {
            navigator.clipboard?.writeText(codes.join('\n'));
            toast('success', 'Recovery codes copied.');
          }}
          className="inline-flex w-full items-center justify-center gap-2 border border-[#141414] bg-white px-4 py-2.5 font-mono text-xs font-bold uppercase transition hover:bg-[#f0efec]"
        >
          <Copy className="h-3.5 w-3.5" />
          Copy them
        </button>

        <button
          type="button"
          onClick={onEnrolled}
          className="inline-flex w-full items-center justify-center gap-2 border border-[#228B22] bg-[#228B22] px-4 py-3 font-mono text-xs font-bold uppercase text-white transition hover:opacity-85"
        >
          I&apos;ve saved them — continue
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={confirm} className="space-y-3">
      <p className="text-xs leading-relaxed text-[#141414]/70">{detail}</p>

      <div className="flex justify-center border border-[#141414] bg-white p-3">
        {setup ? (
          <img src={setup.qr} alt="Scan this with your authenticator app" className="h-40 w-40" />
        ) : (
          <div className="flex h-40 w-40 items-center justify-center">
            <Loader2 className="h-5 w-5 animate-spin text-[#141414]/40" />
          </div>
        )}
      </div>

      <p className="flex items-start gap-1.5 font-mono text-[10px] leading-relaxed text-[#141414]/55">
        <Smartphone className="mt-0.5 h-3 w-3 shrink-0" />
        Scan it with Google Authenticator (or any authenticator app). Can&apos;t scan? Type
        this key in: <span className="font-bold break-all">{setup?.secret ?? '…'}</span>
      </p>

      <input
        value={code}
        onChange={(e) => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
        inputMode="numeric"
        autoComplete="one-time-code"
        placeholder="123456"
        className="w-full border border-[#141414] bg-white p-3 text-center font-mono text-2xl font-black tracking-[0.3em] outline-none focus:bg-[#f8f8f6]"
      />

      <button
        type="submit"
        disabled={busy || code.length < 6 || !setup}
        className="inline-flex w-full items-center justify-center gap-2 border border-[#228B22] bg-[#228B22] px-4 py-3 font-mono text-xs font-bold uppercase text-white transition hover:opacity-85 disabled:opacity-40"
      >
        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ShieldCheck className="h-3.5 w-3.5" />}
        Turn it on
      </button>
    </form>
  );
}
