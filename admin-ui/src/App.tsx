import React, { useCallback, useEffect, useState } from 'react';
import {
  Wifi,
  TrendingUp,
  BarChart3,
  Activity,
  Users,
  LifeBuoy,
  UserPlus,
  Gauge,
  Receipt,
  Ticket as TicketIcon,
  Wallet,
  MessageSquare,
  Mail,
  Megaphone,
  Router as RouterIcon,
  HardDrive,
  Settings as SettingsIcon,
  Loader2,
  Clock,
  Globe,
  Eye,
  Wifi as WifiIcon,
  RadioTower,
  Map as MapIcon,
  UsersRound,
  ShieldAlert,
} from 'lucide-react';

import { BandwidthProfile, Subscriber, OutboundCampaign } from './types';
import { api, ApiPlan, ApiTenant, demoLogin, keepSessionFresh, logout, Me, NavCounts, Role, Capability, can, ROLE_META, setOnSessionExpired, setOnConnectionChange } from './api/client';
import { planToProfile, profileToPlan, campaignToUi, subscriberToUi } from './api/mappers';
import { useHashRoute } from './utils/useHashRoute';
import { toast, ToastHost } from './components/ui';

import LoginView from './components/LoginView';
import GoLiveBanner from './components/GoLiveBanner';
import AssistantWidget from './components/AssistantWidget';
import BroadcastBanner from './components/BroadcastBanner';
import PastDueBanner from './components/PastDueBanner';
import LiveDashboard from './components/LiveDashboard';
import ActiveUsersView from './components/ActiveUsersView';
import UsersView from './components/UsersView';
import TicketsView from './components/TicketsView';
import LeadsView from './components/LeadsView';
import PlanConfigurator from './components/PlanConfigurator';
import TransactionsView from './components/TransactionsView';
import VouchersView from './components/VouchersView';
import ExpensesView from './components/ExpensesView';
import MessagesView from './components/MessagesView';
import EmailsView from './components/EmailsView';
import MessagingView from './components/MessagingView';
import RoutersView from './components/RoutersView';
import MapView from './components/MapView';
import EquipmentView from './components/EquipmentView';
import PppoePlansView from './components/PppoePlansView';
import PppoeClientsView from './components/PppoeClientsView';
import PppoeInvoicesView from './components/PppoeInvoicesView';
import NetworkView from './components/NetworkView';
import SettingsView from './components/SettingsView';
import WalletView from './components/WalletView';
import ReportsView from './components/ReportsView';
import StaffView from './components/StaffView';
import ForcedPasswordChange from './components/ForcedPasswordChange';

// ---- navigation model -------------------------------------------------------

type TabId =
  | 'dashboard'
  | 'active_users'
  | 'users'
  | 'tickets'
  | 'leads'
  | 'packages'
  | 'payments'
  | 'vouchers'
  | 'expenses'
  | 'messages'
  | 'emails'
  | 'campaigns'
  | 'mikrotik'
  | 'equipment'
  | 'settings'
  | 'wallet'
  | 'reports'
  | 'pppoe_clients'
  | 'pppoe_plans'
  | 'pppoe_invoices'
  | 'network'
  | 'map'
  | 'team';

/** Every section the URL is allowed to name. Anything else in the hash is somebody
 *  typing, or a stale link to a renamed page — fall back rather than render blank. */
const KNOWN_TABS: ReadonlySet<TabId> = new Set<TabId>([
  'dashboard', 'active_users', 'users', 'tickets', 'leads', 'packages', 'payments',
  'vouchers', 'expenses', 'messages', 'emails', 'campaigns', 'mikrotik', 'equipment',
  'settings', 'wallet', 'reports', 'pppoe_clients', 'pppoe_plans', 'pppoe_invoices',
  'network', 'map', 'team',
]);

/** RBAC (mirrors backend accounts/rbac.py): the capability a tab needs to appear + open. null =
 *  visible to every signed-in user. The server is authoritative; this only decides what to SHOW. */
