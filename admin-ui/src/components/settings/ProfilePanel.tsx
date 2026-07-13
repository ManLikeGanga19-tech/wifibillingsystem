import { useEffect, useState, type FormEvent } from 'react';
import { Loader2, Save, Wallet } from 'lucide-react';
import { api, OperatorSettings } from '../../api/client';
import { Btn, Field, inputCls, Panel, toast } from '../ui';

/** Account → Profile: the ISP's own name and contact details (their record, not the
 *  customer-facing brand — that's the Branding panel). */
export default function ProfilePanel({ onOpenWallet }: { onOpenWallet: () => void }) {
  const [settings, setSettings] = useState<OperatorSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [biz, setBiz] = useState({ name: '', owner_name: '', contact_phone: '', contact_email: '' });

  useEffect(() => {
    api.operatorSettings
      .get()
      .then((s) => {
        setSettings(s);
        setBiz({
          name: s.name,
          owner_name: s.owner_name,
          contact_phone: s.contact_phone,
          contact_email: s.contact_email,
        });
      })
      .catch(() => toast('error', 'Could not load your profile.'));
  }, []);

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      setSettings(await api.operatorSettings.update(biz));
      toast('success', 'Saved.');
    } catch {
      toast('error', 'Failed to save.');
    } finally {
      setBusy(false);
    }
  };

  if (!settings) {
    return (
      <div className="flex justify-center py-16">
        <Loader2 className="h-6 w-6 animate-spin text-[#141414]/40" />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <Panel title="Business details">
        <form onSubmit={save} className="grid grid-cols-1 gap-3 sm:grid-cols-2">
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
          <div className="sm:col-span-2">
            <Btn type="submit" variant="green" disabled={busy}>
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />} Save
            </Btn>
          </div>
        </form>
      </Panel>

      <Panel title="How you get paid">
        <p className="mb-3 text-xs font-mono leading-relaxed text-[#141414]/70">
          Customer payments are collected securely via <b>Danamo Tech Ltd</b> — you don't
          need your own paybill or any Safaricom paperwork. Every sale is credited to your
          wallet with the platform commission ({Number(settings.commission_rate)}%) already
          deducted, and you withdraw to M-Pesa whenever you like.
        </p>
        <Btn variant="outline" onClick={onOpenWallet}>
          <Wallet className="h-3.5 w-3.5" /> Open my wallet
        </Btn>
      </Panel>
    </div>
  );
}
