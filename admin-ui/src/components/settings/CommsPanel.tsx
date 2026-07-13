import { useEffect, useState } from 'react';
import { CheckCircle2, Loader2, Lock, Send } from 'lucide-react';
import { api, ApiError, MessagingSettings, MessagingSettingsUpdate } from '../../api/client';
import { Btn, Field, inputCls, Panel, toast } from '../ui';

/**
 * Communications — which gateway an ISP's messages leave on.
 *
 * One component serves SMS, email and WhatsApp because they are the same decision three
 * times: use ours, or bring your own. The default (ours) means messaging works on day
 * one with nothing to configure; the ISP switches to their own when they want their own
 * sender name, their own rate, or their own domain's deliverability.
 *
 * Credentials are one-way. The server never sends a saved key back — it only says one
 * exists — so a key box that is empty means "unchanged", never "deleted". That is why
 * the fields below show a lock and a placeholder rather than dots pretending to be a
 * value we do not have.
 */

type ChannelId = 'sms' | 'email' | 'whatsapp';

export default function CommsPanel({ channel }: { channel: ChannelId }) {
  const [s, setS] = useState<MessagingSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testTo, setTestTo] = useState('');
  // Secrets are held only for as long as it takes to submit them.
  const [secret, setSecret] = useState('');

  useEffect(() => {
    api.messaging.get().then(setS).catch(() => toast('error', 'Could not load your gateways.'));
  }, []);

  useEffect(() => {
    setSecret(''); // never carry a typed key across a channel switch
  }, [channel]);

  const set = (patch: Partial<MessagingSettings>) =>
    setS((prev) => (prev ? { ...prev, ...patch } : prev));

  if (!s) {
    return (
      <div className="flex items-center gap-2 p-6 text-sm text-[#141414]/50">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading…
      </div>
    );
  }

  const mode = channel === 'sms' ? s.sms_mode : channel === 'email' ? s.email_mode : s.whatsapp_mode;
  const own = mode === 'own';

  const save = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const patch: MessagingSettingsUpdate = {};
      if (channel === 'sms') {
        patch.sms_mode = s.sms_mode;
        patch.sms_username = s.sms_username;
        patch.sms_sender_id = s.sms_sender_id;
        if (secret) patch.sms_api_key = secret;
      } else if (channel === 'email') {
        patch.email_mode = s.email_mode;
        patch.smtp_host = s.smtp_host;
        patch.smtp_port = s.smtp_port;
        patch.smtp_username = s.smtp_username;
        patch.smtp_use_tls = s.smtp_use_tls;
        patch.from_email = s.from_email;
        patch.from_name = s.from_name;
        if (secret) patch.smtp_password = secret;
      } else {
        patch.whatsapp_mode = s.whatsapp_mode;
        patch.whatsapp_phone_number_id = s.whatsapp_phone_number_id;
        if (secret) patch.whatsapp_token = secret;
      }
      const saved = await api.messaging.update(patch);
      setS(saved);
      setSecret('');
      toast('success', 'Gateway saved.');
    } catch (e) {
      toast('error', fieldError(e) ?? 'Could not save.');
    } finally {
      setBusy(false);
    }
  };

  const sendTest = async () => {
    if (!testTo.trim() || testing) return;
    setTesting(true);
    try {
      const { detail } = await api.messaging.test(channel, testTo.trim());
      toast('success', detail);
    } catch (e) {
      // The provider's own words. "Sender ID not approved" is the whole value here —
      // a generic "failed" would send them hunting.
      toast('error', e instanceof ApiError ? e.message : 'The test message did not go out.');
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="space-y-5">
      <ModeChooser channel={channel} mode={mode} onChange={set} />

      {own && (
        <Panel title="Your credentials">
          <div className="grid gap-4 sm:grid-cols-2">
            {channel === 'sms' && (
              <>
                <Field label="Africa's Talking username">
                  <input
                    className={inputCls}
                    value={s.sms_username}
                    onChange={(e) => set({ sms_username: e.target.value })}
                    placeholder="your-at-username"
                  />
                </Field>
                <Field label="Sender ID">
                  <input
                    className={inputCls}
                    value={s.sms_sender_id}
                    onChange={(e) => set({ sms_sender_id: e.target.value })}
                    placeholder="ACMEWIFI"
                    maxLength={11}
                  />
                </Field>
                <SecretField
                  label="API key"
                  configured={s.sms_api_key_configured}
                  value={secret}
                  onChange={setSecret}
                  className="sm:col-span-2"
                />
              </>
            )}

            {channel === 'email' && (
              <>
                <Field label="SMTP host">
                  <input
                    className={inputCls}
                    value={s.smtp_host}
                    onChange={(e) => set({ smtp_host: e.target.value })}
                    placeholder="mail.yourisp.co.ke"
                  />
                </Field>
                <Field label="Port">
                  <input
                    className={inputCls}
                    type="number"
                    value={s.smtp_port}
                    onChange={(e) => set({ smtp_port: Number(e.target.value) })}
                  />
                </Field>
                <Field label="SMTP username">
                  <input
                    className={inputCls}
                    value={s.smtp_username}
                    onChange={(e) => set({ smtp_username: e.target.value })}
                  />
                </Field>
                <SecretField
                  label="SMTP password"
                  configured={s.smtp_password_configured}
                  value={secret}
                  onChange={setSecret}
                />
                <Field label="From address">
                  <input
                    className={inputCls}
                    value={s.from_email}
                    onChange={(e) => set({ from_email: e.target.value })}
                    placeholder="billing@yourisp.co.ke"
                  />
                </Field>
                <Field label="From name">
                  <input
                    className={inputCls}
                    value={s.from_name}
                    onChange={(e) => set({ from_name: e.target.value })}
                    placeholder="Acme WiFi"
                  />
                </Field>
                <label className="flex items-center gap-2 text-sm sm:col-span-2">
                  <input
                    type="checkbox"
                    checked={s.smtp_use_tls}
                    onChange={(e) => set({ smtp_use_tls: e.target.checked })}
                  />
                  Use TLS (leave on unless your provider says otherwise)
                </label>
              </>
            )}

            {channel === 'whatsapp' && (
              <>
                <Field label="Phone number ID">
                  <input
                    className={inputCls}
                    value={s.whatsapp_phone_number_id}
                    onChange={(e) => set({ whatsapp_phone_number_id: e.target.value })}
                    placeholder="From your Meta Business account"
                  />
                </Field>
                <SecretField
                  label="Access token"
                  configured={s.whatsapp_token_configured}
                  value={secret}
                  onChange={setSecret}
                />
                <p className="text-xs leading-relaxed text-[#141414]/50 sm:col-span-2">
                  Meta only allows free-text messages within 24 hours of a customer
                  writing to you. Outside that window you must use a template they have
                  approved — so keep SMS as your fallback for reminders.
                </p>
              </>
            )}
          </div>
        </Panel>
      )}

      <div className="flex justify-end">
        <Btn onClick={save} disabled={busy}>
          {busy ? 'Saving…' : 'Save gateway'}
        </Btn>
      </div>

      <Panel title="Prove it works">
        <p className="mb-3 text-xs leading-relaxed text-[#141414]/60">
          Send yourself a real message. A wrong key or an unapproved sender ID fails
          quietly in production — you would only find out when a customer says they never
          got their code. Find out now instead.
        </p>
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            className={`${inputCls} flex-1`}
            value={testTo}
            onChange={(e) => setTestTo(e.target.value)}
            placeholder={channel === 'email' ? 'you@yourisp.co.ke' : '2547XXXXXXXX'}
          />
          <Btn onClick={sendTest} variant="outline" disabled={testing || !testTo.trim()}>
            {testing ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Send className="h-4 w-4" />
            )}
            {testing ? 'Sending…' : 'Send test'}
          </Btn>
        </div>
      </Panel>
    </div>
  );
}

