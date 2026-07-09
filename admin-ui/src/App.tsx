import React, { useState, useEffect } from 'react';
import { 
  Wifi, 
  Users, 
  Receipt, 
  Tag, 
  Gauge, 
  Settings, 
  Activity, 
  ChevronRight, 
  Clock, 
  RefreshCw, 
  Sun,
  Moon,
  TrendingUp,
  AlertCircle,
  MessageSquare
} from 'lucide-react';

// Models and Helpers
import { BandwidthProfile, Subscriber, HotspotVoucher, Invoice, RouterConfig, SystemLog, OutboundCampaign } from './types';
import {
  DEFAULT_SUBSCRIBERS,
  DEFAULT_VOUCHERS,
  DEFAULT_INVOICES,
  DEFAULT_ROUTER,
  DEFAULT_LOGS,
  generateVoucherCode,
  calculateNextDate,
  runAutomatedBillingJob
} from './utils/billingEngine';

// Live API
import { api, isAuthenticated, logout } from './api/client';
import { planToProfile, profileToPlan, campaignToUi, subscriberToUi } from './api/mappers';

// Components
import SubscriberManager from './components/SubscriberManager';
import HotspotBillingView from './components/HotspotBillingView';
import PlanConfigurator from './components/PlanConfigurator';
import MikroTikIntegration from './components/MikroTikIntegration';
import MessagingView from './components/MessagingView';
import LoginView from './components/LoginView';
import LiveDashboard from './components/LiveDashboard';
import TransactionsView from './components/TransactionsView';

