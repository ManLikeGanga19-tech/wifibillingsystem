import { useCallback, useEffect, useState } from 'react';
import {
  Activity,
  Building2,
  Gauge,
  Globe,
  Loader2,
  Search as SearchIcon,
  ShieldAlert,
  ShieldCheck,
  TrendingUp,
} from 'lucide-react';
import { api, logout, type Me } from './api/client';
import { useHashRoute } from './utils/useHashRoute';
import { ToastHost } from './components/ui';
import LoginView from './components/LoginView';
import CommandCenter from './views/CommandCenter';
import FinanceView from './views/FinanceView';
import GovernanceView from './views/GovernanceView';
import OpsView from './views/OpsView';
import SearchView from './views/SearchView';
import TenantsView from './views/TenantsView';

type Tab = 'command' | 'finance' | 'tenants' | 'ops' | 'governance' | 'search';

/** The sections the URL may name; anything else falls back to the Command Center. */
const KNOWN_TABS: ReadonlySet<Tab> = new Set<Tab>([
  'command', 'finance', 'tenants', 'ops', 'governance', 'search',
]);

const ISP_CONSOLE_URL = 'http://localhost:4600';

const NAV: { title: string | null; items: { id: Tab; label: string; icon: typeof Gauge }[] }[] = [
  { title: null, items: [{ id: 'command', label: 'Dashboard', icon: Gauge }] },
  {
    title: 'Danamo Tech',
    items: [
      { id: 'finance', label: 'Finance', icon: TrendingUp },
      { id: 'tenants', label: 'ISP Tenants', icon: Building2 },
    ],
  },
  {
    title: 'Operations',
    items: [
      { id: 'ops', label: 'System Health', icon: Activity },
      { id: 'search', label: 'Search', icon: SearchIcon },
    ],
  },
  {
    title: 'Governance',
    items: [{ id: 'governance', label: 'Audit & Access', icon: ShieldCheck }],
  },
];

