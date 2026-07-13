import { Settings } from 'lucide-react';
import { ViewHeader } from './ui';
import BrandingPanel from './settings/BrandingPanel';
import CommsPanel from './settings/CommsPanel';
import DomainPanel from './settings/DomainPanel';
import EmailPanel from './settings/EmailPanel';
import ProfilePanel from './settings/ProfilePanel';
import Placeholder from './settings/Placeholder';
import SettlementSetup from './SettlementSetup';

/**
 * The settings SHELL. One frame, an inner sidebar of every setting an ISP has, and a
 * panel per item. We ship the whole sidebar at once and build the panels step by step —
 * so the structure is stable and a not-yet-built section says so honestly instead of
 * hiding.
 */

type ItemId =
  | 'branding' | 'domain'
  | 'pppoe' | 'hotspot'
  | 'payments' | 'sms' | 'email' | 'whatsapp' | 'templates' | 'loyalty'
  | 'alerts'
  | 'ai' | 'developer'
  | 'profile' | 'security';

interface Item {
  id: ItemId;
  label: string;
  sub: string;
  /** A dimmed sub-heading above this item (e.g. "Communications"). */
  under?: string;
}
interface Group {
  title: string;
  items: Item[];
}

const NAV: Group[] = [
  {
    title: 'General',
    items: [
      { id: 'branding', label: 'Branding', sub: 'Identity, logo, colours' },
      { id: 'domain', label: 'Domain', sub: 'Your subdomain & routers' },
    ],
  },
  {
    title: 'Network',
    items: [
      { id: 'pppoe', label: 'PPPoE', sub: 'Fixed-line subscribers, FUP, reminders' },
      { id: 'hotspot', label: 'Hotspot', sub: 'Captive portal, vouchers, instructions' },
    ],
  },
  {
    title: 'Billing & messaging',
    items: [
      { id: 'payments', label: 'Payments', sub: 'Payout account & credentials' },
      { id: 'sms', label: 'SMS', sub: 'Providers & credits', under: 'Communications' },
      { id: 'email', label: 'Email', sub: 'SMTP gateway' },
      { id: 'whatsapp', label: 'WhatsApp', sub: 'WhatsApp providers' },
      { id: 'templates', label: 'Message templates', sub: 'Receipts, expiry & reminders' },
      { id: 'loyalty', label: 'Loyalty points', sub: 'Reward subscribers for payments' },
    ],
  },
  {
    title: 'Notifications',
    items: [{ id: 'alerts', label: 'Operator alerts', sub: 'Router status & sales digests' }],
  },
  {
    title: 'Integrations',
    items: [
      { id: 'ai', label: 'AI Assistant', sub: 'Provider & API key' },
      { id: 'developer', label: 'Developer', sub: 'API tokens & webhooks' },
    ],
  },
  {
    title: 'Account',
    items: [
      { id: 'profile', label: 'Profile', sub: 'Your name & contact' },
      { id: 'security', label: 'Password & 2FA', sub: 'Sign-in security' },
    ],
  },
];

const ITEM_IDS = new Set(NAV.flatMap((g) => g.items).map((i) => i.id));

