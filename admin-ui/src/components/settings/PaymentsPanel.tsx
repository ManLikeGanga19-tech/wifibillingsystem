import { Fragment, useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Check, Clock, Copy, Loader2, Lock, Send, Zap } from 'lucide-react';
import {
  api,
  ApiError,
  GatewayField,
  PaymentGatewayCard,
  PaymentGatewaysState,
} from '../../api/client';
import { Btn, Field, inputCls, Panel, toast } from '../ui';
import SettlementSetup from '../SettlementSetup';

/**
 * Payments — the gateway an ISP's subscribers pay them through.
 *
 * One active at a time. The default is our own paybill, so a brand-new ISP can sell today
 * while Safaricom takes weeks to approve their own shortcode. Switching to their own M-Pesa
 * means the money reaches them INSTANTLY — we never touch it — and our fee is invoiced
 * instead of withheld.
 *
 * Two settlements, made visible on every card, because it is the whole reason an ISP would
 * switch: "To your WIFI.OS wallet" (we hold it, you withdraw) vs "Straight to your own
 * M-Pesa" (instant, ours to invoice).
 */
export default function PaymentsPanel() {
  const [state, setState] = useState<PaymentGatewaysState | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  const load = useCallback(() => {
    api.paymentGateways
      .get()
      .then(setState)
      .catch(() => toast('error', 'Could not load your payment gateways.'));
  }, []);

  useEffect(load, [load]);

  if (!state) {
    return (
      <div className="flex items-center gap-2 p-6 text-sm text-[#141414]/50">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading…
      </div>
    );
  }

  const connected = state.gateways.filter((g) => g.available).length;
  const opened = state.gateways.find((g) => g.id === open) ?? null;

  return (
    <div className="space-y-5">
      <p className="text-xs leading-relaxed text-[#141414]/60">
        Pick one gateway so subscribers can pay you. Only one is active at a time — switching
        is one click, and saved credentials are kept. {connected} gateway
        {connected === 1 ? '' : 's'} available.
      </p>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {state.gateways.map((g) => (
          <Fragment key={g.id}>
            <GatewayCard gateway={g} onConfigure={() => setOpen(g.id)} onChanged={load} />
          </Fragment>
        ))}
      </div>

      {/* Where the ISP's OWN money goes when they collect on our paybill. Still needed —
          the aggregator path is the default, and a wallet balance has to land somewhere. */}
      <Panel title="Where you get paid">
        <p className="mb-4 text-xs leading-relaxed text-[#141414]/60">
          When customers pay through the <b>WIFI.OS paybill</b>, we hold the money in your
          wallet and send it here when you withdraw. Gateways you own settle to you directly,
          so this does not apply to them.
        </p>
        <SettlementSetup onWentLive={load} />
      </Panel>

      {opened && (
        <ConfigureModal
          gateway={opened}
          onClose={() => setOpen(null)}
          onSaved={() => {
            setOpen(null);
            load();
          }}
        />
      )}
    </div>
  );
}

