import { useEffect, useState, type FormEvent } from 'react';
import { Settings, Save, ShieldCheck, Loader2 } from 'lucide-react';
import { api, OperatorSettings } from '../api/client';
import { Btn, Field, inputCls, Panel, toast, ViewHeader, Badge } from './ui';

export default function SettingsView({ onCredentialsSaved }: { onCredentialsSaved?: () => void }) {
  const [settings, setSettings] = useState<OperatorSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [validating, setValidating] = useState(false);
  const [biz, setBiz] = useState({ name: '', owner_name: '', contact_phone: '', contact_email: '' });
  const [mpesa, setMpesa] = useState({
    mpesa_shortcode: '',
    daraja_consumer_key: '',
    daraja_consumer_secret: '',
    mpesa_passkey: '',
  });

  useEffect(() => {
    api.operatorSettings.get().then((s) => {
      setSettings(s);
      setBiz({
        name: s.name,
        owner_name: s.owner_name,
        contact_phone: s.contact_phone,
        contact_email: s.contact_email,
      });
      setMpesa((m) => ({ ...m, mpesa_shortcode: s.mpesa_shortcode }));
    }).catch(() => toast('error', 'Could not load settings.'));
  }, []);

  const saveBiz = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      setSettings(await api.operatorSettings.update(biz));
      toast('success', 'Business details saved.');
    } catch {
      toast('error', 'Failed to save.');
    } finally {
      setBusy(false);
    }
  };

  const saveMpesa = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      const payload: Record<string, string> = { mpesa_shortcode: mpesa.mpesa_shortcode };
      if (mpesa.daraja_consumer_key) payload.daraja_consumer_key = mpesa.daraja_consumer_key;
      if (mpesa.daraja_consumer_secret) payload.daraja_consumer_secret = mpesa.daraja_consumer_secret;
      if (mpesa.mpesa_passkey) payload.mpesa_passkey = mpesa.mpesa_passkey;
      const s = await api.operatorSettings.update(payload);
      setSettings(s);
      setMpesa({ ...mpesa, daraja_consumer_key: '', daraja_consumer_secret: '', mpesa_passkey: '' });
      toast('success', 'M-Pesa credentials saved (encrypted). Now validate them.');
      onCredentialsSaved?.();
    } catch {
      toast('error', 'Failed to save credentials.');
    } finally {
      setBusy(false);
    }
  };

  const validate = async () => {
    setValidating(true);
    try {
      const r = await api.operatorSettings.validateMpesa();
      if (r.ok) toast('success', r.detail);
      else toast('error', r.detail);
    } catch (e) {
      toast('error', e instanceof Error ? e.message : 'Validation failed.');
    } finally {
      setValidating(false);
    }
  };

  if (!settings) {
    return (
      <div className="flex justify-center py-24">
        <Loader2 className="h-8 w-8 animate-spin text-[#141414]/40" />
      </div>
    );
  }

  return (
    <div className="space-y-5 text-[#141414]">
      <ViewHeader
        icon={<Settings className="h-4.5 w-4.5" />}
        title="Business Settings"
        subtitle={`Console address: ${settings.slug}.wifios.co.ke`}
      >
        <Badge color={settings.has_mpesa_credentials ? 'green' : 'amber'}>
          {settings.has_mpesa_credentials ? 'M-Pesa configured' : 'M-Pesa not configured'}
        </Badge>
      </ViewHeader>

      <Panel title="Business details">
        <form onSubmit={saveBiz} className="grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
          <Field label="Business name">
            <input required value={biz.name} onChange={(e) => setBiz({ ...biz, name: e.target.value })} className={inputCls} />
          </Field>
          <Field label="Owner">
            <input value={biz.owner_name} onChange={(e) => setBiz({ ...biz, owner_name: e.target.value })} className={inputCls} />
          </Field>
          <Field label="Contact phone">
            <input value={biz.contact_phone} onChange={(e) => setBiz({ ...biz, contact_phone: e.target.value })} className={inputCls} />
          </Field>
          <Field label="Contact email">
            <input type="email" value={biz.contact_email} onChange={(e) => setBiz({ ...biz, contact_email: e.target.value })} className={inputCls} />
          </Field>
          <Btn type="submit" disabled={busy}><Save className="h-3.5 w-3.5" /> Save</Btn>
        </form>
      </Panel>

      <Panel title="M-Pesa / Daraja — where your money goes">
        <p className="text-xs font-mono text-[#141414]/60 mb-4 leading-relaxed">
          Customer payments go straight to YOUR paybill. Get these values from
          developer.safaricom.co.ke (app credentials) and your Go-Live approval
          (passkey). Secrets are stored encrypted and never shown again.
        </p>
        <form onSubmit={saveMpesa} className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <Field label="Paybill / shortcode">
            <input required value={mpesa.mpesa_shortcode} onChange={(e) => setMpesa({ ...mpesa, mpesa_shortcode: e.target.value })} className={inputCls} placeholder="e.g. 4123456" />
          </Field>
          <Field label="Lipa Na M-Pesa passkey">
            <input type="password" value={mpesa.mpesa_passkey} onChange={(e) => setMpesa({ ...mpesa, mpesa_passkey: e.target.value })} className={inputCls} placeholder={settings.has_mpesa_credentials ? '•••••• (saved)' : ''} />
          </Field>
          <Field label="Daraja consumer key">
            <input type="password" value={mpesa.daraja_consumer_key} onChange={(e) => setMpesa({ ...mpesa, daraja_consumer_key: e.target.value })} className={inputCls} placeholder={settings.has_mpesa_credentials ? '•••••• (saved)' : ''} />
          </Field>
          <Field label="Daraja consumer secret">
            <input type="password" value={mpesa.daraja_consumer_secret} onChange={(e) => setMpesa({ ...mpesa, daraja_consumer_secret: e.target.value })} className={inputCls} placeholder={settings.has_mpesa_credentials ? '•••••• (saved)' : ''} />
          </Field>
          <div className="flex gap-2 md:col-span-2">
            <Btn type="submit" variant="green" disabled={busy}>
              <Save className="h-3.5 w-3.5" /> Save credentials
            </Btn>
            <Btn variant="outline" onClick={validate} disabled={validating || !settings.has_mpesa_credentials}>
              <ShieldCheck className="h-3.5 w-3.5" />
              {validating ? 'Checking with Safaricom…' : 'Validate live'}
            </Btn>
          </div>
        </form>
      </Panel>
    </div>
  );
}
