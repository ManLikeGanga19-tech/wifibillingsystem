import { ReactNode, useEffect, useState } from 'react';
import { Loader2, Check, Award, Users, Gift, Search, Ticket } from 'lucide-react';
import { api, LoyaltyAccountView, LoyaltySettings, LoyaltySummary } from '../../api/client';
import { Btn, Field, inputCls, Panel, toast } from '../ui';

/**
 * Settings > Loyalty points — reward subscribers for paying.
 *
 * Phase 1: the programme configuration (earn + redemption rules) plus a live view of the
 * programme working (enrolment + points outstanding + top holders). Earning is live;
 * redeeming points for account credit is the next phase, so the redemption rules save now
 * but the note says plainly that cashing in is coming rather than pretending it works.
 */
export default function LoyaltyPanel() {
  const [s, setS] = useState<LoyaltySettings | null>(null);
  const [summary, setSummary] = useState<LoyaltySummary | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.loyalty.get().then(setS).catch(() => toast('error', 'Could not load loyalty settings.'));
    api.loyalty.summary().then(setSummary).catch(() => {});
  }, []);

  if (!s) {
    return (
      <div className="flex items-center gap-2 p-6 text-sm text-[#141414]/50">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading…
      </div>
    );
  }

  const set = (patch: Partial<LoyaltySettings>) => setS((prev) => (prev ? { ...prev, ...patch } : prev));
  const num = (v: string, min = 0) => Math.max(min, parseInt(v || '0', 10) || 0);

  const save = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const saved = await api.loyalty.update({
        is_enabled: s.is_enabled,
        spend_per_point: s.spend_per_point,
        points_per_threshold: s.points_per_threshold,
        min_redeem_points: s.min_redeem_points,
        value_per_point: s.value_per_point,
      });
      setS(saved);
      toast('success', 'Loyalty settings saved.');
    } catch {
      toast('error', 'Could not save. Check the values and try again.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h2 className="text-lg font-bold font-mono uppercase tracking-wide">Loyalty points</h2>
        <p className="text-sm text-[#141414]/60 mt-1">
          Reward subscribers for payments. They accumulate points with each top-up and can
          redeem them for account credit.
        </p>
      </div>

      {/* Programme on/off */}
      <Panel title="Programme">
        <p className="text-xs text-[#141414]/60 -mt-1 mb-3">
          Enable or disable the loyalty programme for all subscribers on this workspace.
        </p>
        <label className="flex items-center gap-2.5 cursor-pointer">
          <input
            type="checkbox"
            checked={s.is_enabled}
            onChange={(e) => set({ is_enabled: e.target.checked })}
            className="accent-[#228B22] h-4 w-4"
          />
          <span className="text-sm font-bold">Enable loyalty points</span>
        </label>
      </Panel>

      <div className={s.is_enabled ? '' : 'opacity-50 pointer-events-none'}>
        {/* Earning */}
        <Panel title="Earning rules">
          <p className="text-xs text-[#141414]/60 -mt-1 mb-4">
            How many points a subscriber earns per payment.
          </p>
          <div className="grid sm:grid-cols-2 gap-4">
            <Field label="Spend per point">
              <div className="flex items-center gap-2">
                <span className="text-xs text-[#141414]/50">Ksh</span>
                <input
                  type="number"
                  min={1}
                  className={`${inputCls} w-28`}
                  value={s.spend_per_point}
                  onChange={(e) => set({ spend_per_point: num(e.target.value, 1) })}
                />
              </div>
              <p className="text-[11px] text-[#141414]/45 mt-1">
                Points are awarded once per this amount paid.
              </p>
            </Field>
            <Field label="Points per threshold">
              <input
                type="number"
                min={1}
                className={`${inputCls} w-28`}
                value={s.points_per_threshold}
                onChange={(e) => set({ points_per_threshold: num(e.target.value, 1) })}
              />
              <p className="text-[11px] text-[#141414]/45 mt-1">
                Points credited each time the spend threshold is crossed.
              </p>
            </Field>
          </div>
          <p className="text-[11px] text-[#141414]/55 mt-3 bg-[#f4f4f2] border border-[#141414]/10 p-2">
            e.g. a Ksh {(s.spend_per_point * 3).toLocaleString()} payment earns{' '}
            <b>{s.points_per_threshold * 3} points</b>.
          </p>
        </Panel>

        {/* Redemption */}
        <Panel title="Redemption rules" className="mt-6">
          <p className="text-xs text-[#141414]/60 -mt-1 mb-4">
            How subscribers cash in their points for account credit.
          </p>
          <div className="grid sm:grid-cols-2 gap-4">
            <Field label="Minimum to redeem">
              <input
                type="number"
                min={0}
                className={`${inputCls} w-28`}
                value={s.min_redeem_points}
                onChange={(e) => set({ min_redeem_points: num(e.target.value) })}
              />
              <p className="text-[11px] text-[#141414]/45 mt-1">
                Subscribers must hold at least this many points before redeeming.
              </p>
            </Field>
            <Field label="Value per point">
              <div className="flex items-center gap-2">
                <span className="text-xs text-[#141414]/50">Ksh</span>
                <input
                  type="text"
                  inputMode="decimal"
                  className={`${inputCls} w-28`}
                  value={s.value_per_point}
                  onChange={(e) => set({ value_per_point: e.target.value.replace(/[^0-9.]/g, '') })}
                />
              </div>
              <p className="text-[11px] text-[#141414]/45 mt-1">
                Ksh credited to the subscriber for each point redeemed.
              </p>
            </Field>
          </div>
          <p className="text-[11px] text-[#141414]/55 mt-3 bg-[#f4f4f2] border border-[#141414]/10 p-2">
            Redeeming turns points into a <b>reward voucher</b> for a plan — the customer enters
            the code at the hotspot to get online. A plan costs{' '}
            <b>{Number(s.value_per_point) > 0
              ? `price ÷ ${s.value_per_point}`
              : 'set a value per point'}</b>{' '}
            points (rounded up).
          </p>
        </Panel>
      </div>

      <div className="flex justify-end">
        <Btn variant="green" onClick={save} disabled={busy}>
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
          Save changes
        </Btn>
      </div>

      {s.is_enabled && <RedeemForCustomer />}

      {/* Programme health */}
      {summary && (
        <Panel title="Programme">
          <div className="grid grid-cols-2 gap-3 mb-4">
            <Stat icon={<Users className="h-4 w-4" />} label="Subscribers enrolled" value={summary.accounts.toLocaleString()} />
            <Stat icon={<Award className="h-4 w-4" />} label="Points outstanding" value={summary.points_outstanding.toLocaleString()} />
          </div>
          {summary.top.length > 0 ? (
            <div className="border border-[#141414]/15">
              <div className="px-3 py-1.5 border-b border-[#141414]/10 text-[10px] font-mono uppercase text-[#141414]/40">
                Top members
              </div>
              {summary.top.map((m) => (
                <div key={m.phone} className="flex items-center justify-between px-3 py-1.5 text-xs border-b border-[#141414]/5 last:border-0">
                  <span className="font-mono">{m.phone}</span>
                  <span className="font-bold">{m.points.toLocaleString()} pts</span>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-[#141414]/45">No points earned yet.</p>
          )}
        </Panel>
      )}
    </div>
  );
}

/**
 * Redeem a walk-in customer's points for a reward voucher (staff-assisted). Look them up by
 * phone, see what their balance can afford, redeem a plan, and read the customer the code.
 * Also the manual grant/deduct lever. Every action is server-audited.
 */
function RedeemForCustomer() {
  const [phone, setPhone] = useState('');
  const [acct, setAcct] = useState<LoyaltyAccountView | null>(null);
  const [busy, setBusy] = useState(false);
  const [code, setCode] = useState('');

  const lookup = async () => {
    const p = phone.trim();
    if (!p || busy) return;
    setBusy(true);
    setCode('');
    try {
      setAcct(await api.loyalty.account(p));
    } catch {
      toast('error', 'Could not look up that number.');
    } finally {
      setBusy(false);
    }
  };

  const redeem = async (planId: number) => {
    if (busy) return;
    setBusy(true);
    try {
      const r = await api.loyalty.redeem(phone.trim(), planId);
      setCode(r.voucher_code);
      toast('success', `Redeemed — code ${r.voucher_code}.`);
      await lookupSilent();
    } catch (e) {
      toast('error', e instanceof Error ? e.message : 'Could not redeem.');
    } finally {
      setBusy(false);
    }
  };

  const adjust = async (sign: 1 | -1) => {
    const raw = window.prompt(`Points to ${sign > 0 ? 'add' : 'remove'}?`);
    const n = Math.abs(parseInt(raw || '0', 10) || 0);
    if (!n) return;
    const reason = window.prompt('Reason (recorded)?') || '';
    if (!reason.trim()) {
      toast('error', 'A reason is required.');
      return;
    }
    setBusy(true);
    try {
      await api.loyalty.adjust(phone.trim(), sign * n, reason.trim());
      toast('success', 'Points adjusted.');
      await lookupSilent();
    } catch (e) {
      toast('error', e instanceof Error ? e.message : 'Could not adjust.');
    } finally {
      setBusy(false);
    }
  };

  const lookupSilent = async () => {
    try {
      setAcct(await api.loyalty.account(phone.trim()));
    } catch {
      /* keep the last view */
    }
  };

  return (
    <Panel title="Redeem for a customer" className="mt-6">
      <p className="text-xs text-[#141414]/60 -mt-1 mb-3">
        Look up a subscriber by phone, then redeem their points for a reward voucher or adjust
        their balance. Read the code to the customer — they enter it at the hotspot.
      </p>
      <div className="flex items-end gap-2">
        <Field label="Customer phone">
          <input
            className={`${inputCls} w-48`}
            placeholder="07XX…"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && lookup()}
          />
        </Field>
        <Btn onClick={lookup} disabled={busy || !phone.trim()}>
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Search className="h-3.5 w-3.5" />}
          Look up
        </Btn>
      </div>

      {code && (
        <div className="mt-3 flex items-center gap-2 bg-[#EAF7EA] border border-[#228B22]/40 p-2.5 text-sm">
          <Ticket className="h-4 w-4 text-[#228B22]" />
          <span>Reward voucher: <b className="font-mono tracking-wider">{code}</b> — read it to the customer.</span>
        </div>
      )}

      {acct && (
        <div className="mt-4 space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <Stat icon={<Award className="h-4 w-4" />} label="Balance" value={`${acct.points_balance.toLocaleString()} pts`} />
            <Stat icon={<Gift className="h-4 w-4" />} label="Worth" value={`Ksh ${Number(acct.value_kes).toLocaleString()}`} />
            <div className="flex gap-1.5 ml-auto">
              <Btn onClick={() => adjust(1)} disabled={busy}>+ Points</Btn>
              <Btn onClick={() => adjust(-1)} disabled={busy}>− Points</Btn>
            </div>
          </div>
          {!acct.found && (
            <p className="text-xs text-[#B26B00]">No account yet for this number — earning creates one on their first payment. You can still grant points with “+ Points”.</p>
          )}
          {acct.redeemable_plans.length > 0 ? (
            <div className="border border-[#141414]/15">
              <div className="px-3 py-1.5 border-b border-[#141414]/10 text-[10px] font-mono uppercase text-[#141414]/40">
                Redeem for a plan
              </div>
              {acct.redeemable_plans.map((p) => (
                <div key={p.plan_id} className="flex items-center justify-between px-3 py-2 text-sm border-b border-[#141414]/5 last:border-0">
                  <span>
                    <b>{p.plan_name}</b>
                    <span className="text-[#141414]/50 text-xs"> · Ksh {Number(p.price).toLocaleString()} · {p.points_cost.toLocaleString()} pts</span>
                  </span>
                  <Btn
                    variant={p.affordable ? 'green' : 'outline'}
                    onClick={() => redeem(p.plan_id)}
                    disabled={busy || !p.affordable}
                  >
                    {p.affordable ? 'Redeem' : 'Not enough'}
                  </Btn>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-[#141414]/45">Set a value per point above to enable redemption.</p>
          )}
        </div>
      )}
    </Panel>
  );
}

function Stat({ icon, label, value }: { icon: ReactNode; label: string; value: string }) {
  return (
    <div className="border border-[#141414]/15 bg-white p-3">
      <div className="flex items-center gap-1.5 text-[#141414]/50 text-[10px] font-mono uppercase">
        {icon} {label}
      </div>
      <div className="text-2xl font-black font-mono mt-1">{value}</div>
    </div>
  );
}
