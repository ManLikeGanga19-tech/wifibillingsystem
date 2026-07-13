import { useEffect, useState } from 'react';
import { CheckCircle2, Loader2, Lock, Send } from 'lucide-react';
import { api, ApiError, EmailSettings, EmailSettingsUpdate } from '../../api/client';
import { Btn, Field, inputCls, Panel, toast } from '../ui';

/**
 * Email. Unlike SMS there is no market of gateways to choose between — just a server. So
 * this stays a straight choice: our mailer, or the ISP's own SMTP with their own From:
 * address (which is what puts receipts in an inbox under a name the customer recognises,
 * and puts deliverability on their domain's reputation rather than ours).
 */
export default function EmailPanel() {
  const [s, setS] = useState<EmailSettings | null>(null);
  const [secret, setSecret] = useState('');
  const [busy, setBusy] = useState(false);
  const [testTo, setTestTo] = useState('');
  const [testing, setTesting] = useState(false);

  useEffect(() => {
    api.messaging.email
      .get()
      .then(setS)
      .catch(() => toast('error', 'Could not load your email settings.'));
  }, []);

  if (!s) {
    return (
      <div className="flex items-center gap-2 p-6 text-sm text-[#141414]/50">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading…
      </div>
    );
  }

  const set = (patch: Partial<EmailSettings>) => setS((prev) => (prev ? { ...prev, ...patch } : prev));
  const own = s.email_mode === 'own';

  const save = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const patch: EmailSettingsUpdate = {
        email_mode: s.email_mode,
        smtp_host: s.smtp_host,
        smtp_port: s.smtp_port,
        smtp_username: s.smtp_username,
        smtp_use_tls: s.smtp_use_tls,
        from_email: s.from_email,
        from_name: s.from_name,
      };
      if (secret) patch.smtp_password = secret; // blank = keep the stored one
      setS(await api.messaging.email.update(patch));
      setSecret('');
      toast('success', 'Email settings saved.');
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'Could not save.');
    } finally {
      setBusy(false);
    }
  };

  const sendTest = async () => {
    if (!testTo.trim() || testing) return;
    setTesting(true);
    try {
      const { detail } = await api.messaging.test('email', testTo.trim());
      toast('success', detail);
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'The test email did not go out.');
    } finally {
      setTesting(false);
    }
  };

  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-2">
        {(
          [
            {
              id: 'platform',
              title: 'Use WIFI.OS (recommended)',
              blurb: 'Nothing to set up — receipts and reminders go out on our mail server.',
            },
            {
              id: 'own',
              title: 'Use my own SMTP',
              blurb:
                'Your server and your From: address, so mail arrives from a name your customers know.',
            },
          ] as const
        ).map((o) => {
          const active = s.email_mode === o.id;
          return (
            <button
              key={o.id}
              onClick={() => set({ email_mode: o.id })}
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
            </button>
          );
        })}
      </div>

      {own && (
        <Panel title="Your SMTP server">
          <div className="grid gap-4 sm:grid-cols-2">
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
            <Field label="Username">
              <input
                className={inputCls}
                value={s.smtp_username}
                onChange={(e) => set({ smtp_username: e.target.value })}
              />
            </Field>
            <Field label="Password">
              <div className="relative">
                <Lock className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[#141414]/35" />
                <input
                  className={`${inputCls} pl-8`}
                  type="password"
                  autoComplete="new-password"
                  value={secret}
                  onChange={(e) => setSecret(e.target.value)}
                  placeholder={
                    s.smtp_password_configured ? 'Saved — type to replace it' : 'Paste it here'
                  }
                />
              </div>
            </Field>
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
          </div>
        </Panel>
      )}

      <div className="flex justify-end">
        <Btn onClick={save} disabled={busy}>
          {busy ? 'Saving…' : 'Save email settings'}
        </Btn>
      </div>

      <Panel title="Prove it works">
        <p className="mb-3 text-xs leading-relaxed text-[#141414]/60">
          Send yourself a real email. A rejected SMTP password fails quietly in production —
          find out now, not when a customer says their receipt never arrived.
        </p>
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            className={`${inputCls} flex-1`}
            value={testTo}
            onChange={(e) => setTestTo(e.target.value)}
            placeholder="you@yourisp.co.ke"
          />
          <Btn onClick={sendTest} variant="outline" disabled={testing || !testTo.trim()}>
            {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
            {testing ? 'Sending…' : 'Send test'}
          </Btn>
        </div>
      </Panel>
    </div>
  );
}