const TAB_CAPABILITY: Record<TabId, Capability | null> = {
  dashboard: 'finance.view',
  map: 'map.view',
  active_users: 'clients.view',
  users: 'clients.view',
  tickets: 'tickets.view',
  leads: 'leads.view',
  pppoe_clients: 'clients.view',
  pppoe_plans: 'hotspot.plans',
  pppoe_invoices: 'finance.view',
  network: 'network.write',
  packages: 'hotspot.plans',
  payments: 'payments.view_amounts',
  reports: 'finance.view',
  vouchers: 'hotspot.vouchers',
  wallet: 'finance.view',
  expenses: 'finance.view',
  messages: 'messaging.send',
  emails: 'messaging.send',
  campaigns: 'messaging.send',
  mikrotik: 'router.access',
  equipment: 'network.write',
  settings: 'settings.write',
  team: 'staff.manage',
};

/** Where each role lands when the console opens — its primary workspace. Owner/Admin (and platform
 *  staff) default to the dashboard. */
const ROLE_HOME: Partial<Record<Role, TabId>> = {
  tenant_care: 'tickets',
  tenant_technician: 'map',
};

interface NavItem {
  id: TabId;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  badge?: keyof NavCounts;
}

const NAV_GROUPS: { title: string | null; items: NavItem[] }[] = [
  {
    title: null,
    items: [
      { id: 'dashboard', label: 'Dashboard', icon: TrendingUp },
      { id: 'map', label: 'Map', icon: MapIcon },
    ],
  },
  {
    title: 'Users',
    items: [
      { id: 'active_users', label: 'Active Users', icon: Activity, badge: 'active_users' },
      { id: 'users', label: 'Users', icon: Users, badge: 'users' },
      { id: 'tickets', label: 'Tickets', icon: LifeBuoy, badge: 'tickets' },
      { id: 'leads', label: 'Leads', icon: UserPlus, badge: 'leads' },
    ],
  },
  {
    title: 'Broadband (PPPoE)',
    items: [
      { id: 'pppoe_clients', label: 'Clients', icon: WifiIcon },
      { id: 'pppoe_plans', label: 'Broadband Plans', icon: Gauge },
      { id: 'pppoe_invoices', label: 'Invoices', icon: Receipt },
      { id: 'network', label: 'Network', icon: RadioTower },
    ],
  },
  {
    title: 'Finance',
    items: [
      { id: 'packages', label: 'Hotspot Plans', icon: Gauge, badge: 'packages' },
      { id: 'payments', label: 'Payments', icon: Receipt },
      { id: 'reports', label: 'Reports', icon: BarChart3 },
      { id: 'vouchers', label: 'Vouchers', icon: TicketIcon, badge: 'vouchers' },
      { id: 'wallet', label: 'Wallet', icon: Wallet },
      { id: 'expenses', label: 'Expenses', icon: Receipt },
    ],
  },
  {
    title: 'Communication',
    items: [
      { id: 'messages', label: 'Messages', icon: MessageSquare },
      { id: 'emails', label: 'Emails', icon: Mail },
      { id: 'campaigns', label: 'Campaigns', icon: Megaphone, badge: 'campaigns' },
    ],
  },
  {
    title: 'Devices',
    items: [
      { id: 'mikrotik', label: 'MikroTik', icon: RouterIcon, badge: 'mikrotik' },
      { id: 'equipment', label: 'Equipment', icon: HardDrive, badge: 'equipment' },
    ],
  },
  {
    title: 'Setup',
    items: [
      { id: 'team', label: 'Team', icon: UsersRound },
      { id: 'settings', label: 'Settings', icon: SettingsIcon },
    ],
  },
];

/** This app is now PURELY the ISP console. Everything cross-tenant (tenants,
 * payouts, reconciliation, audit, P&L) lives in the separate Platform Control
 * app — so an ISP never downloads platform code, and the two deploy apart. */
