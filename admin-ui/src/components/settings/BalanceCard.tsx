import { useEffect, useRef, useState } from 'react';
import { AlertTriangle, Check, Loader2, Plus, Smartphone, X, Zap } from 'lucide-react';
import { api, ApiError, PlatformAccount } from '../../api/client';
import { Btn, Field, inputCls, Panel, toast } from '../ui';

/**
 * The ISP's balance WITH WIFI.OS — what pays for the managed SMS gateway.
 *
 * Not the wallet. The wallet is money we hold FOR them; this is money they have paid TO
 * us. An ISP selling through their own payment gateway never has a wallet balance at all,
 * yet still owes us for every SMS we send on their behalf — which is exactly why this is
 * topped up by M-Pesa rather than deducted from a wallet that may not exist.
 *
 * It can go NEGATIVE. That is not an error, it is postpaid: fees accrue as they happen.
 */
export default function BalanceCard({
  account,
  onChanged,
}: {
  account: PlatformAccount;
  onChanged: () => void;
}) {
  const [topping, setTopping] = useState(false);
  const [editingAlerts, setEditingAlerts] = useState(false);

  const balance = Number(account.balance);
  const negative = balance < 0;

  return (
    <Panel title="SMS balance">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p
            className={`font-mono text-3xl font-black tabular-nums ${
              negative ? 'text-[#B22222]' : ''
            }`}
          >
            KSh {balance.toLocaleString()}
          </p>
          <p className="mt-0.5 text-xs text-[#141414]/55">
            {negative ? (
              <>
                You owe this. Top up to start sending again — at KSh {account.sms_price} per
                message.
              </>
            ) : (
              <>
                About <b>{account.sms_remaining.toLocaleString()}</b> messages left, at KSh{' '}
                {account.sms_price} each.
              </>
            )}
          </p>
        </div>

        <div className="flex gap-2">
          <Btn onClick={() => setTopping(true)}>
            <Plus className="h-3.5 w-3.5" /> Top up
          </Btn>
          <Btn onClick={() => setEditingAlerts((v) => !v)} variant="outline">
            Low-balance alerts
          </Btn>
        </div>
      </div>

      {/* The state that actually costs them customers. */}
      {!account.can_send_sms && (
        <p className="mt-3 flex gap-2 border border-[#B22222]/40 bg-[#B22222]/5 p-3 text-xs leading-relaxed text-[#B22222]">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            <b>Your customers are not getting their receipts.</b> SMS is switched off until you
            top up — every payment confirmation and expiry warning is being dropped.
          </span>
        </p>
      )}
      {account.can_send_sms && account.low && (
        <p className="mt-3 flex gap-2 border border-[#141414]/20 bg-[#f4f3f0] p-3 text-xs leading-relaxed text-[#141414]/70">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          Running low. Top up before your customers stop getting receipts.
        </p>
      )}

      {editingAlerts && <AlertSettings account={account} onSaved={onChanged} />}

      {topping && (
        <TopUpModal
          account={account}
          onClose={() => setTopping(false)}
          onPaid={() => {
            setTopping(false);
            onChanged();
          }}
        />
      )}
    </Panel>
  );
}

