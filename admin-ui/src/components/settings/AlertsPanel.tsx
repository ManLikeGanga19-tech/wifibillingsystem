import { useEffect, useState } from 'react';
import { Loader2, Check, RadioTower, HeartHandshake, Mail, X } from 'lucide-react';
import { api, ApiError, OperatorAlertSettings } from '../../api/client';
import { Btn, Field, inputCls, Panel, toast } from '../ui';

/**
 * Settings > Operator alerts — the ISP TEAM's own notifications (not their customers').
 * Three opt-in switches: router up/down alerts, outage compensation for fixed-line
 * subscribers, and a daily sales digest. All off by default.
 */
export default function AlertsPanel() {
  const [s, setS] = useState<OperatorAlertSettings | null>(null);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.alerts.get().then(setS).catch(() => toast('error', 'Could not load alert settings.'));
  }, []);

  if (!s) {
    return (
      <div className="flex items-center gap-2 p-6 text-sm text-[#141414]/50">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading…
      </div>
    );
  }

  const set = (patch: Partial<OperatorAlertSettings>) =>
    setS((prev) => (prev ? { ...prev, ...patch } : prev));

  const addPhone = () => {
    const value = draft.trim().replace(/,$/, '');
    if (!value || s.router_alert_phones.includes(value)) {
      setDraft('');
      return;
    }
    set({ router_alert_phones: [...s.router_alert_phones, value] });
    setDraft('');
  };
  const removePhone = (p: string) =>
    set({ router_alert_phones: s.router_alert_phones.filter((x) => x !== p) });

  const save = async () => {
    if (busy) return;
    // Fold a half-typed number in rather than silently dropping it on save.
    const phones = draft.trim()
      ? Array.from(new Set([...s.router_alert_phones, draft.trim().replace(/,$/, '')]))
      : s.router_alert_phones;
    setBusy(true);
    try {
      const saved = await api.alerts.update({ ...s, router_alert_phones: phones });
      setS(saved);
      setDraft('');
      toast('success', 'Alert settings saved.');
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'Could not save. Check the numbers.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h2 className="text-lg font-bold font-mono uppercase tracking-wide">Operator alerts</h2>
        <p className="text-sm text-[#141414]/60 mt-1">
          Team alerts — router status and sales digests — plus the outage-compensation policy
          that credits affected subscribers.
        </p>
      </div>

      {/* --- Router status alerts --------------------------------------------------- */}
      <Panel title="MikroTik status alerts">
        <p className="text-xs text-[#141414]/60 -mt-1 mb-3 flex items-center gap-1.5">
          <RadioTower className="h-3.5 w-3.5" />
          Get notified the moment a router goes offline or reconnects.
        </p>

        <label className="flex items-center gap-2.5 cursor-pointer">
          <input
            type="checkbox"
            checked={s.router_alerts_enabled}
            onChange={(e) => set({ router_alerts_enabled: e.target.checked })}
            className="accent-[#228B22] h-4 w-4"
          />
          <span className="text-sm font-bold">Enable status alerts</span>
        </label>

        <div className={`mt-4 ${s.router_alerts_enabled ? '' : 'opacity-50 pointer-events-none'}`}>
          <Field label="Alert phone numbers">
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
            <p className="text-[10px] text-[#141414]/45 mt-1">
              Press Enter to add. Empty = notify all admins.
            </p>
          </Field>

          {s.router_alert_phones.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1.5">
              {s.router_alert_phones.map((p) => (
                <span
                  key={p}
                  className="flex items-center gap-1 border border-[#141414]/30 bg-[#f0efec] px-2 py-0.5 font-mono text-xs"
                >
                  {p}
                  <button
                    type="button"
                    onClick={() => removePhone(p)}
                    className="text-[#141414]/50 hover:text-[#B22222]"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
            </div>
          )}

          <label className="mt-4 flex items-start gap-2.5 cursor-pointer">
            <input
              type="checkbox"
              checked={s.prefer_whatsapp}
              onChange={(e) => set({ prefer_whatsapp: e.target.checked })}
              className="accent-[#228B22] h-4 w-4 mt-0.5"
            />
            <span>
              <span className="text-sm font-bold">Prefer WhatsApp</span>
              <span className="block text-[11px] text-[#141414]/50">
                Send via WhatsApp instead of SMS when a gateway is configured. Falls back to SMS
                otherwise.
              </span>
            </span>
          </label>
        </div>
      </Panel>

      {/* --- Outage compensation ---------------------------------------------------- */}
      <Panel title="Outage compensation">
        <p className="text-xs text-[#141414]/60 -mt-1 mb-3 flex items-center gap-1.5">
          <HeartHandshake className="h-3.5 w-3.5" />
          When a router goes offline, credit the downtime back to affected subscribers' expiry
          once it recovers.
        </p>
        <label className="flex items-start gap-2.5 cursor-pointer">
          <input
            type="checkbox"
            checked={s.compensate_outages}
            onChange={(e) => set({ compensate_outages: e.target.checked })}
            className="accent-[#228B22] h-4 w-4 mt-0.5"
          />
          <span>
            <span className="text-sm font-bold">Compensate outages</span>
            <span className="block text-[11px] text-[#141414]/50">
              Driven by the same monitoring that powers MikroTik status alerts.
            </span>
          </span>
        </label>
        <p className="text-[11px] text-[#141414]/55 mt-3 bg-[#f4f4f2] border border-[#141414]/10 p-2 leading-relaxed">
          Applies to active fixed-line (PPPoE) subscribers on the affected router — each gets the
          exact downtime added to their next-due date once the router recovers. Blips under 10
          minutes are ignored, and every credit is recorded in your audit trail.
        </p>
      </Panel>

      {/* --- Sales digest ----------------------------------------------------------- */}
      <Panel title="Sales reports">
        <p className="text-xs text-[#141414]/60 -mt-1 mb-3 flex items-center gap-1.5">
          <Mail className="h-3.5 w-3.5" />
          Automated email digests so admins don't have to log in to check revenue.
        </p>
        <label className="flex items-start gap-2.5 cursor-pointer">
          <input
            type="checkbox"
            checked={s.sales_digest_enabled}
            onChange={(e) => set({ sales_digest_enabled: e.target.checked })}
            className="accent-[#228B22] h-4 w-4 mt-0.5"
          />
          <span>
            <span className="text-sm font-bold">Send sales digest</span>
            <span className="block text-[11px] text-[#141414]/50">
              A short email each morning with yesterday's takings, to your owner and contact
              addresses.
            </span>
          </span>
        </label>
      </Panel>

      <div className="flex justify-end">
        <Btn variant="green" onClick={save} disabled={busy}>
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
          Save changes
        </Btn>
      </div>
    </div>
  );
}
