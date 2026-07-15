import { useEffect, useState } from 'react';
import { Info, Loader2 } from 'lucide-react';
import { api, ApiError, PppoeSettings } from '../../api/client';
import { Btn, Field, inputCls, Panel, toast } from '../ui';

/**
 * Settings > PPPoE — how an ISP runs their fixed-line business: when dormant accounts are
 * pruned, when subscribers are reminded before renewal, and how invoices are numbered.
 *
 * Every control here drives a real backbone task. The one exception is FUP alerts, which
 * need per-client data metering the platform does not have yet — so the threshold saves,
 * but the card says plainly that it is not firing rather than pretend.
 */
export default function PppoePanel() {
  const [s, setS] = useState<PppoeSettings | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.pppoeSettings
      .get()
      .then(setS)
      .catch(() => toast('error', 'Could not load your PPPoE settings.'));
  }, []);

  if (!s) {
    return (
      <div className="flex items-center gap-2 p-6 text-sm text-[#141414]/50">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading…
      </div>
    );
  }

  const set = (patch: Partial<PppoeSettings>) => setS((prev) => (prev ? { ...prev, ...patch } : prev));

  const toggleIn = (list: number[], value: number): number[] =>
    list.includes(value) ? list.filter((v) => v !== value) : [...list, value].sort((a, b) => a - b);

  const save = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const saved = await api.pppoeSettings.update({
        inactive_prune_days: s.inactive_prune_days,
        pre_expiry_reminder_hours: s.pre_expiry_reminder_hours,
        fup_alert_percents: s.fup_alert_percents,
        auto_generate_invoices: s.auto_generate_invoices,
        invoice_prefix: s.invoice_prefix,
      });
      setS(saved);
      toast('success', 'PPPoE settings saved.');
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'Could not save.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <p className="text-xs leading-relaxed text-[#141414]/60">
        Always-on fixed-line subscribers — how long inactive accounts hang around, when they
        hear from you before renewal, and how invoices are issued.
      </p>

      {/* --- Lifecycle ------------------------------------------------------------ */}
      <Panel title="Lifecycle">
        <p className="mb-3 text-xs text-[#141414]/55">
          Pruning of dormant fixed-line accounts.
        </p>
        <Field label="Inactive prune">
          <p className="mb-2 text-[11px] leading-relaxed text-[#141414]/50">
            Auto-delete <b>disabled</b> accounts untouched for this many days. Accounts with
            any billing history are always kept. Pick Never to keep them indefinitely.
          </p>
          <ChipRow
            options={[{ label: 'Never', value: null }, ...s.choices.prune_days.map((d) => ({ label: `${d} days`, value: d }))]}
            selected={[s.inactive_prune_days]}
            onPick={(v) => set({ inactive_prune_days: v as number | null })}
          />
        </Field>
      </Panel>

      {/* --- Reminders & alerts --------------------------------------------------- */}
      <Panel title="Reminders & alerts">
        <p className="mb-3 text-xs text-[#141414]/55">
          When subscribers hear from you before renewal and as they consume data.
        </p>

        <Field label="Pre-expiry reminders" className="mb-4">
          <p className="mb-2 text-[11px] text-[#141414]/50">
            Subscribers get an SMS this many hours before renewal. Pick any that apply.
          </p>
          <ChipRow
            multi
            options={s.choices.reminder_hours.map((h) => ({ label: `${h}h`, value: h }))}
            selected={s.pre_expiry_reminder_hours}
            onPick={(v) => set({ pre_expiry_reminder_hours: toggleIn(s.pre_expiry_reminder_hours, v as number) })}
          />
        </Field>

        <Field label="FUP alerts">
          <p className="mb-2 flex items-start gap-1.5 text-[11px] leading-relaxed text-[#141414]/50">
            <Info className="mt-0.5 h-3 w-3 shrink-0" />
            Notify when monthly data usage crosses these percentages.
            {!s.fup_metering_ready && (
              <span className="text-[#B22222]/80">
                {' '}Saved, but not firing yet — data metering for PPPoE lines is coming.
              </span>
            )}
          </p>
          <ChipRow
            multi
            dimmed={!s.fup_metering_ready}
            options={s.choices.fup_percents.map((p) => ({ label: `${p}%`, value: p }))}
            selected={s.fup_alert_percents}
            onPick={(v) => set({ fup_alert_percents: toggleIn(s.fup_alert_percents, v as number) })}
          />
        </Field>
      </Panel>

      {/* --- Invoicing ------------------------------------------------------------ */}
      <Panel title="Invoicing">
        <p className="mb-3 text-xs text-[#141414]/55">
          Auto-mint invoices on subscription renewals.
        </p>
        <label className="mb-4 flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={s.auto_generate_invoices}
            onChange={(e) => set({ auto_generate_invoices: e.target.checked })}
          />
          Auto-generate invoices on each client's billing anniversary
        </label>
        <Field label="Invoice number prefix" className="max-w-xs">
          <input
            className={inputCls}
            value={s.invoice_prefix}
            maxLength={8}
            onChange={(e) => set({ invoice_prefix: e.target.value.replace(/[^A-Za-z0-9]/g, '') })}
            placeholder="INV"
          />
          <p className="text-[10px] text-[#141414]/45">
            e.g. INV → {s.invoice_prefix || 'INV'}-001234.
          </p>
        </Field>
      </Panel>

      <div className="flex justify-end">
        <Btn onClick={save} disabled={busy}>
          {busy ? 'Saving…' : 'Save settings'}
        </Btn>
      </div>
    </div>
  );
}

function ChipRow({
  options,
  selected,
  onPick,
  multi = false,
  dimmed = false,
}: {
  options: { label: string; value: number | null }[];
  selected: (number | null)[];
  onPick: (value: number | null) => void;
  multi?: boolean;
  dimmed?: boolean;
}) {
  return (
    <div className={`flex flex-wrap gap-1.5 ${dimmed ? 'opacity-70' : ''}`}>
      {options.map((o) => {
        const active = selected.includes(o.value);
        return (
          <button
            key={String(o.value)}
            onClick={() => onPick(o.value)}
            className={`border px-3 py-1.5 font-mono text-xs transition ${
              active
                ? 'border-[#141414] bg-[#141414] text-[#E4E3E0]'
                : 'border-[#141414]/25 bg-white hover:border-[#141414]'
            }`}
          >
            {o.label}
          </button>
        );
      })}
      {multi && <span className="self-center pl-1 text-[10px] text-[#141414]/40">choose any</span>}
    </div>
  );
}