function GatewayCard({
  gateway,
  onConfigure,
  onChanged,
}: {
  gateway: PaymentGatewayCard;
  onConfigure: () => void;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);

  const activate = async () => {
    setBusy(true);
    try {
      await api.paymentGateways.activate(gateway.id);
      toast('success', `Subscribers now pay you through ${gateway.name}.`);
      onChanged();
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'Could not switch gateway.');
    } finally {
      setBusy(false);
    }
  };

  const dim = !gateway.available;

  return (
    <div
      className={`flex flex-col border p-4 transition ${
        gateway.active ? 'border-[#141414] bg-white' : 'border-[#141414]/20 bg-white'
      } ${dim ? 'opacity-55' : ''}`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-mono text-sm font-bold">{gateway.name}</p>
          <p className="mt-0.5 text-[11px] text-[#141414]/50">{gateway.region}</p>
        </div>
        {gateway.active ? (
          <span className="flex shrink-0 items-center gap-1 bg-[#228B22] px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase text-white">
            <Check className="h-3 w-3" /> Active
          </span>
        ) : !gateway.available ? (
          <span className="flex shrink-0 items-center gap-1 border border-[#141414]/25 px-1.5 py-0.5 font-mono text-[10px] uppercase text-[#141414]/45">
            <Clock className="h-3 w-3" /> Soon
          </span>
        ) : gateway.configured ? (
          <span className="shrink-0 border border-[#141414]/30 px-1.5 py-0.5 font-mono text-[10px] uppercase text-[#141414]/60">
            Ready
          </span>
        ) : null}
      </div>

      {gateway.methods.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1">
          {gateway.methods.map((m) => (
            <span
              key={m}
              className="border border-[#141414]/15 bg-[#f4f3f0] px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wide text-[#141414]/55"
            >
              {m}
            </span>
          ))}
        </div>
      )}

      {gateway.settles && (
        <p className="mt-2 flex items-center gap-1 text-[11px] font-bold text-[#141414]/70">
          <Zap className="h-3 w-3" /> {gateway.settles}
        </p>
      )}

      {gateway.note && (
        <p className="mt-2 text-[11px] leading-relaxed text-[#141414]/55">{gateway.note}</p>
      )}

      {gateway.available && (
        <div className="mt-3 flex gap-2 pt-1">
          {!gateway.managed && (
            <Btn onClick={onConfigure} variant="outline">
              {gateway.configured ? 'Manage' : 'Configure'}
            </Btn>
          )}
          {!gateway.active && (gateway.configured || gateway.managed) && (
            <Btn onClick={activate} disabled={busy}>
              {busy ? '…' : 'Use this'}
            </Btn>
          )}
        </div>
      )}
    </div>
  );
}

