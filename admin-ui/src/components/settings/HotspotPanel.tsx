import { Fragment, ReactNode, useEffect, useRef, useState } from 'react';
import { Check, Loader2, Maximize2, X, ImagePlus, Trash2 } from 'lucide-react';
import { api, Branding, HotspotSettings } from '../../api/client';
import { Btn, Field, inputCls, Panel, toast } from '../ui';
import { BrandLike, DEFAULT_TEMPLATE, PORTAL_TEMPLATES } from '../../portal/templates';
import PortalPreview from './PortalPreview';
import PhoneFrame from './PhoneFrame';

/**
 * Settings > Hotspot — the captive-portal look and the subscriber lifecycle.
 *
 * The portal look (template, background, language, redirect) lives on Branding; the console
 * shows every template as a LIVE preview of the ISP's own brand, so picking one is picking
 * what a customer will actually see. The lifecycle controls (clock start, prune, prefix,
 * voucher expiry) drive real backbone tasks in core.HotspotSettings.
 */
export default function HotspotPanel() {
  const [brand, setBrand] = useState<Branding | null>(null);
  const [s, setS] = useState<HotspotSettings | null>(null);
  const [busy, setBusy] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null); // template id in full-screen
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api.branding.get().then(setBrand).catch(() => toast('error', 'Could not load your branding.'));
    api.hotspotSettings.get().then(setS).catch(() => toast('error', 'Could not load hotspot settings.'));
  }, []);

  if (!brand || !s) {
    return (
      <div className="flex items-center gap-2 p-6 text-sm text-[#141414]/50">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading…
      </div>
    );
  }

  const setBrandField = (patch: Partial<Branding>) =>
    setBrand((prev) => (prev ? { ...prev, ...patch } : prev));
  const setSetting = (patch: Partial<HotspotSettings>) =>
    setS((prev) => (prev ? { ...prev, ...patch } : prev));

  const previewBrand: BrandLike = {
    accent_color: brand.accent_color,
    background_image: brand.background_image,
  };

  const uploadBackground = async (file: File) => {
    setUploading(true);
    try {
      const { background_image } = await api.branding.uploadBackground(file);
      setBrandField({ background_image });
      toast('success', 'Background updated.');
    } catch {
      toast('error', 'That image could not be used. Try a PNG/JPG/WebP under 5 MB.');
    } finally {
      setUploading(false);
    }
  };

  const clearBackground = async () => {
    try {
      await api.branding.deleteBackground();
      setBrandField({ background_image: '' });
    } catch {
      toast('error', 'Could not remove the background.');
    }
  };

  const save = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const [savedBrand, savedSettings] = await Promise.all([
        api.branding.update({
          portal_template: brand.portal_template,
          portal_language: brand.portal_language,
          post_purchase_redirect: brand.post_purchase_redirect,
        }),
        api.hotspotSettings.update({
          timer_start_mode: s.timer_start_mode,
          inactive_prune_days: s.inactive_prune_days,
          username_prefix: s.username_prefix,
          voucher_expiry_days: s.voucher_expiry_days,
        }),
      ]);
      setBrand(savedBrand);
      setS(savedSettings);
      toast('success', 'Hotspot settings saved.');
    } catch (e) {
      const msg = e && typeof e === 'object' && 'body' in e ? String((e as { body?: { detail?: string } }).body?.detail || '') : '';
      toast('error', msg || 'Could not save. Check the values and try again.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6 max-w-5xl">
      <div>
        <h2 className="text-lg font-bold font-mono uppercase tracking-wide">Captive hotspot</h2>
        <p className="text-sm text-[#141414]/60 mt-1">
          Captive-portal subscribers and prepaid vouchers — portal look, account lifecycle,
          and the payment steps shown to buyers.
        </p>
      </div>

      {/* ---- Portal look ------------------------------------------------------------ */}
      <Panel title="Captive portal">
        <p className="text-xs text-[#141414]/60 -mt-1 mb-4">How the hotspot login page looks and behaves.</p>

        <Field label="Portal template">
          <p className="text-xs text-[#141414]/50 mb-3 font-sans normal-case font-normal">
            Pick a look. It previews your own brand — tap the expand icon to see it full-screen.
          </p>
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
            {PORTAL_TEMPLATES.map((t) => {
              const selected = brand.portal_template === t.id;
              return (
                <div
                  key={t.id}
                  onClick={() => setBrandField({ portal_template: t.id })}
                  className={`group relative cursor-pointer border bg-[#f4f4f2] transition ${
                    selected ? 'border-[#228B22] ring-2 ring-[#228B22]' : 'border-[#141414]/20 hover:border-[#141414]/50'
                  }`}
                >
                  {/* thumbnail: the real preview, scaled down */}
                  <div style={{ height: 190, overflow: 'hidden', position: 'relative' }}>
                    <div style={{ width: 300, height: 432, transform: 'scale(0.435)', transformOrigin: 'top left' }}>
                      <PortalPreview templateId={t.id} brand={previewBrand} name={brand.name_for_customers} logo={brand.logo} />
                    </div>
                  </div>
                  {/* expand */}
                  <button
                    onClick={(e) => { e.stopPropagation(); setExpanded(t.id); }}
                    className="absolute top-1.5 right-1.5 p-1 bg-white/85 border border-[#141414]/20 opacity-0 group-hover:opacity-100 transition hover:bg-white"
                    title="Preview full-screen"
                  >
                    <Maximize2 className="h-3.5 w-3.5" />
                  </button>
                  {selected && (
                    <div className="absolute top-1.5 left-1.5 p-0.5 bg-[#228B22] text-white rounded-full">
                      <Check className="h-3 w-3" />
                    </div>
                  )}
                  <div className="flex items-center justify-between px-2 py-1.5 border-t border-[#141414]/10 bg-white">
                    <span className="text-xs font-bold">{t.label}</span>
                    {t.id === DEFAULT_TEMPLATE && (
                      <span className="text-[10px] font-mono uppercase text-[#141414]/40">Default</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </Field>

        {/* background */}
        <div className="mt-6">
          <Field label="Background image">
            <p className="text-xs text-[#141414]/50 mb-2 font-sans normal-case font-normal">
              Shown behind the login card on themes that support it (Aurora, Lagoon, Lumen, Sunrise…).
              PNG, JPG or WebP up to 5 MB.
            </p>
            <div className="flex items-center gap-3">
              {brand.background_image ? (
                <div className="relative">
                  <img src={brand.background_image} alt="" className="h-20 w-32 object-cover border border-[#141414]/20" />
                  <button
                    onClick={clearBackground}
                    className="absolute -top-2 -right-2 p-1 bg-white border border-[#B22222]/50 text-[#B22222] hover:bg-[#B22222] hover:text-white"
                    title="Remove background"
                  >
                    <Trash2 className="h-3 w-3" />
                  </button>
                </div>
              ) : (
                <div className="h-20 w-32 border border-dashed border-[#141414]/30 flex items-center justify-center text-[#141414]/30 text-xs">
                  None
                </div>
              )}
              <div>
                <input
                  ref={fileRef}
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) uploadBackground(f);
                    e.target.value = '';
                  }}
                />
                <Btn variant="outline" onClick={() => fileRef.current?.click()} disabled={uploading}>
                  {uploading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <ImagePlus className="h-3.5 w-3.5" />}
                  {brand.background_image ? 'Replace' : 'Upload'}
                </Btn>
              </div>
            </div>
          </Field>
        </div>

        {/* language + redirect */}
        <div className="grid sm:grid-cols-2 gap-4 mt-6">
          <Field label="Portal language">
            <select
              className={inputCls}
              value={brand.portal_language}
              onChange={(e) => setBrandField({ portal_language: e.target.value })}
            >
              <option value="en">English</option>
            </select>
          </Field>
          <Field label="Post-purchase redirect">
            <input
              className={inputCls}
              placeholder="https://your-site.co.ke  (optional)"
              value={brand.post_purchase_redirect}
              onChange={(e) => setBrandField({ post_purchase_redirect: e.target.value })}
            />
            <p className="text-[11px] text-[#141414]/45 mt-1">Where to send subscribers after a successful purchase. Blank keeps them on the success screen.</p>
          </Field>
        </div>
      </Panel>

      {/* ---- Lifecycle -------------------------------------------------------------- */}
      <Panel title="Lifecycle">
        <p className="text-xs text-[#141414]/60 -mt-1 mb-4">How hotspot accounts are created and cleaned up over time.</p>

        <Field label="Subscription timer starts">
          <div className="grid sm:grid-cols-2 gap-3">
            {s.choices.timer_start_modes.map((m) => {
              const on = s.timer_start_mode === m.value;
              return (
                <button
                  key={m.value}
                  onClick={() => setSetting({ timer_start_mode: m.value as HotspotSettings['timer_start_mode'] })}
                  className={`text-left p-3 border transition ${on ? 'border-[#228B22] ring-1 ring-[#228B22] bg-[#228B22]/5' : 'border-[#141414]/25 hover:border-[#141414]/50'}`}
                >
                  <div className="text-xs font-bold">{m.label}</div>
                  <div className="text-[11px] text-[#141414]/55 mt-0.5">
                    {m.value === 'on_purchase'
                      ? 'The clock starts right after payment or voucher redemption.'
                      : 'Time begins when the subscriber first connects to Wi-Fi.'}
                  </div>
                </button>
              );
            })}
          </div>
        </Field>

        <div className="mt-5">
          <Field label="Inactive prune">
            <p className="text-xs text-[#141414]/50 mb-2 font-sans normal-case font-normal">
              Auto-delete accounts unseen for this many days. Never keeps them indefinitely.
            </p>
            <div className="flex flex-wrap gap-1.5">
              <Chip on={s.inactive_prune_days === null} onClick={() => setSetting({ inactive_prune_days: null })}>Never</Chip>
              {s.choices.prune_days.map((d) => (
                <Fragment key={d}>
                  <Chip on={s.inactive_prune_days === d} onClick={() => setSetting({ inactive_prune_days: d })}>
                    {d} days
                  </Chip>
                </Fragment>
              ))}
            </div>
          </Field>
        </div>

        <div className="mt-5 max-w-xs">
          <Field label="Username prefix">
            <input
              className={inputCls}
              maxLength={8}
              placeholder="e.g. sm"
              value={s.username_prefix}
              onChange={(e) => setSetting({ username_prefix: e.target.value.replace(/[^A-Za-z0-9]/g, '') })}
            />
            <p className="text-[11px] text-[#141414]/45 mt-1">Up to 8 characters; prepended to auto-generated voucher logins.</p>
          </Field>
        </div>
      </Panel>

      {/* ---- Voucher defaults ------------------------------------------------------- */}
      <Panel title="Voucher defaults">
        <p className="text-xs text-[#141414]/60 -mt-1 mb-4">Defaults applied to prepaid vouchers sold through the portal.</p>
        <div className="max-w-xs">
          <Field label="Unused voucher expiry">
            <div className="flex items-center gap-2">
              <input
                type="number"
                min={0}
                className={`${inputCls} w-24`}
                value={s.voucher_expiry_days}
                onChange={(e) => setSetting({ voucher_expiry_days: Math.max(0, parseInt(e.target.value || '0', 10)) })}
              />
              <span className="text-xs text-[#141414]/55">days &nbsp;(0 = never)</span>
            </div>
            <p className="text-[11px] text-[#141414]/45 mt-1">Days before an unused voucher is auto-invalidated.</p>
          </Field>
        </div>
      </Panel>

      <div className="flex justify-end">
        <Btn variant="green" onClick={save} disabled={busy}>
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
          Save changes
        </Btn>
      </div>

      {/* ---- Full-screen preview modal --------------------------------------------- */}
      {expanded && (
        <div
          className="fixed inset-0 z-50 bg-[#141414]/70 flex items-center justify-center p-4"
          onClick={() => setExpanded(null)}
        >
          <div className="flex flex-col items-center gap-3" onClick={(e) => e.stopPropagation()}>
            <PhoneFrame>
              <PortalPreview templateId={expanded} brand={previewBrand} name={brand.name_for_customers} logo={brand.logo} />
            </PhoneFrame>
            <div className="flex items-center gap-2">
              <Btn
                variant="green"
                onClick={() => { setBrandField({ portal_template: expanded }); setExpanded(null); }}
              >
                <Check className="h-3.5 w-3.5" /> Use {PORTAL_TEMPLATES.find((t) => t.id === expanded)?.label}
              </Btn>
              <Btn variant="outline" onClick={() => setExpanded(null)}>
                <X className="h-3.5 w-3.5" /> Close
              </Btn>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={`px-2.5 py-1 text-xs font-bold border transition ${
        on ? 'bg-[#141414] text-white border-[#141414]' : 'bg-white text-[#141414]/70 border-[#141414]/25 hover:border-[#141414]/60'
      }`}
    >
      {children}
    </button>
  );
}
