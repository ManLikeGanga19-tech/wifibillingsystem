import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Wallet, ArrowDownToLine, Loader2 } from 'lucide-react';
import { api, ApiLedgerEntry, ApiPayout, Settlement, WalletSummary } from '../api/client';
import ConfirmPayout from './ConfirmPayout';
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
  const [method, setMethod] = useState<'mpesa' | 'bank'>('mpesa');
  const [phone, setPhone] = useState('');
  const [bank, setBank] = useState({ bank_name: '', bank_account_number: '', bank_account_name: '' });
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
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
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const withdraw = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    try {
      await api.billing.payouts.withdraw(
        method === 'mpesa' ? { amount, method, phone } : { amount, method, ...bank }
      );
      toast('success', 'Withdrawal requested — the platform will pay it out shortly.');
      setAmount('');
      load();
    } catch (err) {
      toast('error', err instanceof Error ? err.message : 'Withdrawal failed.');
    } finally {
      setBusy(false);
    }
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
        subtitle="Customer payments are collected by Danamo Tech and credited here, with the platform commission already deducted. Withdraw to M-Pesa anytime."
      >
        <RefreshBtn onClick={load} />
      </ViewHeader>

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
        <div className="flex border border-[#141414] mb-3 max-w-xs">
          {(['mpesa', 'bank'] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMethod(m)}
              className={`flex-1 py-2 text-xs font-bold font-mono uppercase transition cursor-pointer ${
                method === m ? 'bg-[#141414] text-[#E4E3E0]' : 'bg-white text-[#141414]'
              }`}
            >
              {m === 'mpesa' ? 'M-Pesa' : 'Bank'}
            </button>
          ))}
        </div>
        <form onSubmit={withdraw} className="grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
          <Field label={`Amount (min ${fmtKsh(summary?.minimum_payout ?? 100)})`}>
            <input type="number" min="100" step="0.01" required value={amount} onChange={(e) => setAmount(e.target.value)} className={inputCls} />
          </Field>
          {method === 'mpesa' ? (
            <Field label="M-Pesa number">
              <input type="tel" required value={phone} onChange={(e) => setPhone(e.target.value)} placeholder="07XX…" className={inputCls} />
            </Field>
          ) : (
            <>
              <Field label="Bank">
                <input required value={bank.bank_name} onChange={(e) => setBank({ ...bank, bank_name: e.target.value })} placeholder="e.g. I&M Bank" className={inputCls} />
              </Field>
              <Field label="Account number">
                <input required value={bank.bank_account_number} onChange={(e) => setBank({ ...bank, bank_account_number: e.target.value })} className={inputCls} />
              </Field>
              <Field label="Account name">
                <input value={bank.bank_account_name} onChange={(e) => setBank({ ...bank, bank_account_name: e.target.value })} className={inputCls} />
              </Field>
            </>
          )}
          <Btn type="submit" variant="green" disabled={busy}>
            <ArrowDownToLine className="h-3.5 w-3.5" />
            {busy ? 'Requesting…' : 'Withdraw'}
          </Btn>
        </form>
        <p className="text-[11px] font-mono text-[#141414]/50 mt-2">
          {method === 'bank'
            ? 'Bank withdrawals are sent by the platform via EFT/Pesalink and marked paid.'
            : 'Paid to your M-Pesa number by the platform.'}
        </p>
        {payouts.filter((p) => p.status === 'requested').length > 0 && (
          <p className="text-[11px] font-mono text-[#B26B00] mt-1">
            {payouts.filter((p) => p.status === 'requested').length} withdrawal(s) awaiting payment by the platform.
          </p>
        )}
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