export default function SettingsView({
  onOpenWallet,
  section,
  onSectionChange,
}: {
  onOpenWallet: () => void;
  /** Which panel is open, from the URL (#/settings/branding) — so a refresh keeps you
   *  on the section you were editing, and you can link somebody straight to it. */
  section?: string;
  onSectionChange: (id: string) => void;
}) {
  const active: ItemId = ITEM_IDS.has(section as ItemId) ? (section as ItemId) : 'branding';
  const setActive = (id: ItemId) => onSectionChange(id);
  const current = NAV.flatMap((g) => g.items).find((i) => i.id === active)!;

  return (
    <div className="space-y-5 text-[#141414]">
      <ViewHeader icon={<Settings className="h-4.5 w-4.5" />} title="Settings" subtitle="Personalise and configure your ISP." />

      <div className="grid gap-5 lg:grid-cols-[220px_1fr]">
        {/* Inner sidebar — scrolls on its own (it's long), so the panel beside it stays
            put instead of the whole page having to travel to reach the last item. */}
        <nav className="self-start lg:sticky lg:top-4 lg:max-h-[calc(100vh-6rem)] lg:overflow-y-auto lg:pr-1">
          {/* Mobile: a select. Desktop: the full list. */}
          <select
            value={active}
            onChange={(e) => setActive(e.target.value as ItemId)}
            className="mb-4 w-full border border-[#141414] bg-white p-2.5 font-mono text-xs lg:hidden"
          >
            {NAV.map((g) => (
              <optgroup key={g.title} label={g.title}>
                {g.items.map((i) => (
                  <option key={i.id} value={i.id}>{i.label}</option>
                ))}
              </optgroup>
            ))}
          </select>

          <div className="hidden lg:block">
            {NAV.map((g) => (
              <div key={g.title} className="mb-4">
                <p className="px-2 pb-1.5 font-mono text-[10px] font-bold uppercase tracking-widest text-[#141414]/40">
                  {g.title}
                </p>
                {g.items.map((i) => (
                  <div key={i.id}>
                    {i.under && (
                      <p className="px-2 pt-2 pb-1 font-mono text-[9px] uppercase tracking-widest text-[#141414]/30">
                        {i.under}
                      </p>
                    )}
                    <button
                      onClick={() => setActive(i.id)}
                      className={`w-full border-l-2 px-2.5 py-1.5 text-left transition ${
                        active === i.id
                          ? 'border-[#228B22] bg-[#141414] text-[#E4E3E0]'
                          : 'border-transparent hover:bg-[#f0efec]'
                      }`}
                    >
                      <span className="block font-mono text-[12px] font-bold">{i.label}</span>
                      <span className={`block text-[10px] ${active === i.id ? 'text-[#E4E3E0]/60' : 'text-[#141414]/50'}`}>
                        {i.sub}
                      </span>
                    </button>
                  </div>
                ))}
              </div>
            ))}
          </div>
        </nav>

        {/* Panel */}
        <div className="min-w-0">
          <div className="mb-4 border-b border-[#141414]/15 pb-3">
            <h2 className="font-mono text-sm font-bold uppercase">{current.label}</h2>
            <p className="text-xs text-[#141414]/50">{current.sub}</p>
          </div>

          {active === 'branding' && <BrandingPanel />}
          {active === 'payments' && (
            <div className="border border-[#141414] bg-white p-5">
              <SettlementSetup onWentLive={() => {}} />
            </div>
          )}
          {active === 'profile' && <ProfilePanel onOpenWallet={onOpenWallet} />}

          {active === 'domain' && <DomainPanel />}
          {active === 'pppoe' && (
            <Placeholder title="PPPoE" blurb="Fair-use policy, suspension rules and payment reminders for fixed-line subscribers." />
          )}
          {active === 'hotspot' && (
            <Placeholder title="Hotspot" blurb="Captive-portal instructions, voucher defaults and hotspot behaviour." />
          )}
          {active === 'sms' && <CommsPanel channel="sms" />}
          {active === 'email' && <EmailPanel />}
          {active === 'whatsapp' && <CommsPanel channel="whatsapp" />}
          {active === 'templates' && (
            <Placeholder title="Message templates" blurb="Customise the wording of receipts, expiry warnings and reminders." />
          )}
          {active === 'loyalty' && (
            <Placeholder title="Loyalty points" blurb="Reward subscribers for paying — points they can redeem against WiFi." />
          )}
          {active === 'alerts' && (
            <Placeholder title="Operator alerts" blurb="Get told when a router goes down, and a daily sales digest." />
          )}
          {active === 'ai' && (
            <Placeholder title="AI Assistant" blurb="Plug in an AI provider and API key to help you run support and analytics." />
          )}
          {active === 'developer' && (
            <Placeholder title="Developer" blurb="API tokens and webhooks to integrate WIFI.OS with your own tools." />
          )}
          {active === 'security' && (
            <Placeholder title="Password & 2FA" blurb="Change your password and manage the authenticator that protects your money. (2FA already guards withdrawals today.)" />
          )}
        </div>
      </div>
    </div>
  );
}