/** Pick a bundle, get an STK prompt, watch it land. */
function TopUpModal({
  account,
  onClose,
  onPaid,
}: {
  account: PlatformAccount;
  onClose: () => void;
  onPaid: () => void;
}) {
  const [phone, setPhone] = useState('');
  const [bundle, setBundle] = useState(account.bundles[1]?.id ?? account.bundles[0]?.id ?? '');
  const [custom, setCustom] = useState('');
  const [useCustom, setUseCustom] = useState(false);

  const [topUpId, setTopUpId] = useState<number | null>(null);
  const [state, setState] = useState<'idle' | 'sending' | 'waiting' | 'paid' | 'failed'>('idle');
  const [message, setMessage] = useState('');
  const timer = useRef<number | null>(null);

  // Poll while they are entering their PIN. The server also reconciles against Daraja on a
  // timer, so a dropped callback still lands — this poll just makes it visible.
  useEffect(() => {
    if (topUpId === null || state !== 'waiting') return;
    const started = Date.now();
    const tick = async () => {
      try {
        const s = await api.account.topUpStatus(topUpId);
        if (s.status === 'success') {
          setState('paid');
          toast('success', `KSh ${Number(s.credit).toLocaleString()} added to your balance.`);
          window.setTimeout(onPaid, 1200);
          return;
        }
        if (s.status === 'failed' || s.status === 'timeout') {
          setState('failed');
          setMessage(s.result_desc || 'The payment did not go through.');
          return;
        }
      } catch {
        /* keep polling — a blip must not strand a payment that may have succeeded */
      }
      if (Date.now() - started > 120_000) {
        setState('failed');
        setMessage("We haven't heard from M-Pesa yet. If you paid, it will land shortly.");
        return;
      }
      timer.current = window.setTimeout(tick, 2500);
    };
    timer.current = window.setTimeout(tick, 2500);
    return () => {
      if (timer.current) window.clearTimeout(timer.current);
    };
  }, [topUpId, state, onPaid]);

  const pay = async () => {
    if (!phone.trim() || state === 'sending') return;
    setState('sending');
    try {
      const started = await api.account.topUp({
        phone: phone.trim(),
        ...(useCustom ? { amount: custom } : { bundle }),
      });
      setTopUpId(started.id);
      setMessage(started.detail);
      setState('waiting');
    } catch (e) {
      setState('idle');
      toast('error', e instanceof ApiError ? e.message : 'Could not start the payment.');
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[#141414]/50 p-4"
      onClick={state === 'waiting' ? undefined : onClose}
    >
      <div
        className="max-h-[90vh] w-full max-w-lg overflow-y-auto border border-[#141414] bg-[#E4E3E0] p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between">
          <div>
            <h3 className="font-mono text-sm font-bold uppercase">Top up SMS balance</h3>
            <p className="text-xs text-[#141414]/55">Paid by M-Pesa, straight to WIFI.OS.</p>
          </div>
          {state !== 'waiting' && (
            <button onClick={onClose} className="text-[#141414]/50 hover:text-[#141414]">
              <X className="h-4 w-4" />
            </button>
          )}
        </div>

        {state === 'paid' ? (
          <div className="flex flex-col items-center gap-3 py-8 text-center">
            <Check className="h-12 w-12 text-[#228B22]" />
            <p className="font-bold">Balance topped up.</p>
          </div>
        ) : state === 'waiting' ? (
          <div className="flex flex-col items-center gap-3 py-8 text-center">
            <Smartphone className="h-10 w-10" />
            <Loader2 className="h-5 w-5 animate-spin" />
            <p className="text-sm font-bold">Check your phone</p>
            <p className="max-w-xs text-xs leading-relaxed text-[#141414]/60">{message}</p>
          </div>
        ) : (
          <>
            <div className="grid gap-2 sm:grid-cols-2">
              {account.bundles.map((b) => {
                const active = !useCustom && bundle === b.id;
                return (
                  <button
                    key={b.id}
                    onClick={() => {
                      setUseCustom(false);
                      setBundle(b.id);
                    }}
                    className={`border p-3 text-left transition ${
                      active
                        ? 'border-[#141414] bg-[#141414] text-[#E4E3E0]'
                        : 'border-[#141414]/25 bg-white hover:border-[#141414]'
                    }`}
                  >
                    <p className="font-mono text-lg font-black tabular-nums">
                      {b.sms.toLocaleString()} SMS
                    </p>
                    <p
                      className={`text-[11px] ${active ? 'text-[#E4E3E0]/70' : 'text-[#141414]/55'}`}
                    >
                      KSh {Number(b.price).toLocaleString()} · {b.per_sms}/SMS
                    </p>
                    {Number(b.bonus) > 0 && (
                      <p
                        className={`mt-1 font-mono text-[10px] uppercase ${
                          active ? 'text-[#E4E3E0]/60' : 'text-[#228B22]'
                        }`}
                      >
                        +KSh {Number(b.bonus).toLocaleString()} bonus
                      </p>
                    )}
                  </button>
                );
              })}
            </div>

            <button
              onClick={() => setUseCustom((v) => !v)}
              className="mt-3 text-xs text-[#141414]/60 underline"
            >
              {useCustom ? 'Choose a bundle instead' : 'Or enter your own amount'}
            </button>

            {useCustom && (
              <Field label="Amount (KSh)" className="mt-2">
                <input
                  className={inputCls}
                  type="number"
                  value={custom}
                  onChange={(e) => setCustom(e.target.value)}
                  placeholder={`Minimum ${account.min_topup}`}
                />
              </Field>
            )}

            <Field label="M-Pesa number to charge" className="mt-4">
              <input
                className={inputCls}
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="07XX XXX XXX"
                inputMode="tel"
                autoFocus
              />
            </Field>

            <div className="mt-4 flex justify-end">
              <Btn onClick={pay} disabled={state === 'sending' || !phone.trim()}>
                {state === 'sending' ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Zap className="h-4 w-4" />
                )}
                {state === 'sending' ? 'Sending…' : 'Send M-Pesa prompt'}
              </Btn>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

/** Who we warn, and when — before the receipts stop. */
function AlertSettings({
  account,
  onSaved,
}: {
  account: PlatformAccount;
  onSaved: () => void;
}) {
  const [threshold, setThreshold] = useState(account.low_balance_threshold);
  const [phones, setPhones] = useState<string[]>(account.alert_phones);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);

  const addPhone = () => {
    const value = draft.trim().replace(/,$/, '');
    if (!value || phones.includes(value)) return;
    setPhones((p) => [...p, value]);
    setDraft('');
  };

  const save = async () => {
    setBusy(true);
    try {
      await api.account.alerts({ low_balance_threshold: threshold, alert_phones: phones });
      toast('success', 'Alert settings saved.');
      onSaved();
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'Could not save.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-4 border border-[#141414]/20 bg-white p-4">
      <p className="mb-3 text-xs leading-relaxed text-[#141414]/60">
        We text these numbers when the balance drops below the threshold — once per fall, not
        every hour. The warning itself is free: we never charge you for the message telling
        you that you cannot afford to send messages.
      </p>

      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Threshold (KSh)">
          <input
            className={inputCls}
            type="number"
            value={threshold}
            onChange={(e) => setThreshold(e.target.value)}
          />
        </Field>

        <Field label="Alert phone(s)">
          <input
            className={inputCls}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ',') {
                e.preventDefault();
                addPhone();
              }
            }}
            onBlur={addPhone}
            placeholder="07XX XXX XXX"
          />
          <p className="text-[10px] text-[#141414]/45">Press Enter or comma to add each number.</p>
        </Field>
      </div>

      {phones.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {phones.map((p) => (
            <span
              key={p}
              className="flex items-center gap-1 border border-[#141414]/30 bg-[#f0efec] px-2 py-0.5 font-mono text-xs"
            >
              {p}
              <button
                onClick={() => setPhones((list) => list.filter((x) => x !== p))}
                className="text-[#141414]/50 hover:text-[#B22222]"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      )}

      <div className="mt-4 flex justify-end">
        <Btn onClick={save} disabled={busy}>
          {busy ? 'Saving…' : 'Save alerts'}
        </Btn>
      </div>
    </div>
  );
}