// Derived from the CURRENT domain so cross-console links work on ANY deployment —
// dev localhost ports, staging on :8443, production — never a hardcoded host that
// would 404 in the browser and make the system look broken.
function consoleOrigin(subdomain: string, devPort: string): string {
  const { protocol, hostname, port } = window.location;
  if (hostname === 'localhost' || hostname === '127.0.0.1') return `http://localhost:${devPort}`;
  const base = hostname.split('.').slice(1).join('.') || hostname;
  return `${protocol}//${subdomain}.${base}${port ? `:${port}` : ''}`;
}
const PLATFORM_CONSOLE_URL = consoleOrigin('admin', '4800');

/** Should a nav item show? Platform staff see everything (they bypass capabilities on the server
 *  too); a tenant role sees an item only if it holds the tab's capability. */
function navVisible(me: Me | null, cap: Capability | null): boolean {
  if (!me) return false;
  if (me.is_platform_staff) return true;
  return cap === null || can(me, cap);
}

export default function App() {
  // Session lives in an httpOnly cookie we cannot read, so "am I signed in?" is a
  // question only the server can answer. We ask it. Nothing is kept in the
  // browser, so nothing can go stale after a deploy.
  const [me, setMe] = useState<Me | null>(null);
  const [checking, setChecking] = useState(true);
  const [tenants, setTenants] = useState<ApiTenant[]>([]);

  // Which page you're on lives in the URL (#/payments, #/settings/branding), so a
  // refresh keeps you here and Back/Forward work. An unknown or hand-typed section
  // falls back to the dashboard rather than rendering nothing.
  const { route, navigate } = useHashRoute('dashboard');
  const activeTab: TabId = KNOWN_TABS.has(route.section as TabId)
    ? (route.section as TabId)
    : 'dashboard';
  const setActiveTab = useCallback((tab: TabId) => navigate(tab), [navigate]);
  const [isSidebarOpen, setIsSidebarOpen] = useState(false);
  // Ephemeral UI preference — deliberately NOT persisted (no browser storage).
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [navCounts, setNavCounts] = useState<NavCounts | null>(null);

  // Live server state shared across tabs
  const [apiPlans, setApiPlans] = useState<ApiPlan[]>([]);
  const [profiles, setProfiles] = useState<BandwidthProfile[]>([]);
  const [campaigns, setCampaigns] = useState<OutboundCampaign[]>([]);
  const [liveSubscribers, setLiveSubscribers] = useState<Subscriber[]>([]);

  // Land each role on a page it can actually use: if the current tab isn't permitted for this
  // role (a stale link, the default 'dashboard' for a technician…), send them to their home.
  useEffect(() => {
    if (!me || me.is_platform_staff) return;
    const cap = TAB_CAPABILITY[activeTab];
    if (cap && !can(me, cap)) setActiveTab(ROLE_HOME[me.role] ?? 'dashboard');
  }, [me, activeTab, setActiveTab]);

  const loadNavCounts = useCallback(() => {
    api.navCounts().then(setNavCounts).catch(() => {});
  }, []);

  const loadPlans = useCallback(() => {
    api.plans
      .list()
      .then((r) => {
        setApiPlans(r.results);
        setProfiles(r.results.map(planToProfile));
      })
      .catch(() => {});
  }, []);

  /** Ask the server who we are and which ISP we're acting for. Both live in
   * cookies the server owns, so this is always the truth — there is no local copy
   * that can disagree with it. */
  const loadMe = useCallback(async () => {
    const data = await api.me();
    setMe(data);
    if (data.is_platform_staff) {
      api.platform.tenants
        .list()
        .then((r) => setTenants(r.results))
        .catch(() => {});
    }
    return data;
  }, []);

  useEffect(() => {
    setChecking(true);
    loadMe()
      .catch(async () => {
        // No session. On a demo host the server hands out a read-only demo session, so a
        // first-time visitor lands straight in the showcase instead of a login wall. On any
        // normal host demoLogin() is refused and we fall through to the login gate.
        if (await demoLogin()) {
          await loadMe().catch(() => setMe(null));
        } else {
          setMe(null);
        }
      })
      .finally(() => setChecking(false));
  }, [loadMe]);

  // Keep the session renewed on tab-focus + a heartbeat, so returning after
  // inactivity never lands on an expired token and forces a re-login.
  useEffect(() => keepSessionFresh(), []);

  // When a session dies mid-use and can't be renewed, return to the sign-in screen
  // CENTRALLY — instead of every data call showing "could not load — is the API running?",
  // which wrongly blames the backend. Only nudge if we were actually signed in (so a plain
  // "not signed in" on first load stays silent and just shows the login gate).
  useEffect(() => {
    setOnSessionExpired(() =>
      setMe((prev) => {
        if (prev) toast('info', 'Your session ended — please sign in again.');
        return null;
      })
    );
    return () => setOnSessionExpired(null);
  }, []);

  // A brief API blip (a deploy, an overload) shows a subtle "Reconnecting…" chip instead of
  // a scary "API is down". The client layer retries and auto-recovers; this is just the hint.
  const [reconnecting, setReconnecting] = useState(false);
  useEffect(() => {
    setOnConnectionChange((s) => setReconnecting(s === 'reconnecting'));
    return () => setOnConnectionChange(null);
  }, []);

  /** Leave an ISP we were granted access to. The server ends the grant AND clears
   * the acting-tenant cookie, so we simply re-ask who we are. */
  const exitImpersonation = useCallback(async () => {
    try {
      await api.endImpersonation();
    } catch {
      /* already expired — the cookie is moot either way */
    }
    await loadMe();
    setActiveTab('dashboard');
    loadPlans();
    loadNavCounts();
    toast('info', 'Back in your own console.');
  }, [loadMe, loadPlans, loadNavCounts]);

  // ISP data only loads when we are actually acting for a tenant. Without one the
  // API refuses (by design) — so don't ask.
  const hasTenant = !!me?.acting_operator;

  useEffect(() => {
    if (!hasTenant) return;
    loadPlans();
    loadNavCounts();
    api.campaigns.list().then((r) => setCampaigns(r.results.map(campaignToUi).reverse())).catch(() => {});
    api.subscribers.list().then((r) => setLiveSubscribers(r.results.map(subscriberToUi))).catch(() => {});
    const t = window.setInterval(loadNavCounts, 30_000);
    return () => window.clearInterval(t);
  }, [hasTenant, loadPlans, loadNavCounts]);

  // Refresh badges when switching tabs — cheap, and keeps counts honest after actions
  useEffect(() => {
    if (hasTenant) loadNavCounts();
  }, [activeTab, hasTenant, loadNavCounts]);

  // Adapter for legacy components that expect an activity-log callback
  const addLog = (_cat: string, type: 'info' | 'success' | 'warning' | 'error', message: string) =>
    toast(type, message);

  // ---- plans CRUD (PlanConfigurator keeps its original design) --------------
  const handleAddProfile = async (newProf: Omit<BandwidthProfile, 'id'>) => {
    try {
      await api.plans.create(profileToPlan(newProf));
      loadPlans();
      toast('success', `Plan '${newProf.name}' saved.`);
    } catch {
      toast('error', 'Failed to save plan — check the API connection.');
    }
  };

  const handleUpdateProfile = async (updatedProf: BandwidthProfile) => {
    try {
      await api.plans.update(Number(updatedProf.id), profileToPlan(updatedProf));
      loadPlans();
    } catch {
      toast('error', 'Failed to update plan.');
    }
  };

  const handleDeleteProfile = async (id: string) => {
    try {
      await api.plans.remove(Number(id));
      loadPlans();
    } catch {
      toast('error', 'Could not delete — plans with payment history should be deactivated instead.');
    }
  };

  // Campaigns are self-contained in MessagingView (its own fetch/create + live progress).

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
        <LoginView onLoggedIn={() => loadMe().catch(() => {})} />
        <ToastHost />
      </>
    );
  }

  // SUSPENDED is a locked door. (PENDING is not: a freshly signed-up ISP gets their
  // console immediately and can build everything — they just cannot take a shilling
  // yet. That is the money gate, explained by GoLiveBanner rather than a wall.
  // Locking them out until approval was a waiting room, and it killed the momentum
  // of someone who had just signed up.)
  if (me && me.operator && me.operator.status === 'suspended') {
    return (
      <div className="min-h-screen bg-[#E4E3E0] text-[#141414] flex items-center justify-center p-4">
        <div className="max-w-sm bg-white border border-[#141414] p-6 text-center space-y-4">
          <Clock className="h-10 w-10 mx-auto text-[#B22222]" />
          <h1 className="font-bold font-mono uppercase">Account suspended</h1>
          <p className="text-xs font-mono text-[#141414]/70 leading-relaxed">
            {me.operator.name} has been suspended. Contact the platform administrator.
          </p>
          <button
            onClick={async () => { await logout(); setMe(null); }}
            className="text-xs font-mono underline cursor-pointer"
          >
            Sign out
          </button>
        </div>
        <ToastHost />
      </div>
    );
  }

  // A new hire must set their own password before anything else — the temp password is single-use.
  if (me && me.must_change_password) {
    return <ForcedPasswordChange me={me} onDone={() => loadMe().catch(() => {})} />;
  }

  const isPlatformStaff = !!me?.is_platform_staff;
  // Show only the sections this role can use (platform staff bypass — they read everything).
  // The server enforces access regardless; this is purely which nav items appear.
  const navGroups = NAV_GROUPS
    .map((g) => ({ ...g, items: g.items.filter((it) => navVisible(me, TAB_CAPABILITY[it.id])) }))
    .filter((g) => g.items.length > 0);
  const acting = me?.acting_operator ?? null;
  // Platform staff inside an ISP that is not their own — only reachable via an
  // audited ImpersonationGrant issued by Platform Control.
  const viewingAsOther =
    isPlatformStaff && acting !== null && acting.slug !== me?.operator?.slug;

  const badgeValue = (item: NavItem): number | null =>
    item.badge && navCounts ? navCounts[item.badge] : null;

  return (
    <div className="flex h-screen w-full bg-[#E4E3E0] text-[#141414] font-sans text-sm overflow-hidden selection:bg-[#141414] selection:text-[#E4E3E0]">
      {/* Sidebar */}
      <aside
        className={`fixed md:relative inset-y-0 left-0 z-40 ${
          isSidebarCollapsed ? 'md:w-16' : 'md:w-60'
        } w-60 border-r border-[#141414] bg-[#E4E3E0] flex flex-col h-full shrink-0 transform md:translate-x-0 transition-all duration-200 ease-in-out ${
          isSidebarOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'
        }`}
      >
        {/* Logo */}
        <div className={`p-4 h-14 border-b border-[#141414] flex items-center ${isSidebarCollapsed ? 'justify-center px-1' : 'justify-between'}`}>
          {isSidebarCollapsed ? (
            <div className="w-5.5 h-5.5 bg-[#141414] rotate-45 shrink-0 flex items-center justify-center" title="WIFI.OS">
              <span className="text-[9px] text-[#E4E3E0] font-mono -rotate-45 font-extrabold">W</span>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <div className="w-3.5 h-3.5 bg-[#141414] rotate-45 shrink-0"></div>
              <span className="font-bold tracking-tighter text-lg uppercase font-mono">WIFI.OS</span>
            </div>
          )}
          {!isSidebarCollapsed && (
            <button
              onClick={() => setIsSidebarOpen(false)}
              className="md:hidden p-1 border border-[#141414] text-[10px] font-mono hover:bg-[#141414] hover:text-white cursor-pointer"
            >
              [X]
            </button>
          )}
        </div>

        {/* Navigation */}
        <nav className="flex-1 py-2 font-mono overflow-y-auto">
          {navGroups.map((group, gi) => (
            <div key={group.title ?? gi}>
              {group.title &&
                (isSidebarCollapsed ? (
                  <div className="mx-3 my-2 border-b border-[#141414]/15" />
                ) : (
                  <div className="px-4 pt-3 pb-1 opacity-50 text-[10px] uppercase italic tracking-wider">{group.title}</div>
                ))}
              {group.items.map((item) => {
                const Icon = item.icon;
                const badge = badgeValue(item);
                const active = activeTab === item.id;
                return (
                  <button
                    key={item.id}
                    onClick={() => {
                      setActiveTab(item.id);
                      setIsSidebarOpen(false);
                    }}
                    title={isSidebarCollapsed ? item.label : undefined}
                    className={`w-full py-2.5 flex items-center transition-all cursor-pointer text-xs ${
                      isSidebarCollapsed ? 'px-0 justify-center' : 'px-4 justify-between'
                    } ${active ? 'bg-[#141414] text-[#E4E3E0] font-bold' : 'hover:bg-white/60 text-[#141414]'}`}
                  >
                    <span className="flex items-center gap-2 min-w-0">
                      <Icon className="h-4 w-4 shrink-0" />
                      {!isSidebarCollapsed && <span className="font-bold tracking-tight truncate">{item.label.toUpperCase()}</span>}
                    </span>
                    {!isSidebarCollapsed && badge !== null && (
                      <span
                        className={`text-[10px] font-bold px-1.5 py-0.5 border ${
                          active ? 'border-[#E4E3E0]/40 text-[#E4E3E0]' : 'border-[#141414]/30 bg-white/70'
                        }`}
                      >
                        {badge}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          ))}
        </nav>

        {/* Footer */}
        <div className={`p-4 border-t border-[#141414] font-mono text-[10px] uppercase ${isSidebarCollapsed ? 'text-center px-1' : ''}`}>
          {isSidebarCollapsed ? (
            <span className="text-[10px] font-bold text-[#141414]/60">v1</span>
          ) : (
            <>
              <p className="opacity-50">WIFI.OS BILLING</p>
              <p className="font-bold">v1.0 — LIVE</p>
            </>
          )}
        </div>
      </aside>

      {/* Mobile backdrop */}
      {isSidebarOpen && <div onClick={() => setIsSidebarOpen(false)} className="fixed inset-0 z-30 bg-[#141414]/40 md:hidden"></div>}

      {/* Main */}
      <main className="flex-1 flex flex-col min-w-0 bg-[#f0efec] h-full overflow-hidden">
        <header className="h-14 border-b border-[#141414] flex items-center justify-between px-4 sm:px-6 bg-white shrink-0">
          <div className="flex items-center gap-3 md:gap-8">
            <button
              onClick={() => {
                if (window.innerWidth < 768) setIsSidebarOpen(!isSidebarOpen);
                else setIsSidebarCollapsed(!isSidebarCollapsed);
              }}
              className="p-1.5 border border-[#141414] bg-[#E4E3E0] text-[#141414] hover:bg-[#141414] hover:text-white transition-colors cursor-pointer flex items-center justify-center shrink-0"
              title={isSidebarCollapsed ? 'Expand menu' : 'Collapse menu'}
            >
              <Wifi className={`h-4 w-4 transition-transform duration-200 ${isSidebarCollapsed ? 'rotate-90' : ''}`} />
            </button>
            <div className="flex flex-col">
              <span className="text-[10px] opacity-60 font-bold uppercase tracking-wider font-serif italic">System State</span>
              <span className="flex items-center gap-1.5 font-mono font-bold text-[#228B22] text-[10px] sm:text-xs">
                <span className="w-2 h-2 rounded-full bg-[#228B22] animate-pulse"></span>
                OPERATIONAL
              </span>
            </div>
            <div className="hidden sm:flex flex-col border-l border-[#141414] pl-5 md:pl-8">
              <span className="text-[10px] opacity-60 font-bold uppercase tracking-wider font-serif italic">Online Now</span>
              <span className="font-mono text-[10px] sm:text-xs font-bold">{navCounts?.active_users ?? '—'} CLIENTS</span>
            </div>
          </div>

          <div className="flex items-center gap-3 sm:gap-4 text-right font-mono text-[10px] sm:text-xs">
            {/* Cross-ISP work lives in Platform Control now. Entering another
                ISP's console is done THERE, through an audited grant — never by
                flipping a dropdown here. */}
            {isPlatformStaff && (
              <a
                href={PLATFORM_CONSOLE_URL}
                target="_blank"
                rel="noreferrer"
                title="Open Platform Control (all ISPs, finance, audit)"
                className="border border-[#141414] bg-[#E4E3E0] px-2 py-1.5 text-[11px] font-mono font-bold uppercase cursor-pointer hover:bg-[#141414] hover:text-white transition flex items-center gap-1.5"
              >
                <Globe className="h-3.5 w-3.5" /> Platform
              </a>
            )}

            {/* Who you are, front and centre — the post-login role identity. */}
            {me && (
              <div className="hidden sm:flex flex-col items-end leading-tight">
                <span className="text-[11px] font-bold truncate max-w-[9rem]">{me.name || me.phone}</span>
                <span
                  className="text-[9px] font-mono font-bold uppercase tracking-wider px-1.5 py-0.5 text-white mt-0.5"
                  style={{ background: ROLE_META[me.role].color }}
                  title={`Signed in as ${ROLE_META[me.role].label}`}
                >
                  {ROLE_META[me.role].label}
                </span>
              </div>
            )}

            <div className="border-l border-[#141414] pl-3 sm:pl-4 text-right">
              <div className="text-[11px] opacity-50 uppercase truncate max-w-[10rem]">
                {acting?.name ?? me?.operator?.name ?? 'No ISP'}
                {me?.is_read_only && ' · read-only'}
              </div>
              <button
                onClick={async () => {
                  await logout(); // the server clears the cookies
                  setMe(null);
                }}
                title="Sign out of the console"
                className="font-bold uppercase tracking-tight hover:text-[#B22222] transition cursor-pointer"
              >
                Sign out
              </button>
            </div>
          </div>
        </header>

        {/* This ISP requires 2FA and this employee hasn't enrolled yet. Money actions are
            TOTP-gated regardless; this nudges them to secure the whole account. */}
        {me?.must_enrol_2fa && (
          <div className="bg-[#B22222] text-white px-4 py-1.5 text-[11px] font-mono flex items-center justify-between gap-2 shrink-0">
            <span className="flex items-center gap-2">
              <ShieldAlert className="h-3.5 w-3.5 shrink-0" />
              Your ISP requires two-factor authentication — set up your authenticator to secure your account.
            </span>
            <button onClick={() => navigate('settings', 'security')} className="underline font-bold shrink-0 cursor-pointer">
              Set up now
            </button>
          </div>
        )}

        {/* Read-only roles (support) can look but not touch. Say so up front —
            otherwise every write silently 403s and looks like a broken API. */}
        {me?.is_read_only && (
          <div className="bg-[#B26B00] text-white px-4 py-1.5 text-[11px] font-mono flex items-center gap-2 shrink-0">
            <Eye className="h-3.5 w-3.5 shrink-0" />
            Read-only access — you can view everything, but changes (re-sync, edits,
            withdrawals) are disabled for your role.
          </div>
        )}

        {/* Loud banner while a platform user is inside someone else's ISP. This
            access is time-boxed and recorded — the banner says so. */}
        {viewingAsOther && (
          <div className="bg-[#2563EB] text-white px-4 py-1.5 text-[11px] font-mono flex items-center justify-between gap-3 shrink-0">
            <span className="flex items-center gap-2 truncate">
              <Eye className="h-3.5 w-3.5 shrink-0" />
              Inside <b>{acting?.name}</b>'s console as platform staff — this session is recorded.
            </span>
            <button
              onClick={exitImpersonation}
              className="underline font-bold shrink-0 cursor-pointer"
            >
              Exit
            </button>
          </div>
        )}

        {/* Read-only demo: every screen is real seeded data, but the API refuses writes.
            Say so up front so a refused action reads as "it's a demo", not "it's broken". */}
        {acting?.is_demo && (
          <div className="bg-[#228B22] text-white px-4 py-1.5 text-[11px] font-mono flex items-center gap-2 shrink-0">
            <Eye className="h-3.5 w-3.5 shrink-0" />
            <span className="truncate">
              You're exploring a live <b>WIFI.OS demo</b> — browse everything; changes are disabled.
            </span>
          </div>
        )}

        <div className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8 min-h-0">
          <div className="max-w-7xl mx-auto space-y-6">
            {/* Platform-wide notices from Danamo (maintenance, price changes, outages).
                Self-contained + dismissable; renders nothing when there's nothing to say. */}
            <BroadcastBanner />

            {/* Pinned until they can take payments. Without it, every blocked
                action just looks like a broken product. Verifying settlement flips
                the gate, so re-ask the server who we are and the banner vanishes. */}
            {acting && !acting.can_transact && (
              <GoLiveBanner
                operator={acting}
                onWentLive={() => {
                  loadMe().catch(() => {});
                  toast('success', 'Payments are ON. Your free month starts now.');
                }}
              />
            )}

            {/* Past-due: pinned while they owe, so a refused sale or a read-only console is
                explained, not mysterious. Vanishes the moment they pay (level -> current). */}
            {acting?.billing && (
              <PastDueBanner
                billing={acting.billing}
                onPay={() => navigate('settings', 'sms')}
              />
            )}

            {activeTab === 'dashboard' && <LiveDashboard onNavigate={(tab) => setActiveTab(tab as TabId)} />}
            {activeTab === 'active_users' && <ActiveUsersView />}
            {activeTab === 'users' && <UsersView />}
            {activeTab === 'tickets' && <TicketsView />}
            {activeTab === 'leads' && <LeadsView />}
            {activeTab === 'packages' && (
              <PlanConfigurator
                profiles={profiles}
                onAddProfile={handleAddProfile}
                onUpdateProfile={handleUpdateProfile}
                onDeleteProfile={handleDeleteProfile}
                onAddLog={addLog}
              />
            )}
            {activeTab === 'payments' && <TransactionsView />}
            {activeTab === 'vouchers' && <VouchersView plans={apiPlans} />}
            {activeTab === 'expenses' && <ExpensesView />}
            {activeTab === 'messages' && <MessagesView />}
            {activeTab === 'emails' && <EmailsView />}
            {activeTab === 'campaigns' && <MessagingView />}
            {activeTab === 'mikrotik' && <RoutersView />}
            {activeTab === 'equipment' && <EquipmentView />}
            {activeTab === 'settings' && (
              <SettingsView
                onOpenWallet={() => setActiveTab('wallet')}
                section={route.sub}
                onSectionChange={(id) => navigate('settings', id)}
              />
            )}
            {activeTab === 'wallet' && <WalletView />}
            {activeTab === 'reports' && <ReportsView />}
            {activeTab === 'pppoe_clients' && <PppoeClientsView />}
            {activeTab === 'pppoe_plans' && <PppoePlansView />}
            {activeTab === 'pppoe_invoices' && <PppoeInvoicesView />}
            {activeTab === 'network' && <NetworkView />}
            {activeTab === 'map' && <MapView onNavigate={(tab) => setActiveTab(tab as TabId)} />}
            {activeTab === 'team' && me && <StaffView me={me} />}
          </div>
        </div>

        <footer className="h-8 border-t border-[#141414] bg-white flex items-center justify-between px-4 sm:px-6 font-mono text-[10px] text-[#141414]/70 shrink-0 select-none">
          <p className="truncate">
            {reconnecting ? (
              <span className="text-[#B26B00]">Reconnecting to the API…</span>
            ) : (
              'WIFI.OS Billing • Connected to live API'
            )}
          </p>
          <div className="hidden sm:flex items-center gap-4">
            <span>{navCounts ? `${navCounts.mikrotik} router${navCounts.mikrotik !== 1 ? 's' : ''}` : ''}</span>
          </div>
        </footer>
        {reconnecting && (
          <div className="fixed bottom-12 left-1/2 -translate-x-1/2 z-50 flex items-center gap-2 bg-[#141414] text-[#E4E3E0] px-3 py-1.5 text-[11px] font-mono shadow-lg">
            <span className="h-2 w-2 rounded-full bg-[#E4A11B] animate-pulse" />
            Reconnecting… your work is safe
          </div>
        )}
      </main>
      <AssistantWidget />
      <ToastHost />
    </div>
  );
}
