import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { Banknote, CheckCircle2, KeyRound, Loader2, Pencil, ShieldAlert, Smartphone, X, Zap } from 'lucide-react';
import { api, ApiError, Settlement } from '../api/client';
import { toast } from './ui';

/**
 * "Where should we pay you?" — the last thing between a new ISP and their first
 * shilling, and it takes one form.
 *
 * SETTING IT IS PLUG AND PLAY on purpose. We do NOT send a test payment to prove the
 * account before letting them trade: most signups never trade at all, and paying a
 * transfer fee to verify idle accounts is a straight loss on our least valuable
 * users. The paybill IS the KYC — Safaricom already vetted them to issue it.
 *
 * CHANGING IT IS NOT. Swapping the payout destination is exactly what someone who got
 * into an ISP's console would do, so it takes a code emailed to the owner's login
 * address — an inbox the console cannot reach. First save: one click. Change: two
 * steps, on purpose.
 *
 * The copy has to carry the custody model too. An ISP WILL ask why their customers'
 * money lands with us; better they read the honest answer here than invent a worse
 * one.
 */
export default function SettlementSetup({ onWentLive }: { onWentLive: () => void }) {
  const [state, setState] = useState<Settlement | null>(null);
  const [method, setMethod] = useState<'paybill' | 'bank'>('paybill');
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  // Held in memory only, never in storage, and dropped the moment the change lands.
  const [codeStep, setCodeStep] = useState<{ sentTo: string } | null>(null);
  const pending = useRef<Record<string, string> | null>(null);

  const load = useCallback(async () => {
    try {
      const s = await api.settlement.get();
      setState(s);
      if (s.method) setMethod(s.method);
    } catch {
      /* the banner still shows; they can retry */
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const submit = async (body: Record<string, string>) => {
    setBusy(true);
    try {
      const s = await api.settlement.set({ method, ...body });
      setState(s);
      setEditing(false);
      setCodeStep(null);
      pending.current = null;
      toast('success', s.detail);
      if (s.can_transact) onWentLive();
    } catch (err) {
      // Not a failure — a step. The code is already in the owner's inbox.
      if (err instanceof ApiError && (err.body as { code_required?: boolean })?.code_required) {
        pending.current = body;
        setCodeStep({ sentTo: err.message });
      } else {
        toast('error', err instanceof ApiError ? err.message : 'Could not save that.');
      }
    } finally {
      setBusy(false);
    }
  };

  const save = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    submit(Object.fromEntries(new FormData(e.currentTarget)) as Record<string, string>);
  };

  const enterCode = (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const code = String(new FormData(e.currentTarget).get('code') ?? '');
    submit({ ...(pending.current ?? {}), code });
  };

  if (!state) {
    return (
      <div className="flex justify-center py-6">
        <Loader2 className="h-5 w-5 animate-spin text-[#141414]/40" />
      </div>
    );
  }

  /* Step 2 of a change: the code that only the real owner can read. */
  if (codeStep) {
    return (
      <form onSubmit={enterCode} className="space-y-3">
        <div className="flex items-start gap-2.5 border border-[#B26B00] bg-[#FFF8EC] p-3">
          <ShieldAlert className="h-4 w-4 shrink-0 mt-0.5 text-[#B26B00]" />
          <div className="text-xs font-mono leading-relaxed">
            <p className="font-bold uppercase text-[#B26B00]">One more step</p>
            <p className="mt-1">{codeStep.sentTo}</p>
            <p className="text-[#141414]/60 mt-1">
              Nothing has changed yet — we still pay <b>{state.destination}</b> until you enter it.
            </p>
          </div>
        </div>

        <label className="block max-w-[220px]">
          <span className="text-[10px] font-bold font-mono uppercase text-[#141414]/60">
            6-digit code
          </span>
          <input
            name="code"
            autoFocus
            inputMode="numeric"
            autoComplete="one-time-code"
            maxLength={6}
            placeholder="123456"
            className="mt-1 w-full bg-white border border-[#141414] p-2 text-lg font-black font-mono tracking-[0.3em] text-center outline-none focus:bg-[#f8f8f6]"
          />
        </label>

        <div className="flex gap-2">
          <button
            type="submit"
            disabled={busy}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-bold font-mono uppercase border border-[#228B22] bg-[#228B22] text-white hover:opacity-85 transition cursor-pointer disabled:opacity-40"
          >
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <KeyRound className="h-3.5 w-3.5" />}
            Lock in the new account
          </button>
          <button
            type="button"
            onClick={() => {
              setCodeStep(null);
              pending.current = null;
              setEditing(false);
            }}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-bold font-mono uppercase border border-[#141414] bg-white hover:bg-[#f0efec] transition cursor-pointer"
          >
            <X className="h-3.5 w-3.5" />
            Cancel
          </button>
        </div>

        <p className="text-[10px] font-mono text-[#141414]/50 leading-relaxed">
          Didn&apos;t ask for this? Someone may have access to your console. Do not enter the
          code — change your password and contact us.
        </p>
      </form>
    );
  }

  /* Settled and not being edited: say where the money goes, and offer the change. */
  if (state.has_account && !editing) {
    return (
      <div className="space-y-2">
        <div className="flex items-start gap-2.5 text-xs font-mono">
          <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5 text-[#228B22]" />
          <span>
            We&apos;ll settle to <b>{state.destination}</b>.
            {!state.confirmed && (
              <span className="block text-[#141414]/60 mt-1">
                Your first withdrawal will carry a short code — read it back and your payouts
                unlock for good.
              </span>
            )}
          </span>
        </div>
        <button
          type="button"
          onClick={() => setEditing(true)}
          className="inline-flex items-center gap-1.5 px-2.5 py-1.5 text-[11px] font-bold font-mono uppercase border border-[#141414] bg-white hover:bg-[#f0efec] transition cursor-pointer"
        >
          <Pencil className="h-3 w-3" />
          Change account
        </button>
      </div>
    );
  }

  return (
    <form onSubmit={save} className="space-y-3">
      {state.change_requires_code && (
        <div className="flex items-start gap-2 border border-[#141414] bg-[#f0efec] p-2.5 text-[11px] font-mono leading-relaxed">
          <ShieldAlert className="h-3.5 w-3.5 shrink-0 mt-0.5" />
          <span>
            Changing where we pay you needs a code from your email. We&apos;ll send it when you
            save. Until you enter it, we keep paying <b>{state.destination}</b>.
          </span>
        </div>
      )}

      <div className="flex gap-2">
        {(
          [
            ['paybill', 'M-Pesa Paybill', Smartphone],
            ['bank', 'Bank account', Banknote],
          ] as const
        ).map(([value, label, Icon]) => (
          <button
            key={value}
            type="button"
            onClick={() => setMethod(value)}
            className={`flex-1 inline-flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-bold font-mono uppercase border transition cursor-pointer ${
              method === value
                ? 'bg-[#141414] text-[#E4E3E0] border-[#141414]'
                : 'bg-white text-[#141414] border-[#141414] hover:bg-[#f0efec]'
            }`}
          >
            <Icon className="h-3.5 w-3.5" />
            {label}
          </button>
        ))}
      </div>

      {method === 'paybill' ? (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          <Field name="settlement_paybill" label="Your paybill number" placeholder="123456" />
          <Field
            name="settlement_name"
            label="Registered business name"
            placeholder="Acme Networks Ltd"
          />
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          <Field name="payout_bank_name" label="Bank" placeholder="I&M Bank" />
          <Field name="payout_bank_account_number" label="Account number" placeholder="0123456789" />
          <Field name="payout_bank_account_name" label="Account name" placeholder="Acme Networks Ltd" />
        </div>
      )}

      <div className="flex gap-2">
        <button
          type="submit"
          disabled={busy}
          className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-bold font-mono uppercase border border-[#228B22] bg-[#228B22] text-white hover:opacity-85 transition cursor-pointer disabled:opacity-40"
        >
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />}
          {state.has_account ? 'Continue' : 'Save & go live'}
        </button>
        {state.has_account && (
          <button
            type="button"
            onClick={() => setEditing(false)}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-bold font-mono uppercase border border-[#141414] bg-white hover:bg-[#f0efec] transition cursor-pointer"
          >
            <X className="h-3.5 w-3.5" />
            Cancel
          </button>
        )}
      </div>

      {!state.has_account && (
        <p className="text-[10px] font-mono text-[#141414]/50 leading-relaxed">
          Payments switch on the moment you save — no documents, no waiting. {state.explainer}
        </p>
      )}
    </form>
  );
}

function Field({
  name,
  label,
  placeholder,
}: {
  name: string;
  label: string;
  placeholder: string;
}) {
  return (
    <label className="block">
      <span className="text-[10px] font-bold font-mono uppercase text-[#141414]/60">{label}</span>
      <input
        name={name}
        placeholder={placeholder}
        className="mt-1 w-full bg-white border border-[#141414] p-2 text-xs font-mono outline-none focus:bg-[#f8f8f6]"
      />
    </label>
  );
}
