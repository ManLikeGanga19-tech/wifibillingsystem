import { useState, type FormEvent } from 'react';
import { KeyRound, Loader2, ShieldCheck } from 'lucide-react';
import { api, ApiError, Settlement } from '../api/client';
import { fmtKsh, toast } from './ui';

/**
 * "We sent your money — tell us the code that came with it."
 *
 * The first payout to a new destination carries a short code. Reading it back
 * proves the money actually landed where the ISP said it should, and it costs us
 * nothing: the code rides along on money they asked for anyway.
 *
 * Until they confirm, NO SECOND payout leaves. That is the whole point, and it is
 * not really about typos — it is about ACCOUNT TAKEOVER. Someone who gets into an
 * ISP's console could swap the payout destination and drain the wallet. This caps
 * that at a single payout, and changing a confirmed account re-arms the whole cycle
 * (and emails the real owner).
 *
 * So the copy must not read as bureaucracy. It has to say: your money is already
 * gone out, this is what unlocks the rest, and here is what it protects you from.
 */
export default function ConfirmPayout({
  settlement,
  onConfirmed,
}: {
  settlement: Settlement;
  onConfirmed: () => void;
}) {
  const pending = settlement.awaiting_confirmation;
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);

  if (!pending) return null;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const s = await api.settlement.confirm(code.trim());
      toast('success', s.detail);
      onConfirmed();
    } catch (err) {
      toast('error', err instanceof ApiError ? err.message : 'Could not confirm that code.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="bg-white border-2 border-[#B26B00]">
      <div className="p-4 sm:p-5">
        <div className="flex items-start gap-3">
          <div className="bg-[#B26B00] text-white p-1.5 shrink-0">
            <KeyRound className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <h3 className="text-sm font-bold font-mono uppercase tracking-tight">
              Confirm your payout to unlock the rest
            </h3>
            <p className="text-xs font-mono text-[#141414]/70 mt-1 leading-relaxed">
              We paid <b>{fmtKsh(pending.amount)}</b> to <b>{pending.destination}</b> in full. It
              arrived with a short code — find it on your M-Pesa message or statement and type it
              below.
            </p>
          </div>
        </div>

        <form onSubmit={submit} className="mt-4 flex flex-col sm:flex-row gap-2">
          <input
            autoFocus
            value={code}
            onChange={(e) => setCode(e.target.value.toUpperCase())}
            placeholder="WOS-XXXX"
            className="w-full sm:max-w-[12rem] bg-white border border-[#141414] p-2 text-xs font-mono uppercase outline-none focus:bg-[#f8f8f6]"
          />
          <button
            type="submit"
            disabled={busy || code.trim().length < 4}
            className="inline-flex items-center justify-center gap-1.5 px-3 py-2 text-xs font-bold font-mono uppercase border border-[#228B22] bg-[#228B22] text-white hover:opacity-85 transition cursor-pointer disabled:opacity-40 whitespace-nowrap"
          >
            {busy ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <ShieldCheck className="h-3.5 w-3.5" />
            )}
            Confirm &amp; unlock payouts
          </button>
        </form>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-2">
          <p className="text-[10px] font-mono text-[#141414]/50">
            {pending.attempts_left} attempt(s) left
          </p>
        </div>

        {/* Why this exists — say it plainly, or it reads as red tape. */}
        <p className="text-[10px] font-mono text-[#141414]/50 mt-3 border-t border-[#141414]/10 pt-2.5 leading-relaxed">
          <b>Why:</b> until you confirm, we hold further withdrawals. It means that if anyone ever
          got into your console and changed your payout account, they could take one payout — never
          your whole balance. Change the account later and we&apos;ll ask again, and email you.
        </p>
      </div>
    </div>
  );
}
