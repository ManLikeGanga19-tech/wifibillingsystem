import { useCallback, useEffect, useState } from 'react';
import {
  Activity,
  Building2,
  Gauge,
  LogOut,
  Search as SearchIcon,
  ShieldCheck,
  TrendingUp,
} from 'lucide-react';
import { api, logout, type Me } from './api/client';
import { Spinner, ToastHost } from './components/ui';
import LoginView from './components/LoginView';
import CommandCenter from './views/CommandCenter';
import FinanceView from './views/FinanceView';
import GovernanceView from './views/GovernanceView';
import OpsView from './views/OpsView';
import SearchView from './views/SearchView';
import TenantsView from './views/TenantsView';

type Tab = 'command' | 'finance' | 'tenants' | 'ops' | 'governance' | 'search';

const NAV: { id: Tab; label: string; icon: typeof Gauge }[] = [
  { id: 'command', label: 'Command', icon: Gauge },
  { id: 'finance', label: 'Finance', icon: TrendingUp },
  { id: 'tenants', label: 'ISPs', icon: Building2 },
  { id: 'ops', label: 'Ops', icon: Activity },
  { id: 'governance', label: 'Governance', icon: ShieldCheck },
  { id: 'search', label: 'Search', icon: SearchIcon },
];

export default function App() {
  // "Am I signed in?" is a question only the SERVER can answer now — the session
  // lives in an httpOnly cookie we cannot read. So we ask it, rather than probing
  // localStorage (which is exactly the stale state we no longer keep).
  const [me, setMe] = useState<Me | null>(null);
  const [checking, setChecking] = useState(true);
  const [tab, setTab] = useState<Tab>('command');
  const [openTenant, setOpenTenant] = useState<number | null>(null);

  const loadMe = useCallback(async () => {
    setChecking(true);
    try {
      setMe(await api.me());
    } catch {
      setMe(null); // not signed in (or the session expired) -> the login gate
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
  };

  if (checking) return <Spinner />;

  if (!me) {
    return (
      <>
        <LoginView onLoggedIn={loadMe} />
        <ToastHost />
      </>
    );
  }

  return (
    <div className="min-h-screen flex flex-col">
      {/* ---- top bar ---- */}
      <header
        className="sticky top-0 z-30 border-b backdrop-blur"
        style={{ borderColor: 'var(--hairline)', background: 'rgba(7,10,15,0.85)' }}
      >
        <div className="max-w-[1600px] mx-auto px-4 sm:px-6 h-14 flex items-center gap-6">
          <div className="flex items-center gap-2.5 shrink-0">
            <div
              className="h-7 w-7 rounded-lg flex items-center justify-center"
              style={{ background: 'var(--accent-dim)' }}
            >
              <ShieldCheck className="h-4 w-4" style={{ color: 'var(--accent)' }} />
            </div>
            <div className="leading-tight hidden sm:block">
              <p className="text-sm font-semibold tracking-tight">WIFI.OS</p>
              <p
                className="text-[9px] uppercase tracking-[0.18em]"
                style={{ color: 'var(--accent)' }}
              >
                Platform Control
              </p>
            </div>
          </div>

          <nav className="flex items-center gap-1 overflow-x-auto flex-1">
            {NAV.map((n) => {
              const Icon = n.icon;
              const active = tab === n.id;
              return (
                <button
                  key={n.id}
                  onClick={() => go(n.id)}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs whitespace-nowrap transition cursor-pointer"
                  style={
                    active
                      ? { background: 'var(--accent-dim)', color: 'var(--accent)' }
                      : { color: 'var(--text-secondary)' }
                  }
                >
                  <Icon className="h-3.5 w-3.5" />
                  {n.label}
                </button>
              );
            })}
          </nav>

          <div className="flex items-center gap-3 shrink-0">
            <div className="text-right hidden sm:block leading-tight">
              <p className="text-xs font-medium">{me.name}</p>
              <p className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
                {me.is_read_only ? 'read-only' : me.role.replace('_', ' ')}
              </p>
            </div>
            <button
              onClick={signOut}
              title="Sign out"
              className="p-1.5 rounded-md cursor-pointer transition hover:text-white"
              style={{ color: 'var(--text-muted)' }}
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </div>
      </header>

      {/* ---- body ---- */}
      <main className="flex-1 max-w-[1600px] w-full mx-auto p-4 sm:p-6">
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
      </main>

      <footer
        className="border-t py-3 px-6 text-[10px]"
        style={{ borderColor: 'var(--hairline)', color: 'var(--text-muted)' }}
      >
        Danamo Tech · every action on this console is recorded in the audit trail.
      </footer>

      <ToastHost />
    </div>
  );
}