/** The one real decision on this page. */
function ModeChooser({
  channel,
  mode,
  onChange,
}: {
  channel: ChannelId;
  mode: string;
  onChange: (patch: Partial<MessagingSettings>) => void;
}) {
  const isWhatsApp = channel === 'whatsapp';
  const defaultId = isWhatsApp ? 'off' : 'platform';
  const key = channel === 'sms' ? 'sms_mode' : channel === 'email' ? 'email_mode' : 'whatsapp_mode';

  const options: { id: string; title: string; blurb: string }[] = [
    isWhatsApp
      ? {
          id: 'off',
          title: 'Off',
          blurb: 'We hold no WhatsApp account on your behalf, so this channel stays quiet until you connect one.',
        }
      : {
          id: 'platform',
          title: 'Use WIFI.OS (recommended)',
          blurb:
            channel === 'sms'
              ? 'Nothing to set up — your messages go out on our SMS account and are billed with your plan.'
              : 'Nothing to set up — receipts and reminders go out on our mail server.',
        },
    {
      id: 'own',
      title: 'Use my own gateway',
      blurb:
        channel === 'sms'
          ? 'Your Africa’s Talking account, your sender ID, your SMS rate.'
          : channel === 'email'
            ? 'Your SMTP server and your From: address, so mail arrives from a name your customers know.'
            : 'Your WhatsApp Business account.',
    },
  ];

  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {options.map((o) => {
        const active = mode === o.id;
        return (
          <button
            key={o.id}
            onClick={() => onChange({ [key]: o.id } as Partial<MessagingSettings>)}
            className={`border p-4 text-left transition ${
              active
                ? 'border-[#141414] bg-[#141414] text-[#E4E3E0]'
                : 'border-[#141414]/25 bg-white hover:border-[#141414]'
            }`}
          >
            <div className="flex items-center gap-2">
              {active && <CheckCircle2 className="h-4 w-4 shrink-0" />}
              <span className="font-mono text-sm font-bold">{o.title}</span>
            </div>
            <p
              className={`mt-1 text-xs leading-relaxed ${
                active ? 'text-[#E4E3E0]/70' : 'text-[#141414]/55'
              }`}
            >
              {o.blurb}
            </p>
            {o.id === defaultId && !active && (
              <p className="mt-1 font-mono text-[10px] uppercase tracking-wide text-[#141414]/35">
                Default
              </p>
            )}
          </button>
        );
      })}
    </div>
  );
}

