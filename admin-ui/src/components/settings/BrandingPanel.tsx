import { useEffect, useRef, useState } from 'react';
import { Image as ImageIcon, Loader2, Trash2, Upload, Wifi } from 'lucide-react';
import { api, ApiError, Branding } from '../../api/client';
import { Btn, Field, inputCls, Panel, toast } from '../ui';

/**
 * Branding — the first thing that makes WIFI.OS feel like the ISP's own product. Edit on
 * the left, see it on the customer's phone on the right, live. Everything a WiFi customer
 * sees (the captive portal, and later receipts and SMS) wears this.
 */
export default function BrandingPanel() {
  const [b, setB] = useState<Branding | null>(null);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.branding.get().then(setB).catch(() => toast('error', 'Could not load branding.'));
  }, []);

  const set = (patch: Partial<Branding>) => setB((prev) => (prev ? { ...prev, ...patch } : prev));

  const save = async () => {
    if (!b || busy) return;
    setBusy(true);
    try {
      const saved = await api.branding.update({
        display_name: b.display_name,
        tagline: b.tagline,
        primary_color: b.primary_color,
        accent_color: b.accent_color,
        support_phone: b.support_phone,
        support_email: b.support_email,
      });
      setB(saved);
      toast('success', 'Branding saved — your customers will see it.');
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'Could not save.');
    } finally {
      setBusy(false);
    }
  };

  const upload = async (file: File) => {
    setUploading(true);
    try {
      const { logo } = await api.branding.uploadLogo(file);
      set({ logo });
      toast('success', 'Logo updated.');
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'Could not upload that logo.');
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = '';
    }
  };

  const removeLogo = async () => {
    try {
      await api.branding.deleteLogo();
      set({ logo: '' });
    } catch {
      toast('error', 'Could not remove the logo.');
    }
  };

  if (!b) {
    return (
      <div className="flex justify-center py-16">
        <Loader2 className="h-6 w-6 animate-spin text-[#141414]/40" />
      </div>
    );
  }

  const shownName = b.display_name || b.name_for_customers;

  return (
    <div className="grid gap-5 lg:grid-cols-[1fr_320px]">
      {/* Editor */}
      <div className="space-y-5">
        <Panel title="Logo">
          <div className="flex items-center gap-4">
            <div className="grid h-16 w-16 shrink-0 place-items-center border border-[#141414] bg-white">
              {b.logo ? (
                <img src={b.logo} alt="Logo" className="max-h-full max-w-full object-contain" />
              ) : (
                <ImageIcon className="h-6 w-6 text-[#141414]/30" />
              )}
            </div>
            <div className="flex flex-wrap gap-2">
              <input
                ref={fileRef}
                type="file"
                accept="image/png,image/jpeg,image/webp"
                className="hidden"
                onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])}
              />
              <Btn variant="outline" onClick={() => fileRef.current?.click()} disabled={uploading}>
                {uploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
                {b.logo ? 'Replace' : 'Upload logo'}
              </Btn>
              {b.logo && (
                <Btn variant="outline" onClick={removeLogo}>
                  <Trash2 className="h-3.5 w-3.5" /> Remove
                </Btn>
              )}
            </div>
          </div>
          <p className="mt-3 text-[11px] font-mono text-[#141414]/50">
            PNG, JPG or WebP. It's resized and cleaned on our side — square logos look best.
          </p>
        </Panel>

        <Panel title="Identity">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Name shown to customers">
              <input
                value={b.display_name}
                onChange={(e) => set({ display_name: e.target.value })}
                placeholder={b.name_for_customers}
                className={inputCls}
              />
            </Field>
            <Field label="Tagline">
              <input
                value={b.tagline}
                onChange={(e) => set({ tagline: e.target.value })}
                placeholder="Fast WiFi. Fair prices."
                className={inputCls}
              />
            </Field>
          </div>
        </Panel>

        <Panel title="Colours">
          <div className="flex flex-wrap gap-6">
            <ColorField label="Primary" value={b.primary_color} onChange={(v) => set({ primary_color: v })} />
            <ColorField label="Accent (buttons, prices)" value={b.accent_color} onChange={(v) => set({ accent_color: v })} />
          </div>
        </Panel>

        <Panel title="Customer support">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Support phone">
              <input
                value={b.support_phone}
                onChange={(e) => set({ support_phone: e.target.value })}
                placeholder="07XX XXX XXX"
                className={inputCls}
              />
            </Field>
            <Field label="Support email">
              <input
                type="email"
                value={b.support_email}
                onChange={(e) => set({ support_email: e.target.value })}
                placeholder="help@yourisp.co.ke"
                className={inputCls}
              />
            </Field>
          </div>
          <p className="mt-2 text-[11px] font-mono text-[#141414]/50">
            Shown to a customer on the captive portal when they need help.
          </p>
        </Panel>

        <Btn variant="green" onClick={save} disabled={busy}>
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : null}
          Save branding
        </Btn>
      </div>

      {/* Live preview — a mini captive portal on a phone */}
      <div className="lg:sticky lg:top-4 self-start">
        <p className="mb-2 text-[10px] font-bold font-mono uppercase tracking-widest text-[#141414]/50">
          Your customer sees
        </p>
        <div className="mx-auto w-full max-w-[280px] rounded-[2rem] border-[6px] border-[#141414] bg-[#141414] p-1.5">
          <div className="overflow-hidden rounded-[1.5rem] bg-[#E4E3E0] p-4">
            <div className="flex items-center gap-2.5">
              <div
                className="grid h-9 w-9 shrink-0 place-items-center"
                style={{ background: b.logo ? 'transparent' : b.primary_color }}
              >
                {b.logo ? (
                  <img src={b.logo} alt="" className="max-h-9 max-w-9 object-contain" />
                ) : (
                  <Wifi className="h-5 w-5 text-white" />
                )}
              </div>
              <div className="min-w-0">
                <p className="truncate text-sm font-bold" style={{ color: b.primary_color }}>
                  {shownName}
                </p>
                <p className="truncate text-[10px] text-[#141414]/60">{b.tagline || 'Buy WiFi with M-Pesa'}</p>
              </div>
            </div>

            <div className="mt-4 space-y-2">
              {[
                ['1 Hour Express', 'KSh 20'],
                ['Daily Unlimited', 'KSh 100'],
              ].map(([name, price]) => (
                <div key={name} className="flex items-center justify-between border border-[#141414] bg-white p-2.5">
                  <span className="text-xs font-bold">{name}</span>
                  <span className="text-sm font-black" style={{ color: b.accent_color }}>
                    {price}
                  </span>
                </div>
              ))}
              <button
                className="mt-1 w-full py-2.5 text-center text-xs font-bold uppercase text-white"
                style={{ background: b.accent_color }}
              >
                Pay with M-Pesa
              </button>
            </div>

            {(b.support_phone || b.support_email) && (
              <p className="mt-3 text-center text-[9px] text-[#141414]/50">
                Need help? {b.support_phone || b.support_email}
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function ColorField({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label className="block">
      <span className="text-[10px] font-bold font-mono uppercase text-[#141414]/60">{label}</span>
      <div className="mt-1 flex items-center gap-2">
        <input
          type="color"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="h-9 w-12 cursor-pointer border border-[#141414] bg-white p-0.5"
        />
        <input
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className={`${inputCls} w-28`}
        />
      </div>
    </label>
  );
}