/** Credentials for one gateway, plus a test charge and the webhook URL to register. */
function ConfigureModal({
  gateway,
  onClose,
  onSaved,
}: {
  gateway: PaymentGatewayCard;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(gateway.fields.map((f) => [f.key, f.value]))
  );
  const [busy, setBusy] = useState(false);
  const [testPhone, setTestPhone] = useState('');
  const [testing, setTesting] = useState(false);

  const save = async (activate: boolean) => {
    if (busy) return;
    setBusy(true);
    try {
      await api.paymentGateways.configure(gateway.id, values, activate);
      toast('success', activate ? `${gateway.name} is now taking payments.` : 'Credentials saved.');
      onSaved();
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'Could not save those credentials.');
    } finally {
      setBusy(false);
    }
  };

  const sendTest = async () => {
    if (!testPhone.trim() || testing) return;
    setTesting(true);
    try {
      const { detail } = await api.paymentGateways.test(gateway.id, testPhone.trim());
      toast('success', detail);
    } catch (e) {
      // Safaricom's own words — "invalid passkey" is the whole value here.
      toast('error', e instanceof ApiError ? e.message : 'The test charge did not go out.');
    } finally {
      setTesting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[#141414]/50 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-[90vh] w-full max-w-lg overflow-y-auto border border-[#141414] bg-[#E4E3E0] p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="font-mono text-sm font-bold uppercase">{gateway.name}</h3>
        <p className="mb-4 text-xs text-[#141414]/55">{gateway.region}</p>

        <div className="space-y-3">
          {gateway.fields.map((f) => (
            <Fragment key={f.key}>
              <GatewayFieldInput
                field={f}
                value={values[f.key] ?? ''}
                onChange={(v) => setValues((prev) => ({ ...prev, [f.key]: v }))}
              />
            </Fragment>
          ))}
        </div>

        {gateway.webhook_url && (
          <div className="mt-4 border border-[#141414]/20 bg-white p-3">
            <p className="font-mono text-[10px] font-bold uppercase tracking-wide text-[#141414]/60">
              Your callback URL
            </p>
            <p className="mt-1 text-[11px] leading-relaxed text-[#141414]/55">
              Register this as the validation/confirmation URL on your Daraja app, so we hear
              when a customer pays.
            </p>
            <div className="mt-2 flex items-center gap-2">
              <code className="min-w-0 flex-1 truncate border border-[#141414]/20 bg-[#f4f3f0] px-2 py-1 text-[11px]">
                {gateway.webhook_url}
              </code>
              <button
                onClick={() => {
                  navigator.clipboard?.writeText(gateway.webhook_url);
                  toast('info', 'Copied.');
                }}
                className="shrink-0 border border-[#141414]/30 p-1.5 hover:bg-[#f0efec]"
                title="Copy"
              >
                <Copy className="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        )}

        <div className="mt-4 border-t border-[#141414]/15 pt-4">
          <p className="mb-2 flex items-center gap-1.5 font-mono text-[10px] font-bold uppercase tracking-wide text-[#141414]/60">
            <Send className="h-3 w-3" /> Prove it works
          </p>
          <p className="mb-2 text-[11px] leading-relaxed text-[#141414]/55">
            Charge KSh 1 to your own phone. A wrong key fails silently in production, at a
            customer — find out now instead.
          </p>
          <div className="flex flex-col gap-2 sm:flex-row">
            <input
              className={`${inputCls} flex-1`}
              value={testPhone}
              onChange={(e) => setTestPhone(e.target.value)}
              placeholder="07XX XXX XXX"
              inputMode="tel"
            />
            <Btn onClick={sendTest} variant="outline" disabled={testing || !testPhone.trim()}>
              {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Zap className="h-4 w-4" />}
              {testing ? 'Sending…' : 'Test charge'}
            </Btn>
          </div>
        </div>

        <div className="mt-5 flex items-center justify-end gap-2 border-t border-[#141414]/15 pt-4">
          <Btn onClick={() => save(false)} variant="outline" disabled={busy}>
            Save
          </Btn>
          {!gateway.active && (
            <Btn onClick={() => save(true)} disabled={busy}>
              {busy ? 'Saving…' : 'Save & use'}
            </Btn>
          )}
        </div>
      </div>
    </div>
  );
}

function GatewayFieldInput({
  field,
  value,
  onChange,
}: {
  field: GatewayField;
  value: string;
  onChange: (v: string) => void;
}) {
  if (field.choices.length > 0) {
    return (
      <Field label={field.label}>
        <select className={inputCls} value={value} onChange={(e) => onChange(e.target.value)}>
          {field.choices.map((c) => (
            <option key={c.value} value={c.value}>
              {c.label}
            </option>
          ))}
        </select>
        {field.help && (
          <p className="text-[10px] leading-relaxed text-[#141414]/45">{field.help}</p>
        )}
      </Field>
    );
  }

  return (
    <Field label={field.label + (field.required ? '' : ' (optional)')}>
      <div className="relative">
        {field.secret && (
          <Lock className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#141414]/35" />
        )}
        <input
          className={`${inputCls} ${field.secret ? 'pl-8' : ''}`}
          type={field.secret ? 'password' : 'text'}
          autoComplete={field.secret ? 'new-password' : 'off'}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={field.secret && field.set ? 'Saved — type to replace it' : field.placeholder}
        />
      </div>
      {field.secret ? (
        <p className="flex items-start gap-1 text-[10px] leading-relaxed text-[#141414]/45">
          <AlertTriangle className="mt-0.5 h-2.5 w-2.5 shrink-0" />
          {field.set
            ? 'Stored encrypted. We cannot show it back — leave blank to keep it.'
            : 'Stored encrypted, and never shown again once saved.'}
        </p>
      ) : (
        field.help && (
          <p className="text-[10px] leading-relaxed text-[#141414]/45">{field.help}</p>
        )
      )}
    </Field>
  );
}
