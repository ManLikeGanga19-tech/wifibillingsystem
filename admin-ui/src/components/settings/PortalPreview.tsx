import { CSSProperties } from 'react';
import { Wifi, Smartphone, Ticket } from 'lucide-react';
import { BrandLike, resolveTemplate, templateVars } from '../../portal/templates';

/**
 * A faithful mock of the captive-portal login, themed by a template's tokens and the ISP's
 * own brand — the exact surfaces the real portal themes (backdrop, header, card, accent),
 * so the picker shows what a subscriber will actually see. Not the live portal's logic;
 * its look.
 */
export default function PortalPreview({
  templateId,
  brand,
  name,
  logo,
}: {
  templateId: string;
  brand: BrandLike;
  name: string;
  logo?: string;
}) {
  const tpl = resolveTemplate(templateId);
  const vars = templateVars(tpl, brand) as CSSProperties;
  const tagline = 'Fast WiFi. Lipa na M-Pesa.';

  const card: CSSProperties = {
    background: 'var(--pt-card-bg)',
    border: 'var(--pt-card-border)',
    borderRadius: 'var(--pt-card-radius)',
    boxShadow: 'var(--pt-card-shadow)',
    backdropFilter: 'var(--pt-card-blur)',
    WebkitBackdropFilter: 'var(--pt-card-blur)',
    color: '#141414',
  };

  return (
    <div
      style={{ ...vars, background: 'var(--pt-bg)' }}
      className="min-h-full flex flex-col items-center px-4 pt-9 pb-6"
    >
      {/* header */}
      <div
        className="w-full flex items-center gap-2.5 mb-5"
        style={{ color: 'var(--pt-header-fg)' }}
      >
        <div
          className="h-8 w-8 flex items-center justify-center overflow-hidden rounded"
          style={{ background: logo ? 'transparent' : '#141414' }}
        >
          {logo ? (
            <img src={logo} alt="" className="max-h-8 max-w-8 object-contain" />
          ) : (
            <Wifi className="h-4 w-4 text-white" />
          )}
        </div>
        <div className="min-w-0">
          <div className="font-bold text-[15px] leading-none tracking-tight truncate">{name}</div>
          <div className="text-[11px] opacity-70 truncate">{tagline}</div>
        </div>
      </div>

      {/* card */}
      <div className="w-full p-4" style={card}>
        {/* tabs */}
        <div className="flex mb-4 text-[12px] font-bold">
          <div
            className="flex-1 flex items-center justify-center gap-1.5 py-2"
            style={{ background: 'var(--pt-accent)', color: 'var(--pt-accent-fg)' }}
          >
            <Smartphone className="h-3.5 w-3.5" /> M-Pesa
          </div>
          <div className="flex-1 flex items-center justify-center gap-1.5 py-2 border border-black/15 text-black/60">
            <Ticket className="h-3.5 w-3.5" /> Voucher
          </div>
        </div>

        {/* sample plans */}
        <div className="space-y-2">
          {[
            ['1 Hour', 'KES 20', '2 Mbps'],
            ['1 Day', 'KES 50', '5 Mbps'],
            ['1 Week', 'KES 250', '8 Mbps'],
          ].map(([n, price, speed]) => (
            <div
              key={n}
              className="flex items-center justify-between px-3 py-2.5 border border-black/10 rounded"
            >
              <div>
                <div className="text-[13px] font-bold text-black/85">{n}</div>
                <div className="text-[11px] text-black/45">{speed}</div>
              </div>
              <div className="text-[13px] font-bold text-black/85">{price}</div>
            </div>
          ))}
        </div>

        <button
          className="mt-4 w-full py-2.5 text-[13px] font-bold rounded"
          style={{ background: 'var(--pt-accent)', color: 'var(--pt-accent-fg)' }}
        >
          Buy with M-Pesa
        </button>
      </div>

      <div
        className="mt-5 text-[10px] opacity-60 text-center"
        style={{ color: 'var(--pt-header-fg)' }}
      >
        Need help? Call your provider.
      </div>
    </div>
  );
}
