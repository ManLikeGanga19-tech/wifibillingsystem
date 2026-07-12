import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Banknote, CheckCircle2, Loader2, Send, Smartphone } from 'lucide-react';
import { api, ApiError, Settlement } from '../api/client';
import { toast } from './ui';

/**
 * "Where should we pay you?" — the last thing between a new ISP and their first
 * shilling.
 *
 * Three moves: tell us the account → we send a few shillings carrying a reference
 * → read it back. That last step is the whole point: only someone who can see that
 * account's statement can do it, which proves they control it. Same trick banks
 * have used for decades, and it means we never ask anyone to upload a document.
 *
 * The copy has to carry the custody model too. An ISP WILL ask why their customers'
 * money lands with us; better they read the honest answer here than invent a worse
 * one.
 */
export default function SettlementSetup({ onVerified }: { onVerified: () => void }) {
  const [state, setState] = useState<Settlement | null>(null);
  const [method, setMethod] = useState<'paybill' | 'bank'>('paybill');
  const [busy, setBusy] = useState(false);
  const [reference, setReference] = useState('');

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

  const fail = (e: unknown) =>
    toast('error', e instanceof ApiError ? e.message : 'Something went wrong.');

  const saveAccount = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    try {
      setState(await api.settlement.set({ method, ...Object.fromEntries(form) as Record<string, string> }));
      toast('success', 'Saved. Now we need to prove it’s yours.');
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  };

  const send = async () => {
    setBusy(true);
    try {
      const s = await api.settlement.send();
      setState(s);
      toast('info', s.detail);
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  };

  const verify = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const s = await api.settlement.verify(reference.trim());
      setState(s);
      toast('success', s.detail);
      if (s.can_transact) onVerified();
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  };

  if (!state) {
    return (
      <div className="flex justify-center py-8">
        <Loader2 className="h-5 w-5 animate-spin text-[#141414]/40" />
      </div>
    );
  }

  if (state.verified) {
    return (
      <div className="flex items-start gap-2.5 text-xs font-mono">
        <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5 text-[#228B22]" />
        <span>
          Verified — we&apos;ll settle to <b>{state.destination}</b>.
        </span>
      </div>
    );
  }

  /* ---- step 2: they've told us the account; now prove it ---- */
  if (state.has_account) {
    return (
      <div className="space-y-3">
        <p className="text-xs font-mono text-[#141414]/70 leading-relaxed">
          We&apos;ll pay you into <b>{state.destination}</b>.
        </p>

        {!state.verification.in_progress ? (
          <>
            <p className="text-xs font-mono text-[#141414]/70 leading-relaxed">
              To prove it&apos;s really yours, we&apos;ll send it a few shillings carrying a
              reference. Find them on your statement and type the reference back — that&apos;s
              all we need. No documents, no waiting for a human.
            </p>
            <button
              onClick={send}
              disabled={busy}
              className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-bold font-mono uppercase border border-[#141414] bg-[#141414] text-[#E4E3E0] hover:bg-[#228B22] hover:border-[#228B22] transition cursor-pointer disabled:opacity-40"
            >
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Send className="h-3.5 w-3.5" />}
              Send the test payment
            </button>
          </>
        ) : (
          <form onSubmit={verify} className="space-y-2.5">
            <p className="text-xs font-mono text-[#141414]/70 leading-relaxed">
              We sent <b>KSh {state.verification.amount}</b> to {state.destination}. Find it on
              your statement and type the reference it carries (it looks like{' '}
              <span className="font-bold">WOS-XXXX</span>).
            </p>
            <div className="flex gap-2">
              <input
                autoFocus
                value={reference}
                onChange={(e) => setReference(e.target.value.toUpperCase())}
                placeholder="WOS-XXXX"
                className="w-full bg-white border border-[#141414] p-2 text-xs font-mono uppercase outline-none focus:bg-[#f8f8f6]"
              />
              <button
                type="submit"
                disabled={busy || reference.trim().length < 4}
                className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-bold font-mono uppercase border border-[#141414] bg-[#141414] text-[#E4E3E0] hover:bg-[#228B22] hover:border-[#228B22] transition cursor-pointer disabled:opacity-40 whitespace-nowrap"
              >
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
                Go live
              </button>
            </div>
            <div className="flex items-center justify-between">
              {state.verification.attempts_left !== null && (
                <p className="text-[10px] font-mono text-[#141414]/50">
                  {state.verification.attempts_left} attempt(s) left
                </p>
              )}
              <button
                type="button"
                onClick={send}
                disabled={busy}
                className="text-[10px] font-mono underline text-[#141414]/60 cursor-pointer"
              >
                Send it again
              </button>
            </div>
          </form>
        )}
      </div>
    );
  }

  /* ---- step 1: where do we pay you? ---- */
  return (
    <form onSubmit={saveAccount} className="space-y-3">
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
          <Field name="settlement_name" label="Registered business name" placeholder="Acme Networks Ltd" />
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          <Field name="payout_bank_name" label="Bank" placeholder="I&M Bank" />
          <Field name="payout_bank_account_number" label="Account number" placeholder="0123456789" />
          <Field name="payout_bank_account_name" label="Account name" placeholder="Acme Networks Ltd" />
        </div>
      )}

      <button
        type="submit"
        disabled={busy}
        className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-bold font-mono uppercase border border-[#141414] bg-[#141414] text-[#E4E3E0] hover:bg-[#228B22] hover:border-[#228B22] transition cursor-pointer disabled:opacity-40"
      >
        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
        Save account
      </button>

      <p className="text-[10px] font-mono text-[#141414]/50 leading-relaxed">
        {state.explainer}
      </p>
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