export default function App() {
  // The session lives in an httpOnly cookie we cannot read, so "am I signed in?"
  // is a question only the SERVER can answer. We ask it — nothing is stored here.
  const [me, setMe] = useState<Me | null>(null);
  const [checking, setChecking] = useState(true);

  // The page you're on lives in the URL, so a refresh keeps you here instead of
  // bouncing you back to the Command Center.
  const { route, navigate } = useHashRoute('command');
  const tab: Tab = KNOWN_TABS.has(route.section as Tab) ? (route.section as Tab) : 'command';
  const setTab = useCallback((next: Tab) => navigate(next), [navigate]);
  const [openTenant, setOpenTenant] = useState<number | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const loadMe = useCallback(async () => {
    setChecking(true);
    try {
      setMe(await api.me());
    } catch {
      setMe(null); // not signed in (or expired) -> the login gate
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    loadMe();
  }, [loadMe]);

  const signOut = async () => {
    await logout(); // the server clears the cookies; nothing to clear here
    setMe(null);
  };

  const go = (t: string) => {
    setOpenTenant(null);
    setTab(t as Tab);
    setSidebarOpen(false);
  };

  if (checking) {
    return (
      <div className="min-h-screen bg-[#E4E3E0] flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-[#141414]/40" />
      </div>
    );
  }

  if (!me) {
    return (
      <>
        <LoginView onLoggedIn={loadMe} />
        <ToastHost />
      </>
    );
  }

  // Signed in, but NOT Danamo platform staff (e.g. an ISP-owner session — cookies are
  // shared across localhost ports, so a login on the ISP console lands here too). Without
  // this gate the platform shell rendered and every /platform/ call 403'd ("Could not load
  // this data"). Tell them plainly instead of showing a broken dashboard.
  if (!me.is_platform_staff) {
    return (
      <>
        <NotPlatformView me={me} onSignOut={signOut} />
        <ToastHost />
      </>
    );
  }

  return (
    <div className="flex h-screen w-full bg-[#E4E3E0] text-[#141414] font-sans text-sm overflow-hidden">
      {/* ---- Sidebar (same shape as the ISP console) ---- */}
      <aside
        className={`fixed md:relative inset-y-0 left-0 z-40 w-60 border-r border-[#141414] bg-[#E4E3E0] flex flex-col h-full shrink-0 transform transition-transform duration-200 md:translate-x-0 ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="p-4 h-14 border-b border-[#141414] flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-3.5 h-3.5 bg-[#141414] rotate-45 shrink-0" />
            <div className="leading-none">
              <span className="font-bold tracking-tighter text-lg uppercase font-mono">
                WIFI.OS
              </span>
              <p className="text-[9px] font-mono uppercase tracking-wider text-[#141414]/50 mt-0.5">
                Platform Control
              </p>
            </div>
          </div>
          <button
            onClick={() => setSidebarOpen(false)}
            className="md:hidden p-1 border border-[#141414] text-[10px] font-mono cursor-pointer"
          >
            [X]
          </button>
        </div>

        <nav className="flex-1 py-2 font-mono overflow-y-auto">
          {NAV.map((group, gi) => (
            <div key={group.title ?? gi}>
              {group.title && (
                <div className="px-4 pt-3 pb-1 opacity-50 text-[10px] uppercase italic tracking-wider">
                  {group.title}
                </div>
              )}
              {group.items.map((item) => {
                const Icon = item.icon;
                const active = tab === item.id;
                return (
                  <button
                    key={item.id}
                    onClick={() => go(item.id)}
                    className={`w-full py-2.5 px-4 flex items-center gap-2 text-xs transition cursor-pointer ${
                      active
                        ? 'bg-[#141414] text-[#E4E3E0] font-bold'
                        : 'hover:bg-white/60 text-[#141414]'
                    }`}
                  >
                    <Icon className="h-4 w-4 shrink-0" />
                    <span className="font-bold tracking-tight truncate">
                      {item.label.toUpperCase()}
                    </span>
                  </button>
                );
              })}
            </div>
          ))}
        </nav>

        <div className="p-4 border-t border-[#141414] font-mono text-[10px] uppercase">
          <p className="opacity-50">Danamo Tech</p>
          <p className="font-bold">Platform v1.0</p>
        </div>
      </aside>

      {sidebarOpen && (
        <div
          onClick={() => setSidebarOpen(false)}
          className="fixed inset-0 z-30 bg-[#141414]/40 md:hidden"
        />
      )}

      {/* ---- Main ---- */}
      <main className="flex-1 flex flex-col min-w-0 bg-[#f0efec] h-full overflow-hidden">
        <header className="h-14 border-b border-[#141414] flex items-center justify-between px-4 sm:px-6 bg-white shrink-0">
          <div className="flex items-center gap-3 md:gap-8">
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="md:hidden p-1.5 border border-[#141414] cursor-pointer"
            >
              <Gauge className="h-4 w-4" />
            </button>
            <div className="flex flex-col">
              <span className="text-[10px] opacity-60 font-bold uppercase tracking-wider font-serif italic">
                Scope
              </span>
              <span className="flex items-center gap-1.5 font-mono font-bold text-[10px] sm:text-xs">
                <span className="w-2 h-2 rounded-full bg-[#228B22] pulse-active" />
                ALL ISPs — PLATFORM VIEW
              </span>
            </div>
          </div>

          <div className="flex items-center gap-3 sm:gap-4 font-mono text-[10px] sm:text-xs">
            <a
              href={ISP_CONSOLE_URL}
              target="_blank"
              rel="noreferrer"
              title="Open your own ISP console"
              className="hidden sm:flex items-center gap-1.5 border border-[#141414] bg-[#E4E3E0] px-2 py-1.5 font-bold uppercase cursor-pointer hover:bg-[#141414] hover:text-white transition"
            >
              <Globe className="h-3.5 w-3.5" /> My ISP
            </a>
            <div className="border-l border-[#141414] pl-3 sm:pl-4 text-right">
              <div className="text-[11px] opacity-50 uppercase truncate max-w-[10rem]">
                {me.name}
                {me.is_read_only && ' · read-only'}
              </div>
              <button
                onClick={signOut}
                title="Sign out"
                className="font-bold uppercase tracking-tight hover:text-[#B22222] transition cursor-pointer"
              >
                Sign out
              </button>
            </div>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8 min-h-0">
          <div className="max-w-7xl mx-auto space-y-6">
            {tab === 'command' && <CommandCenter onNavigate={go} />}
            {tab === 'finance' && (
              <FinanceView
                onOpenTenant={(id) => {
                  setTab('tenants');
                  setOpenTenant(id);
                }}
              />
            )}
            {tab === 'tenants' && <TenantsView openId={openTenant} onOpen={setOpenTenant} />}
            {tab === 'ops' && <OpsView />}
            {tab === 'governance' && <GovernanceView />}
            {tab === 'search' && <SearchView />}
          </div>
        </div>

        <footer className="h-8 border-t border-[#141414] bg-white flex items-center px-4 sm:px-6 font-mono text-[10px] text-[#141414]/70 shrink-0 select-none">
          <p className="truncate">
            Danamo Tech · every action on this console is recorded in the audit trail
          </p>
        </footer>
      </main>

      <ToastHost />
    </div>
  );
}

/**
 * The signed-in-but-not-platform-staff screen. Platform Control is Danamo-only; an ISP
 * account that lands here (usually a session shared from the ISP console on another
 * localhost port) gets told plainly and offered a clean re-login — instead of a dashboard
 * that 403s on every panel.
 */
function NotPlatformView({ me, onSignOut }: { me: Me; onSignOut: () => void }) {
  return (
    <div className="min-h-screen bg-[#E4E3E0] flex items-center justify-center p-4">
      <div className="bg-white border border-[#141414] max-w-md w-full p-8 text-center">
        <ShieldAlert className="h-8 w-8 mx-auto text-[#B26B00]" />
        <h1 className="font-bold text-lg mt-3">Not a platform account</h1>
        <p className="text-sm text-[#141414]/70 mt-2 leading-relaxed">
          You&apos;re signed in as <b>{me.name || me.phone}</b>
          {me.operator ? ` (${me.operator.name})` : ''} — an ISP account, not Danamo platform
          staff. Platform Control is for Danamo Tech only.
        </p>
        <p className="text-xs text-[#141414]/50 mt-2">
          If you run an ISP, use your own console instead.
        </p>
        <button
          onClick={onSignOut}
          className="mt-5 w-full bg-[#141414] text-[#E4E3E0] font-bold py-3 uppercase text-xs font-mono hover:bg-[#B26B00] transition"
        >
          Sign in with a platform account
        </button>
      </div>
    </div>
  );
}