export default function App() {
  const [authed, setAuthed] = useState<boolean>(isAuthenticated());
  const [activeTab, setActiveTab] = useState<string>('dashboard');
  const [simulatedDate, setSimulatedDate] = useState<string>('2026-06-14');
  const [isDarkMode, setIsDarkMode] = useState<boolean>(false);
  const [isSidebarOpen, setIsSidebarOpen] = useState<boolean>(false);
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState<boolean>(() => {
    const saved = localStorage.getItem('wifi_sidebar_collapsed');
    return saved === 'true';
  });

  // Save changes automatically
  useEffect(() => {
    localStorage.setItem('wifi_sidebar_collapsed', String(isSidebarCollapsed));
  }, [isSidebarCollapsed]);

  // Live server state (plans come from the Django API)
  const [profiles, setProfiles] = useState<BandwidthProfile[]>([]);

  const [subscribers, setSubscribers] = useState<Subscriber[]>(() => {
    const saved = localStorage.getItem('wifi_subscribers');
    return saved ? JSON.parse(saved) : DEFAULT_SUBSCRIBERS;
  });

  const [vouchers, setVouchers] = useState<HotspotVoucher[]>(() => {
    const saved = localStorage.getItem('wifi_vouchers');
    return saved ? JSON.parse(saved) : DEFAULT_VOUCHERS;
  });

  const [invoices, setInvoices] = useState<Invoice[]>(() => {
    const saved = localStorage.getItem('wifi_invoices');
    return saved ? JSON.parse(saved) : DEFAULT_INVOICES;
  });

  const [router, setRouter] = useState<RouterConfig>(() => {
    const saved = localStorage.getItem('wifi_router');
    return saved ? JSON.parse(saved) : DEFAULT_ROUTER;
  });

  const [logs, setLogs] = useState<SystemLog[]>(() => {
    const saved = localStorage.getItem('wifi_logs');
    return saved ? JSON.parse(saved) : DEFAULT_LOGS;
  });

  // Live server state (campaigns + subscribers for messaging audience counts)
  const [campaigns, setCampaigns] = useState<OutboundCampaign[]>([]);
  const [liveSubscribers, setLiveSubscribers] = useState<Subscriber[]>([]);

  // Load live data once signed in
  useEffect(() => {
    if (!authed) return;
    api.plans.list().then(r => setProfiles(r.results.map(planToProfile))).catch(() => {});
    api.campaigns.list().then(r => setCampaigns(r.results.map(campaignToUi).reverse())).catch(() => {});
    api.subscribers.list().then(r => setLiveSubscribers(r.results.map(subscriberToUi))).catch(() => {});
  }, [authed]);

  useEffect(() => {
    localStorage.setItem('wifi_subscribers', JSON.stringify(subscribers));
  }, [subscribers]);

  useEffect(() => {
    localStorage.setItem('wifi_vouchers', JSON.stringify(vouchers));
  }, [vouchers]);

  useEffect(() => {
    localStorage.setItem('wifi_invoices', JSON.stringify(invoices));
  }, [invoices]);

  useEffect(() => {
    localStorage.setItem('wifi_router', JSON.stringify(router));
  }, [router]);

  useEffect(() => {
    localStorage.setItem('wifi_logs', JSON.stringify(logs));
  }, [logs]);

  // Darkmode sync
  useEffect(() => {
    if (isDarkMode) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [isDarkMode]);

  // Auxiliary logs function
  const addLog = (
    category: 'Router' | 'Billing' | 'Subscriber' | 'Hotspot',
    type: 'info' | 'success' | 'warning' | 'error',
    message: string
  ) => {
    const timeNow = new Date();
    const pad = (n: number) => String(n).padStart(2, '0');
    const timestampStr = `${simulatedDate} ${pad(timeNow.getHours())}:${pad(timeNow.getMinutes())}:${pad(timeNow.getSeconds())}`;
    
    setLogs(prev => [
      ...prev,
      {
        id: `log-active-${Date.now()}-${Math.random()}`,
        timestamp: timestampStr,
        category,
        type,
        message
      }
    ]);
  };

  // Roll simulated date by 1 day and automatically run client audits
  const advanceSimulatedDate = () => {
    const nextDay = calculateNextDate(simulatedDate, 'Daily', 1);
    setSimulatedDate(nextDay);
    
    // Log the date change
    addLog('Billing', 'info', `Environment configuration: Advanced simulated core cluster clock to next cycle: ${nextDay}.`);
    
    // Automatically run the invoicing check for the new day
    setTimeout(() => {
      const invoiceCounter = invoices.length + 1;
      const result = runAutomatedBillingJob(subscribers, profiles, nextDay, invoiceCounter);
      if (result.newInvoices.length > 0) {
        setInvoices(prev => [...prev, ...result.newInvoices]);
        setSubscribers(result.updatedSubscribers);
        setLogs(prev => [...prev, ...result.newLogs]);
      }
    }, 150);
  };

  // Instantly issue manual on-demand invoice for a customer
  const handleTriggerManualInvoiceInstance = (sub: Subscriber) => {
    const subPlan = profiles.find(p => p.id === sub.planId);
    if (!subPlan) return;

    const invoiceCounter = invoices.length + 1;
    const invNum = `INV-INT-${String(invoiceCounter).padStart(3, '0')}`;
    
    const newInv: Invoice = {
      id: `inv-inst-${sub.id}-${Date.now()}`,
      invoiceNumber: invNum,
      subscriberId: sub.id,
      subscriberName: sub.name,
      planName: subPlan.name,
      amount: subPlan.price,
      status: 'Unpaid',
      dateCreated: simulatedDate,
      dateDue: calculateNextDate(simulatedDate, 'Daily', 3),
      periodStart: simulatedDate,
      periodEnd: calculateNextDate(simulatedDate, 'Daily', subPlan.validityDays)
    };

    setInvoices(prev => [...prev, newInv]);
    setSubscribers(prev => prev.map(s => {
      if (s.id === sub.id) {
        return {
          ...s,
          balance: Number((s.balance + subPlan.price).toFixed(2))
        };
      }
      return s;
    }));

    addLog(
      'Billing',
      'success',
      `On-Demand Invoicing: Manual instance bill ${invNum} of KSh ${subPlan.price.toLocaleString()} generated for ${sub.name}.`
    );
  };

  // Add/Edit Profiles — persisted through the Django API
  const handleAddProfile = async (newProf: Omit<BandwidthProfile, 'id'>) => {
    try {
      const created = await api.plans.create(profileToPlan(newProf));
      setProfiles(prev => [...prev, planToProfile(created)]);
      addLog('Billing', 'success', `Plan '${created.name}' saved to the server.`);
    } catch {
      addLog('Billing', 'error', 'Failed to save plan — check the API connection.');
    }
  };

  const handleUpdateProfile = async (updatedProf: BandwidthProfile) => {
    try {
      const saved = await api.plans.update(Number(updatedProf.id), profileToPlan(updatedProf));
      setProfiles(prev => prev.map(p => p.id === updatedProf.id ? planToProfile(saved) : p));
    } catch {
      addLog('Billing', 'error', 'Failed to update plan — check the API connection.');
    }
  };

  const handleDeleteProfile = async (id: string) => {
    try {
      await api.plans.remove(Number(id));
      setProfiles(prev => prev.filter(p => p.id !== id));
    } catch {
      addLog('Billing', 'error', 'Could not delete plan — plans with payment history should be deactivated instead.');
    }
  };

  // Add/Edit Subscribers
  const handleAddSubscriber = (newSub: Omit<Subscriber, 'id' | 'createdAt'>) => {
    setSubscribers(prev => [...prev, { 
      ...newSub, 
      id: `sub-${Date.now()}`,
      createdAt: simulatedDate
    }]);
  };

  const handleUpdateSubscriber = (updatedSub: Subscriber) => {
    setSubscribers(prev => prev.map(s => s.id === updatedSub.id ? updatedSub : s));
  };

  const handleDeleteSubscriber = (id: string) => {
    setSubscribers(prev => prev.filter(s => s.id !== id));
  };

  // Generate hotspot coupons
  const handleGenerateVouchers = (profileId: string, count: number, prefix: string) => {
    const selectedProfile = profiles.find(p => p.id === profileId);
    if (!selectedProfile) return;

    const newBatch: HotspotVoucher[] = [];
    for (let i = 0; i < count; i++) {
      newBatch.push({
        id: `vouch-${Date.now()}-${i}-${Math.random()}`,
        code: generateVoucherCode(6, prefix),
        profileId,
        price: selectedProfile.price,
        status: 'Unused',
        createdAt: new Date().toISOString()
      });
    }

    setVouchers(prev => [...prev, ...newBatch]);
  };

  const handleClearExpiredVouchers = () => {
    setVouchers(prev => prev.filter(v => v.status !== 'Expired'));
    addLog('Hotspot', 'warning', 'Cleaned expired hotspot session files from controller cache.');
  };

  const handleUseVoucher = (code: string, mac: string) => {
    setVouchers(prev => prev.map(v => {
      if (v.code.toUpperCase() === code.toUpperCase()) {
        const p = profiles.find(prof => prof.id === v.profileId);
        const expireInDays = p?.validityDays || 1;
        const usedAtStr = new Date().toISOString();
        
        // Calculate expiration string based on simulated validity
        const expireDate = new Date(simulatedDate);
        expireDate.setDate(expireDate.getDate() + expireInDays);

        return {
          ...v,
          status: 'Active',
          usedByMac: mac,
          usedAt: usedAtStr,
          expiresBy: expireDate.toISOString().substring(0, 10)
        };
      }
      return v;
    }));
  };

  const handleDeleteVoucher = (id: string) => {
    setVouchers(prev => prev.filter(v => v.id !== id));
  };

  // Bulk SMS / WhatsApp broadcast — dispatched by the server via Celery
  const handleSendCampaign = async (campaign: Omit<OutboundCampaign, 'id' | 'sentAt' | 'status'>) => {
    try {
      await api.campaigns.create({
        name: campaign.name,
        channel: campaign.channel.toLowerCase(),
        audience: campaign.audience.toLowerCase(),
        body: campaign.body,
      });
      const r = await api.campaigns.list();
      setCampaigns(r.results.map(campaignToUi).reverse());
      addLog(
        'Subscriber',
        'success',
        `Messaging: ${campaign.channel} broadcast "${campaign.name}" queued for ${campaign.audience.toLowerCase()} clients.`
      );
    } catch {
      addLog('Subscriber', 'error', 'Messaging: failed to queue the broadcast — check the API connection.');
    }
  };

  if (!authed) {
    return <LoginView onLoggedIn={() => setAuthed(true)} />;
  }

  return (
    <div className="flex h-screen w-full bg-[#E4E3E0] text-[#141414] font-sans text-sm overflow-hidden selection:bg-[#141414] selection:text-[#E4E3E0]">
      
      {/* Responsive Left Sidebar */}
      <aside className={`fixed md:relative inset-y-0 left-0 z-40 ${
        isSidebarCollapsed ? 'md:w-16' : 'md:w-56'
      } w-56 border-r border-[#141414] bg-[#E4E3E0] flex flex-col h-full shrink-0 transform md:translate-x-0 transition-all duration-200 ease-in-out ${
        isSidebarOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'
      }`}>
        
        {/* Sidebar Header Logo */}
        <div className={`p-4 h-14 border-b border-[#141414] flex items-center ${
          isSidebarCollapsed ? 'justify-center px-1' : 'justify-between'
        }`}>
          {isSidebarCollapsed ? (
            <div className="w-5.5 h-5.5 bg-[#141414] rotate-45 shrink-0 flex items-center justify-center hover:scale-110 transition-transform cursor-pointer" title="WIFI.OS ISP Console">
              <span className="text-[11px] text-[#E4E3E0] font-mono -rotate-45 font-extrabold">W</span>
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
              className="md:hidden p-1 border border-[#141414] text-[11px] font-mono hover:bg-[#141414] hover:text-white cursor-pointer"
            >
              [X]
            </button>
          )}
        </div>

        {/* Sidebar Navigation */}
        <nav className="flex-1 py-3 font-mono overflow-y-auto">
          {isSidebarCollapsed ? (
            <div className="mx-3 my-2 border-b border-[#141414]/15" />
          ) : (
            <div className="px-4 py-1 opacity-50 text-[11px] uppercase italic tracking-wider">Infrastructure</div>
          )}
          
          <button
            onClick={() => { setActiveTab('dashboard'); setIsSidebarOpen(false); }}
            className={`w-full py-2.5 flex items-center transition-all cursor-pointer text-xs ${
              isSidebarCollapsed ? 'px-0 justify-center' : 'px-4 justify-between'
            } ${
              activeTab === 'dashboard'
                ? 'bg-[#141414] text-[#E4E3E0] font-bold'
                : 'hover:bg-white/60 text-[#141414]'
            }`}
            title={isSidebarCollapsed ? "Dashboard [01]" : undefined}
          >
            <span className="flex items-center gap-2">
              <TrendingUp className="h-4 w-4 shrink-0" />
              {!isSidebarCollapsed && <span className="font-bold tracking-tight">DASHBOARD</span>}
            </span>
            {!isSidebarCollapsed && <span className="text-xs font-bold">[01]</span>}
          </button>

          <button
            onClick={() => { setActiveTab('mikrotik'); setIsSidebarOpen(false); }}
            className={`w-full py-2.5 flex items-center transition-all cursor-pointer text-xs ${
              isSidebarCollapsed ? 'px-0 justify-center' : 'px-4 justify-between'
            } ${
              activeTab === 'mikrotik'
                ? 'bg-[#141414] text-[#E4E3E0] font-bold'
                : 'hover:bg-white/60 text-[#141414]'
            }`}
            title={isSidebarCollapsed ? "MikroTik Node [02]" : undefined}
          >
            <span className="flex items-center gap-2">
              <Settings className="h-4 w-4 shrink-0" />
              {!isSidebarCollapsed && <span className="font-bold tracking-tight">MIKROTIK NODE</span>}
            </span>
            {!isSidebarCollapsed && <span className="text-xs font-bold">[02]</span>}
          </button>

          <button
            onClick={() => { setActiveTab('hotspot'); setIsSidebarOpen(false); }}
            className={`w-full py-2.5 flex items-center transition-all cursor-pointer text-xs ${
              isSidebarCollapsed ? 'px-0 justify-center' : 'px-4 justify-between'
            } ${
              activeTab === 'hotspot'
                ? 'bg-[#141414] text-[#E4E3E0] font-bold'
                : 'hover:bg-white/60 text-[#141414]'
            }`}
            title={isSidebarCollapsed ? "Hotspot Config [03]" : undefined}
          >
            <span className="flex items-center gap-2">
              <Tag className="h-4 w-4 shrink-0" />
              {!isSidebarCollapsed && <span className="font-bold tracking-tight">HOTSPOT CONFIG</span>}
            </span>
            {!isSidebarCollapsed && <span className="text-xs font-bold">[03]</span>}
          </button>

          {isSidebarCollapsed ? (
            <div className="mx-3 my-3 border-b border-[#141414]/15" />
          ) : (
            <div className="px-4 py-1 mt-4 opacity-50 text-[11px] uppercase italic tracking-wider">Finance & Setup</div>
          )}
          
          <button
            onClick={() => { setActiveTab('subscribers'); setIsSidebarOpen(false); }}
            className={`w-full py-2.5 flex items-center transition-all cursor-pointer text-xs ${
              isSidebarCollapsed ? 'px-0 justify-center' : 'px-4 justify-between'
            } ${
              activeTab === 'subscribers'
                ? 'bg-[#141414] text-[#E4E3E0] font-bold'
                : 'hover:bg-white/60 text-[#141414]'
            }`}
            title={isSidebarCollapsed ? "Subscribers [04]" : undefined}
          >
            <span className="flex items-center gap-2">
              <Users className="h-4 w-4 shrink-0" />
              {!isSidebarCollapsed && <span className="font-bold tracking-tight">SUBSCRIBERS</span>}
            </span>
            {!isSidebarCollapsed && <span className="text-xs font-bold">[04]</span>}
          </button>

          <button
            onClick={() => { setActiveTab('invoices'); setIsSidebarOpen(false); }}
            className={`w-full py-2.5 flex items-center transition-all cursor-pointer text-xs ${
              isSidebarCollapsed ? 'px-0 justify-center' : 'px-4 justify-between'
            } ${
              activeTab === 'invoices'
                ? 'bg-[#141414] text-[#E4E3E0] font-bold'
                : 'hover:bg-white/60 text-[#141414]'
            }`}
            title={isSidebarCollapsed ? "Invoicing [05]" : undefined}
          >
            <span className="flex items-center gap-2">
              <Receipt className="h-4 w-4 shrink-0" />
              {!isSidebarCollapsed && <span className="font-bold tracking-tight">TRANSACTIONS</span>}
            </span>
            {!isSidebarCollapsed && <span className="text-xs font-bold">[05]</span>}
          </button>

          <button
            onClick={() => { setActiveTab('plans'); setIsSidebarOpen(false); }}
            className={`w-full py-2.5 flex items-center transition-all cursor-pointer text-xs ${
              isSidebarCollapsed ? 'px-0 justify-center' : 'px-4 justify-between'
            } ${
              activeTab === 'plans'
                ? 'bg-[#141414] text-[#E4E3E0] font-bold'
                : 'hover:bg-white/60 text-[#141414]'
            }`}
            title={isSidebarCollapsed ? "Speed Plans [06]" : undefined}
          >
            <span className="flex items-center gap-2">
              <Gauge className="h-4 w-4 shrink-0" />
              {!isSidebarCollapsed && <span className="font-bold tracking-tight">SPEED PLANS</span>}
            </span>
            {!isSidebarCollapsed && <span className="text-xs font-bold">[06]</span>}
          </button>

          <button
            onClick={() => { setActiveTab('messaging'); setIsSidebarOpen(false); }}
            className={`w-full py-2.5 flex items-center transition-all cursor-pointer text-xs ${
              isSidebarCollapsed ? 'px-0 justify-center' : 'px-4 justify-between'
            } ${
              activeTab === 'messaging'
                ? 'bg-[#141414] text-[#E4E3E0] font-bold'
                : 'hover:bg-white/60 text-[#141414]'
            }`}
            title={isSidebarCollapsed ? "Messaging [07]" : undefined}
          >
            <span className="flex items-center gap-2">
              <MessageSquare className="h-4 w-4 shrink-0" />
              {!isSidebarCollapsed && <span className="font-bold tracking-tight">MESSAGING</span>}
            </span>
            {!isSidebarCollapsed && <span className="text-xs font-bold">[07]</span>}
          </button>
        </nav>

        {/* Sidebar Footer Info */}
        <div className={`p-4 border-t border-[#141414] font-mono text-[11px] uppercase space-y-2 ${isSidebarCollapsed ? 'text-center px-1' : ''}`}>
          {isSidebarCollapsed ? (
            <span className="text-[10px] font-bold text-[#141414]/60 bg-[#141414]/10 px-1 py-0.5 rounded-none" title="WIFI.OS Controller version">v4.82</span>
          ) : (
            <>
              <div>
                <p className="opacity-50">SYSTEM UPTIME</p>
                <p className="font-bold">182D:14H:22M</p>
              </div>
              <div className="border-t border-[#141414]/10 pt-2">
                <p className="opacity-50">TOTAL SUBSCRIBERS</p>
                <p className="font-bold">{subscribers.length} CLIENTS</p>
              </div>
              <div className="border-t border-[#141414]/10 pt-2">
                <p className="opacity-50">VOUCHERS ACTIVE</p>
                <p className="font-bold">{vouchers.filter(v => v.status === 'Active').length} CLIENTS</p>
              </div>
              <div className="border-t border-[#141414]/10 pt-2">
                <p className="opacity-60 text-[10px] italic">v4.82.0-STABLE (MTK_R01)</p>
              </div>
            </>
          )}
        </div>
      </aside>

      {/* Backdrop overlay for mobile sidebar */}
      {isSidebarOpen && (
        <div 
          onClick={() => setIsSidebarOpen(false)}
          className="fixed inset-0 z-30 bg-[#141414]/40 md:hidden"
        ></div>
      )}

      {/* Main Panel */}
      <main className="flex-1 flex flex-col min-w-0 bg-[#f0efec] h-full overflow-hidden">
        
        {/* Top Header Panel */}
        <header className="h-14 border-b border-[#141414] flex items-center justify-between px-4 sm:px-6 bg-white shrink-0">
          
          <div className="flex items-center gap-3 md:gap-8">
            <button 
              onClick={() => {
                if (window.innerWidth < 768) {
                  setIsSidebarOpen(!isSidebarOpen);
                } else {
                  setIsSidebarCollapsed(!isSidebarCollapsed);
                }
              }}
              className="p-1.5 border border-[#141414] bg-[#E4E3E0] text-[#141414] hover:bg-[#141414] hover:text-white transition-colors cursor-pointer flex items-center justify-center shrink-0"
              title={isSidebarCollapsed ? "Expand Sidebar Menu" : "Collapse Sidebar Menu"}
            >
              <Wifi className={`h-4 w-4 transition-transform duration-200 ${isSidebarCollapsed ? 'rotate-90' : ''}`} />
            </button>
            
            <div className="flex flex-col">
              <span className="text-[11px] opacity-60 font-bold uppercase tracking-wider font-serif italic">System State</span>
              <span className="flex items-center gap-1.5 font-mono font-bold text-[#228B22] text-xs sm:text-xs">
                <span className="w-2 h-2 rounded-full bg-[#228B22] animate-pulse"></span>
                OPERATIONAL
              </span>
            </div>
            
            <div className="hidden sm:flex flex-col border-l border-[#141414] pl-5 md:pl-8">
              <span className="text-[11px] opacity-60 font-bold uppercase tracking-wider font-serif italic">MikroTik Sync</span>
              <span className="font-mono text-xs sm:text-xs font-bold text-[#141414]">
                {router.ip || '192.168.88.1'} ({router.isConnected ? 'ACTIVE' : 'OFFLINE'})
              </span>
            </div>
          </div>

          <div className="flex items-center gap-3 sm:gap-4 text-right font-mono text-xs sm:text-xs">
            
            {/* Clock simulated advance controller */}
            <div className="flex items-center gap-2 border border-[#141414] bg-[#E4E3E0] p-1 px-2">
              <div className="text-left hidden xs:block">
                <span className="text-[10px] opacity-50 block uppercase font-mono leading-none">CLK</span>
                <span className="font-mono font-extrabold text-[#141414] text-xs sm:text-xs">{simulatedDate}</span>
              </div>
              <button
                onClick={advanceSimulatedDate}
                title="Advance core system calendar day to check subscription lifespans"
                className="bg-[#141414] hover:bg-white hover:text-[#141414] border border-[#141414] text-[#E4E3E0] text-[11px] font-bold px-1.5 sm:px-2.5 py-1 flex items-center gap-1 transition-colors uppercase shrink-0"
              >
                <Clock className="h-3 w-3" />
                <span>+1 Day</span>
              </button>
            </div>

            <div className="hidden lg:flex items-center gap-3 border-l border-[#141414] pl-4">
              <div>
                <div className="text-[11px] opacity-50 uppercase italic font-bold">ROUTER CPU</div>
                <div className="h-1 w-20 bg-[#E4E3E0] relative mt-1 border border-[#141414]/30">
                  <div className="absolute left-0 top-0 h-full bg-[#141414]" style={{ width: '28%' }}></div>
                </div>
              </div>
            </div>

            <div className="border-l border-[#141414] pl-3 sm:pl-4 text-right">
              <div className="text-[11px] opacity-50 uppercase">Session Operator</div>
              <button
                onClick={() => { logout(); setAuthed(false); }}
                title="Sign out of the console"
                className="font-bold uppercase tracking-tight hover:text-[#B22222] transition cursor-pointer"
              >
                Sign out
              </button>
            </div>

          </div>
        </header>

        {/* Dynamic Inner Tab View, automatically scrolling with high-density container layouts */}
        <div className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8 min-h-0">
          <div className="max-w-7xl mx-auto space-y-6">
            {activeTab === 'dashboard' && (
              <LiveDashboard onNavigate={setActiveTab} />
            )}

            {activeTab === 'subscribers' && (
              <SubscriberManager
                subscribers={subscribers}
                profiles={profiles}
                onAddSubscriber={handleAddSubscriber}
                onUpdateSubscriber={handleUpdateSubscriber}
                onDeleteSubscriber={handleDeleteSubscriber}
                onTriggerManualInvoice={handleTriggerManualInvoiceInstance}
                onAddLog={addLog}
              />
            )}

            {activeTab === 'hotspot' && (
              <HotspotBillingView
                vouchers={vouchers}
                profiles={profiles}
                onGenerateVouchers={handleGenerateVouchers}
                onClearExpiredVouchers={handleClearExpiredVouchers}
                onUseVoucher={handleUseVoucher}
                onDeleteVoucher={handleDeleteVoucher}
                onAddLog={addLog}
              />
            )}

            {activeTab === 'invoices' && (
              <TransactionsView />
            )}

            {activeTab === 'plans' && (
              <PlanConfigurator
                profiles={profiles}
                onAddProfile={handleAddProfile}
                onUpdateProfile={handleUpdateProfile}
                onDeleteProfile={handleDeleteProfile}
                onAddLog={addLog}
              />
            )}

            {activeTab === 'messaging' && (
              <MessagingView
                campaigns={campaigns}
                subscribers={liveSubscribers}
                onSendCampaign={handleSendCampaign}
                onAddLog={addLog}
              />
            )}

            {activeTab === 'mikrotik' && (
              <MikroTikIntegration
                router={router}
                subscribers={subscribers}
                vouchers={vouchers}
                onUpdateRouter={setRouter}
                logs={logs}
                onAddLog={addLog}
              />
            )}
          </div>
        </div>

        {/* Footing Status Bar */}
        <footer className="h-8 border-t border-[#141414] bg-white flex items-center justify-between px-4 sm:px-6 font-mono text-[11px] text-[#141414]/70 shrink-0 select-none">
          <p className="truncate">WIFI.OS ISP Controller â€¢ System synchronized with MikroTik API bounds</p>
          <div className="hidden sm:flex items-center gap-4">
            <span className="flex items-center gap-1"><span className="w-1.5 h-1.5 rounded-full bg-[#228B22] animate-ping"></span> Firewall: Online</span>
            <span>|</span>
            <span>Interfaces: 4 Active</span>
          </div>
        </footer>

      </main>
    </div>
  );
}