/** A credential box. It never displays a stored value — because the server never sends
 *  one back. Blank means "keep what you have". */
function SecretField({
  label,
  configured,
  value,
  onChange,
  className = '',
}: {
  label: string;
  configured: boolean;
  value: string;
  onChange: (v: string) => void;
  className?: string;
}) {
  return (
    <Field label={label} className={className}>
      <div className="relative">
        <Lock className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#141414]/35" />
        <input
          className={`${inputCls} pl-8`}
          type="password"
          autoComplete="new-password"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={configured ? 'Saved — type to replace it' : 'Paste it here'}
        />
      </div>
      <p className="text-[10px] leading-relaxed text-[#141414]/45">
        {configured
          ? 'Stored encrypted. We cannot show it back to you — leave this blank to keep it.'
          : 'Stored encrypted, and never shown again once saved.'}
      </p>
    </Field>
  );
}

/** DRF hands back {field: ["message"]} on a validation error — show the message, not
 *  "[object Object]". */
function fieldError(e: unknown): string | null {
  if (!(e instanceof ApiError)) return null;
  const body = e.body as Record<string, unknown> | null;
  if (body && typeof body === 'object') {
    for (const value of Object.values(body)) {
      if (typeof value === 'string') return value;
      if (Array.isArray(value) && typeof value[0] === 'string') return value[0];
    }
  }
  return e.message;
}
