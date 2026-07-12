import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Banknote, CheckCircle2, Loader2, Smartphone, Zap } from 'lucide-react';
import { api, ApiError, Settlement } from '../api/client';
import { toast } from './ui';

/**
 * "Where should we pay you?" — the last thing between a new ISP and their first
 * shilling, and it takes one form.
 *
 * PLUG AND PLAY on purpose. We do NOT send a test payment to prove the account
 * before letting them trade: most signups never trade at all, and paying a transfer
 * fee to verify idle accounts is a straight loss on our least valuable users. The
 * paybill IS the KYC — Safaricom already vetted them to issue it.
 *
 * The proof happens later, for free: the first payout carries a code they read back
 * (see the wallet). Until then no SECOND payout leaves, which caps a wrong or
 * hijacked destination at one payout instead of an open drain.
 *
 * The copy has to carry the custody model too. An ISP WILL ask why their customers'
 * money lands with us; better they read the honest answer here than invent a worse
 * one.
 */
export default function SettlementSetup({ onWentLive }: { onWentLive: () => void }) {
  const [state, setState] = useState<Settlement | null>(null);
  const [method, setMethod] = useState<'paybill' | 'bank'>('paybill');
  const [busy, setBusy] = useState(false);

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

  const save = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = Object.fromEntries(new FormData(e.currentTarget)) as Record<string, string>;
    setBusy(true);
    try {
      const s = await api.settlement.set({ method, ...form });
      setState(s);
      toast('success', s.detail);
      if (s.can_transact) onWentLive();
    } catch (err) {
      toast('error', err instanceof ApiError ? err.message : 'Could not save that.');
    } finally {
      setBusy(false);
    }
  };

  if (!state) {
    return (
      <div className="flex justify-center py-6">
        <Loader2 className="h-5 w-5 animate-spin text-[#141414]/40" />
      </div>
    );
  }

  if (state.has_account) {
    return (
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
    );
  }

  return (
    <form onSubmit={save} className="space-y-3">
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

      <button
        type="submit"
        disabled={busy}
        className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-bold font-mono uppercase border border-[#228B22] bg-[#228B22] text-white hover:opacity-85 transition cursor-pointer disabled:opacity-40"
      >
        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />}
        Save &amp; go live
      </button>

      <p className="text-[10px] font-mono text-[#141414]/50 leading-relaxed">
        Payments switch on the moment you save — no documents, no waiting.{' '}
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
