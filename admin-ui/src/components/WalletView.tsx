import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Wallet, ArrowDownToLine, Loader2 } from 'lucide-react';
import { api, ApiLedgerEntry, ApiPayout, asMfaChallenge, MfaChallenge, PayoutQuote, Settlement, WalletSummary, WithdrawPayload } from '../api/client';
import ConfirmPayout from './ConfirmPayout';
import MfaGate from './MfaGate';
import SettlementSetup from './SettlementSetup';
import { Badge, Btn, Field, inputCls, Panel, RefreshBtn, TableShell, tdCls, toast, ViewHeader, fmtDateTime, fmtKsh } from './ui';

const ENTRY_LABEL: Record<ApiLedgerEntry['entry_type'], { label: string; color: 'green' | 'red' | 'amber' | 'gray' | 'blue' }> = {
  sale: { label: 'Sale', color: 'green' },
  commission: { label: 'Commission', color: 'gray' },
  base_fee: { label: 'Platform fee', color: 'amber' },
  pppoe_fee: { label: 'PPPoE fee', color: 'amber' },
  setup_fee: { label: 'Setup fee', color: 'amber' },
  payout: { label: 'Withdrawal', color: 'blue' },
  adjustment: { label: 'Adjustment', color: 'gray' },
};

export default function WalletView() {
  const [summary, setSummary] = useState<WalletSummary | null>(null);
  const [ledger, setLedger] = useState<ApiLedgerEntry[] | null>(null);
  const [payouts, setPayouts] = useState<ApiPayout[]>([]);
  const [settlement, setSettlement] = useState<Settlement | null>(null);
  const [error, setError] = useState('');
  const [amount, setAmount] = useState('');
  const [quote, setQuote] = useState<PayoutQuote | null>(null);
  const [busy, setBusy] = useState(false);
  // The second factor. Held in memory for one request and then dropped — a code that
  // authorises a withdrawal is the last thing that should ever touch storage.
  const [challenge, setChallenge] = useState<MfaChallenge | null>(null);
  // So the Refresh button visibly does something even when nothing has changed.
  const [refreshing, setRefreshing] = useState(false);

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      const [s, l, p, st] = await Promise.all([
        api.billing.wallet(),
        api.billing.ledger(),
        api.billing.payouts.list(),
        api.settlement.get(),
      ]);
      setSummary(s);
      setLedger(l.results);
      setPayouts(p.results);
      setSettlement(st);
      setError('');
    } catch {
      setError('Could not load your wallet.');
    } finally {
      // Hold briefly so the Refresh click always produces visible feedback.
      setTimeout(() => setRefreshing(false), 400);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Live transfer-cost preview — so they see what they'll actually receive before committing.
  useEffect(() => {
    const a = amount.trim();
    if (!a || Number(a) <= 0) {
      setQuote(null);
      return;
    }
    const t = window.setTimeout(() => {
      api.billing.payouts.quote(a).then(setQuote).catch(() => setQuote(null));
    }, 350);
    return () => window.clearTimeout(t);
  }, [amount]);

  /** One place the withdrawal is actually sent, so the retry-with-a-code path is the
   *  SAME code path as the first attempt — not a second, subtly different one. The
   *  destination is NOT sent — it's the verified settlement account, server-side. */
  const send = async (mfa_code?: string) => {
    const payload: WithdrawPayload = { amount, mfa_code };

    setBusy(true);
    try {
      await api.billing.payouts.withdraw(payload);
      setChallenge(null);
      toast('success', 'Withdrawal requested — the platform will pay it out shortly.');
      setAmount('');
      load();
    } catch (err) {
      // Not an error to shout about: the server is asking for the second factor (or
      // telling us they have no authenticator yet). Open the gate instead of painting
      // the screen red.
      const mfa = asMfaChallenge(err);
      if (mfa) setChallenge(mfa);
      else toast('error', err instanceof Error ? err.message : 'Withdrawal failed.');
    } finally {
      setBusy(false);
    }
  };

  const withdraw = (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    send();
  };

  if (!summary && !error)
    return (
      <div className="flex justify-center py-24">
        <Loader2 className="h-8 w-8 animate-spin text-[#141414]/40" />
      </div>
    );

  return (
    <div className="space-y-5 text-[#141414]">
      <ViewHeader
        icon={<Wallet className="h-4.5 w-4.5" />}
        title="Wallet"
        subtitle="Your earnings, commission already deducted. Withdraw to your payout account anytime."
      >
        <RefreshBtn onClick={load} spinning={refreshing} />
      </ViewHeader>

      {challenge && (
        <MfaGate
          challenge={challenge}
          onCode={(code) => send(code)}
          onCancel={() => setChallenge(null)}
        />
      )}

      {/* Pinned above everything: their money is already out, and this is what
          unlocks the next withdrawal. Blocking a payout without explaining it is
          how a safety feature gets mistaken for a bug. */}
      {settlement && <ConfirmPayout settlement={settlement} onConfirmed={load} />}

      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <div className="bg-white border border-[#141414] p-3.5 col-span-2 md:col-span-1">
            <p className="text-[11px] font-mono uppercase text-[#141414]/60">Available Balance</p>
            <p className="text-xl font-black font-mono mt-1 text-[#228B22]">{fmtKsh(summary.balance)}</p>
          </div>
          <div className="bg-white border border-[#141414] p-3.5">
            <p className="text-[11px] font-mono uppercase text-[#141414]/60">Sales This Month</p>
            <p className="text-lg font-black font-mono mt-1">{fmtKsh(summary.month_gross)}</p>
          </div>
          <div className="bg-white border border-[#141414] p-3.5">
            <p className="text-[11px] font-mono uppercase text-[#141414]/60">Commission ({Number(summary.commission_rate)}%)</p>
            <p className="text-lg font-black font-mono mt-1">{fmtKsh(summary.month_commission)}</p>
          </div>
          <div className="bg-white border border-[#141414] p-3.5">
            <p className="text-[11px] font-mono uppercase text-[#141414]/60">Fees This Month</p>
            <p className="text-lg font-black font-mono mt-1">{fmtKsh(summary.month_fees)}</p>
          </div>
          <div className="bg-white border border-[#141414] p-3.5">
            <p className="text-[11px] font-mono uppercase text-[#141414]/60">Withdrawn</p>
            <p className="text-lg font-black font-mono mt-1">{fmtKsh(summary.month_withdrawn)}</p>
          </div>
        </div>
      )}

      <Panel title="Withdraw earnings">
        {!settlement?.has_account ? (
          <p className="text-xs font-mono text-[#141414]/70 max-w-md">
            Add your payout account in <b>Settings → Payments</b> first — every withdrawal
            goes there. Changing it later needs a code we email you.
          </p>
        ) : (
          <form onSubmit={withdraw} className="grid grid-cols-1 md:grid-cols-3 gap-3 items-end max-w-2xl">
            <Field label={`Amount (min ${fmtKsh(summary?.minimum_payout ?? 100)})`}>
              <input type="number" min="100" step="0.01" required value={amount} onChange={(e) => setAmount(e.target.value)} className={inputCls} />
            </Field>
            {/* No destination fields: money goes to the ONE verified settlement account,
                shown read-only. It can't be redirected here — that would bypass the
                change-code protection. */}
            <div className="text-xs font-mono">
              <div className="text-[10px] uppercase text-[#141414]/50 mb-1">Pays out to</div>
              <div className="border border-[#141414]/20 bg-[#f4f4f2] px-2.5 py-2 truncate" title={settlement.destination ?? ''}>
                {settlement.destination}
              </div>
            </div>
            <Btn type="submit" variant="green" disabled={busy}>
              <ArrowDownToLine className="h-3.5 w-3.5" />
              {busy ? 'Requesting…' : 'Withdraw'}
            </Btn>
          </form>
        )}

        {/* Transfer-cost breakdown — the ISP sees exactly what they'll receive and where the
            cost goes, before they commit. */}
        {quote && Number(quote.amount) > 0 && (
          <div className="mt-3 max-w-md border border-[#141414]/20 bg-[#f4f4f2] p-3 text-xs font-mono">
            <div className="flex justify-between py-0.5">
              <span className="text-[#141414]/60">Withdraw</span>
              <span>{fmtKsh(Number(quote.amount))}</span>
            </div>
            <div className="flex justify-between py-0.5 text-[#B26B00]">
              <span>Transfer cost → {quote.cost_destination}</span>
              <span>− {fmtKsh(Number(quote.cost))}</span>
            </div>
            <div className="flex justify-between py-1 mt-1 border-t border-[#141414]/15 font-bold">
              <span>You receive</span>
              <span>{fmtKsh(Number(quote.net))}</span>
            </div>
            <p className="mt-1.5 text-[10px] leading-relaxed text-[#141414]/55 font-sans">{quote.note}</p>
          </div>
        )}

        {settlement?.has_account && (
          <p className="text-[11px] font-mono text-[#141414]/50 mt-2">
            Paid out by the platform to your registered account.
          </p>
        )}
        {payouts.filter((p) => p.status === 'requested').length > 0 && (
          <p className="text-[11px] font-mono text-[#B26B00] mt-1">
            {payouts.filter((p) => p.status === 'requested').length} withdrawal(s) awaiting payment by the platform.
          </p>
        )}
      </Panel>

      {/* Where the money actually goes. The go-live banner is gone once they're
          live, so this is the only place a trading ISP can find — or change — it. */}
      <Panel title="Payout account">
        <SettlementSetup onWentLive={load} />
      </Panel>

      <TableShell
        headers={['When', 'Type', 'Details', 'Amount']}
        loading={ledger === null}
        error={error}
        empty="No wallet activity yet — it starts with your first customer payment."
      >
        {(ledger ?? []).map((e) => (
          <tr key={e.id} className="hover:bg-[#f0efec]/40 transition">
            <td className={`${tdCls} font-mono whitespace-nowrap`}>{fmtDateTime(e.created_at)}</td>
            <td className={tdCls}>
              <Badge color={ENTRY_LABEL[e.entry_type].color}>{ENTRY_LABEL[e.entry_type].label}</Badge>
            </td>
            <td className={`${tdCls} text-[#141414]/70`}>{e.memo || '—'}</td>
            <td className={`${tdCls} font-mono font-bold text-right whitespace-nowrap ${Number(e.amount) < 0 ? 'text-[#B22222]' : 'text-[#228B22]'}`}>
              {Number(e.amount) > 0 ? '+' : ''}{fmtKsh(e.amount)}
            </td>
          </tr>
        ))}
      </TableShell>
    </div>
  );
}
