import { Fragment, useCallback, useEffect, useState } from 'react';
import { AlertTriangle, Check, Loader2, Lock, Send, Zap } from 'lucide-react';
import {
  api,
  ApiError,
  CreditSummary,
  ProviderCard,
  ProvidersResponse,
} from '../../api/client';
import { Btn, Field, inputCls, Panel, toast } from '../ui';

/**
 * Communications — pick the gateway your messages leave on.
 *
 * A grid of providers, one live at a time. The WIFI.OS card is different in kind: it runs
 * on our account, so there is no credential to paste — the ISP buys SMS credits and we
 * meter them. Everything else is bring-your-own: their account, their sender ID, their
 * rate, their bill.
 *
 * Credentials are one-way. The server never sends a saved key back — it only says one is
 * stored — so an empty key box means "unchanged", never "deleted".
 */

type ChannelId = 'sms' | 'whatsapp';

export default function CommsPanel({ channel }: { channel: ChannelId }) {
  const [data, setData] = useState<ProvidersResponse | null>(null);
  const [open, setOpen] = useState<string | null>(null); // provider being configured
  const [testTo, setTestTo] = useState('');
  const [testing, setTesting] = useState(false);

  const load = useCallback(() => {
    api.messaging
      .providers(channel)
      .then(setData)
      .catch(() => toast('error', 'Could not load your gateways.'));
  }, [channel]);

  useEffect(() => {
    setData(null);
    setOpen(null);
    load();
  }, [load]);

  if (!data) {
    return (
      <div className="flex items-center gap-2 p-6 text-sm text-[#141414]/50">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading…
      </div>
    );
  }

  const sendTest = async () => {
    if (!testTo.trim() || testing) return;
    setTesting(true);
    try {
      const { detail } = await api.messaging.test(channel, testTo.trim());
      toast('success', detail);
    } catch (e) {
      // The gateway's own words. "Sender ID not approved" is the whole value here — a
      // generic "failed" would send them hunting.
      toast('error', e instanceof ApiError ? e.message : 'The test message did not go out.');
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="space-y-5">
      <p className="text-xs leading-relaxed text-[#141414]/60">
        {channel === 'sms'
          ? 'Outbound SMS for receipts, expiry warnings and alerts. Pick a provider and add its credentials — only one is active at a time.'
          : 'An optional, richer channel for receipts and reminders. Pick a provider and add its credentials — only one is active at a time.'}
      </p>

      {channel === 'sms' && data.credits && <CreditsCard credits={data.credits} onBought={load} />}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {data.providers.map((p) => (
          <Fragment key={p.id}>
            <GatewayCard
              provider={p}
              channel={channel}
              onConfigure={() => setOpen(p.id)}
              onChanged={load}
            />
          </Fragment>
        ))}
      </div>

      {channel === 'whatsapp' && data.note && (
        <p className="flex gap-2 border border-[#141414]/15 bg-[#f4f3f0] p-3 text-xs leading-relaxed text-[#141414]/60">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          {data.note}
        </p>
      )}

      <Panel title="Prove it works">
        <p className="mb-3 text-xs leading-relaxed text-[#141414]/60">
          Send yourself a real message on the live gateway. A wrong key or an unapproved
          sender ID fails quietly in production — you would only find out when a customer
          says they never got their code. Find out now instead.
        </p>
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            className={`${inputCls} flex-1`}
            value={testTo}
            onChange={(e) => setTestTo(e.target.value)}
            placeholder="2547XXXXXXXX"
          />
          <Btn onClick={sendTest} variant="outline" disabled={testing || !testTo.trim()}>
            {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            {testing ? 'Sending…' : 'Send test'}
          </Btn>
        </div>
      </Panel>

      {open && (
        <ConfigureModal
          channel={channel}
          provider={data.providers.find((p) => p.id === open)!}
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

/** One provider. Its state is the point: Connected / Ready / Configure. */
function GatewayCard({
  provider,
  channel,
  onConfigure,
  onChanged,
}: {
  provider: ProviderCard;
  channel: ChannelId;
  onConfigure: () => void;
  onChanged: () => void;
}) {
  const [busy, setBusy] = useState(false);

  const activate = async () => {
    setBusy(true);
    try {
      await api.messaging.activate(channel, provider.id);
      toast('success', `${provider.name} is now sending your messages.`);
      onChanged();
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'Could not switch gateway.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className={`flex flex-col border p-4 transition ${
        provider.active ? 'border-[#141414] bg-white' : 'border-[#141414]/20 bg-white'
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-mono text-sm font-bold">{provider.name}</p>
          <p className="mt-0.5 text-[11px] text-[#141414]/50">{provider.region}</p>
        </div>
        {provider.active ? (
          <span className="flex shrink-0 items-center gap-1 bg-[#228B22] px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase text-white">
            <Check className="h-3 w-3" /> Connected
          </span>
        ) : provider.configured ? (
          <span className="shrink-0 border border-[#141414]/30 px-1.5 py-0.5 font-mono text-[10px] uppercase text-[#141414]/60">
            Ready
          </span>
        ) : null}
      </div>

      {provider.note && (
        <p className="mt-2 text-[11px] leading-relaxed text-[#141414]/55">{provider.note}</p>
      )}

      <div className="mt-3 flex gap-2 pt-1">
        {!provider.managed && (
          <Btn onClick={onConfigure} variant="outline">
            {provider.configured ? 'Manage' : 'Configure'}
          </Btn>
        )}
        {!provider.active && (provider.configured || provider.managed) && (
          <Btn onClick={activate} disabled={busy}>
            {busy ? '…' : 'Use this'}
          </Btn>
        )}
      </div>
    </div>
  );
}

/** Credentials for one gateway. Secrets show a lock and a placeholder — never dots
 *  pretending to be a value we do not have. */
function ConfigureModal({
  channel,
  provider,
  onClose,
  onSaved,
}: {
  channel: ChannelId;
  provider: ProviderCard;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(provider.fields.map((f) => [f.key, f.value]))
  );
  const [busy, setBusy] = useState(false);

  const save = async (activate: boolean) => {
    if (busy) return;
    setBusy(true);
    try {
      await api.messaging.configure(channel, provider.id, values, activate);
      toast('success', activate ? `${provider.name} is now live.` : 'Credentials saved.');
      onSaved();
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'Could not save those credentials.');
    } finally {
      setBusy(false);
    }
  };

  const disconnect = async () => {
    setBusy(true);
    try {
      await api.messaging.disconnect(channel, provider.id);
      toast('info', `${provider.name} disconnected.`);
      onSaved();
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'Could not disconnect.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[#141414]/50 p-4"
      onClick={onClose}
    >
      <div
        className="max-h-[90vh] w-full max-w-md overflow-y-auto border border-[#141414] bg-[#E4E3E0] p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="font-mono text-sm font-bold uppercase">{provider.name}</h3>
        <p className="mb-4 text-xs text-[#141414]/55">{provider.region}</p>

        <div className="space-y-3">
          {provider.fields.map((f) => (
            <Fragment key={f.key}>
            <Field label={f.label + (f.required ? '' : ' (optional)')}>
              <div className="relative">
                {f.secret && (
                  <Lock className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#141414]/35" />
                )}
                <input
                  className={`${inputCls} ${f.secret ? 'pl-8' : ''}`}
                  type={f.secret ? 'password' : 'text'}
                  autoComplete={f.secret ? 'new-password' : 'off'}
                  value={values[f.key] ?? ''}
                  onChange={(e) => setValues((v) => ({ ...v, [f.key]: e.target.value }))}
                  placeholder={f.secret && f.set ? 'Saved — type to replace it' : f.placeholder}
                />
              </div>
              {f.secret && (
                <p className="text-[10px] leading-relaxed text-[#141414]/45">
                  {f.set
                    ? 'Stored encrypted. We cannot show it back — leave blank to keep it.'
                    : 'Stored encrypted, and never shown again once saved.'}
                </p>
              )}
            </Field>
            </Fragment>
          ))}
        </div>

        <div className="mt-5 flex flex-wrap items-center justify-between gap-2">
          <div className="flex gap-2">
            <Btn onClick={() => save(false)} variant="outline" disabled={busy}>
              Save
            </Btn>
            {!provider.active && (
              <Btn onClick={() => save(true)} disabled={busy}>
                {busy ? 'Saving…' : 'Save & use'}
              </Btn>
            )}
          </div>
          {provider.configured && (
            <Btn onClick={disconnect} variant="danger" disabled={busy}>
              Disconnect
            </Btn>
          )}
        </div>
      </div>
    </div>
  );
}

/** The managed gateway is prepaid. This is the balance, and the way to top it up. */
function CreditsCard({ credits, onBought }: { credits: CreditSummary; onBought: () => void }) {
  const [buying, setBuying] = useState<string | null>(null);
  const [mfaFor, setMfaFor] = useState<string | null>(null);
  const [code, setCode] = useState('');

  const buy = async (bundleId: string, mfaCode: string) => {
    setBuying(bundleId);
    try {
      await api.messaging.buyCredits(bundleId, mfaCode);
      toast('success', 'Credits added.');
      setMfaFor(null);
      setCode('');
      onBought();
    } catch (e) {
      const err = e as ApiError;
      const body = err.body as { mfa_required?: boolean } | null;
      if (body?.mfa_required) {
        // Not a failure — a demand. Show the code box rather than a red error.
        setMfaFor(bundleId);
      } else {
        toast('error', err instanceof ApiError ? err.message : 'Could not buy credits.');
      }
    } finally {
      setBuying(null);
    }
  };

  return (
    <Panel title="SMS credits">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="font-mono text-3xl font-black tabular-nums">
            {credits.balance.toLocaleString()}
          </p>
          <p className="text-xs text-[#141414]/55">
            SMS left on the WIFI.OS gateway · wallet KSh{' '}
            {Number(credits.wallet_balance).toLocaleString()}
          </p>
        </div>
        {credits.low && (
          <p className="flex items-center gap-1.5 border border-[#B22222]/40 bg-[#B22222]/5 px-2 py-1 text-xs text-[#B22222]">
            <AlertTriangle className="h-3.5 w-3.5" />
            Running low — top up before receipts start failing.
          </p>
        )}
      </div>

      <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
        {credits.bundles.map((b) => (
          <div key={b.id} className="border border-[#141414]/20 bg-white p-3">
            <p className="font-mono text-lg font-black tabular-nums">
              {b.credits.toLocaleString()}
            </p>
            <p className="text-[11px] text-[#141414]/50">
              KSh {Number(b.price).toLocaleString()} · {b.per_sms}/SMS
            </p>
            {mfaFor === b.id ? (
              <div className="mt-2 space-y-1.5">
                <input
                  className={inputCls}
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  placeholder="6-digit code"
                  inputMode="numeric"
                  autoFocus
                />
                <div className="flex gap-1.5">
                  <Btn onClick={() => buy(b.id, code)} disabled={buying === b.id || !code}>
                    {buying === b.id ? '…' : 'Confirm'}
                  </Btn>
                  <Btn onClick={() => setMfaFor(null)} variant="outline">
                    Cancel
                  </Btn>
                </div>
              </div>
            ) : (
              <div className="mt-2">
                <Btn onClick={() => buy(b.id, '')} variant="outline" disabled={buying === b.id}>
                  <Zap className="h-3.5 w-3.5" /> Buy
                </Btn>
              </div>
            )}
          </div>
        ))}
      </div>
      <p className="mt-3 text-[11px] leading-relaxed text-[#141414]/45">
        Credits are paid for from your wallet, and buying them asks for your authenticator
        code — the same lock as a withdrawal, because it is your money moving.
      </p>
    </Panel>
  );
}
