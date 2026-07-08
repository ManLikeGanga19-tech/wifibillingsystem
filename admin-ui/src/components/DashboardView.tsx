import React, { useState, useEffect } from 'react';
import { Subscriber, Invoice, HotspotVoucher, RouterConfig, SystemLog, BandwidthProfile } from '../types';
import { 
  Wifi, 
  Users, 
  Tag, 
  DollarSign, 
  Radio, 
  TrendingUp, 
  Activity, 
  AlertTriangle, 
  CheckCircle, 
  Clock, 
  RefreshCw, 
  Database,
  ArrowUpRight,
  ArrowDownLeft,
  ChevronRight
} from 'lucide-react';

interface DashboardViewProps {
  subscribers: Subscriber[];
  invoices: Invoice[];
  vouchers: HotspotVoucher[];
  router: RouterConfig;
  profiles: BandwidthProfile[];
  logs: SystemLog[];
  onTriggerBillingJob: () => void;
  onNavigate: (tab: string) => void;
  simulatedDate: string;
}

export default function DashboardView({
  subscribers,
  invoices,
  vouchers,
  router,
  profiles,
  logs,
  onTriggerBillingJob,
  onNavigate,
  simulatedDate
}: DashboardViewProps) {
  const [liveDownload, setLiveDownload] = useState<number>(31.4);
  const [liveUpload, setLiveUpload] = useState<number>(12.8);
  const [trafficHistory, setTrafficHistory] = useState<{rx: number; tx: number}[]>(
    Array.from({ length: 15 }, () => ({ rx: Math.random() * 20 + 10, tx: Math.random() * 10 + 4 }))
  );

  // Simulate active router bandwidth polling
  useEffect(() => {
    if (!router.isConnected) return;
    const interval = setInterval(() => {
      const rxDelta = (Math.random() - 0.4) * 4;
      const txDelta = (Math.random() - 0.4) * 2;
      setLiveDownload(prev => Math.max(2.1, Math.min(95.0, Number((prev + rxDelta).toFixed(1)))));
      setLiveUpload(prev => Math.max(1.0, Math.min(45.0, Number((prev + txDelta).toFixed(1)))));

      setTrafficHistory(prev => {
        const next = [...prev.slice(1)];
        next.push({ rx: Math.max(5, Math.min(90, prev[prev.length-1].rx + rxDelta)), tx: Math.max(2, Math.min(40, prev[prev.length-1].tx + txDelta)) });
        return next;
      });
    }, 2500);

    return () => clearInterval(interval);
  }, [router.isConnected]);

  // Aggregate Metrics
  const totalPaid = invoices.filter(inv => inv.status === 'Paid').reduce((sum, inv) => sum + inv.amount, 0);
  const totalOverdue = invoices.filter(inv => inv.status === 'Overdue').reduce((sum, inv) => sum + inv.amount, 0);
  const totalUnpaid = invoices.filter(inv => inv.status === 'Unpaid').reduce((sum, inv) => sum + inv.amount, 0);
  
  const activeSubs = subscribers.filter(sub => sub.status === 'Active');
  const expiredSubs = subscribers.filter(sub => sub.status === 'Expired');
  
  const activeVouchers = vouchers.filter(v => v.status === 'Active');
  const unusedVouchers = vouchers.filter(v => v.status === 'Unused');

  const profileBreakdown = profiles.map(prof => {
    const subCount = subscribers.filter(s => s.planId === prof.id).length;
    const vouchCount = vouchers.filter(v => v.profileId === prof.id).length;
    return {
      name: prof.name,
      subs: subCount,
      vouchs: vouchCount,
      revenue: (subCount * prof.price) + (vouchCount * prof.price)
    };
  });

  return (
    <div className="space-y-6">
      {/* Top Banner / System Status Alerts */}
      <div className="flex flex-col md:flex-row md:items-center md:justify-between bg-white border border-[#141414] p-4 rounded-none gap-4">
        <div>
          <h2 className="text-lg font-serif italic font-bold uppercase tracking-tight text-[#141414]">
            WiFi Network Controller Overview
          </h2>
          <p className="text-[#141414]/70 text-xs font-mono mt-1">
            Simulated System Clock: <span className="font-bold bg-[#E4E3E0] px-2 py-0.5 border border-[#141414]/30">{simulatedDate}</span> â€¢ Cluster Status: <span className="text-[#228B22] font-semibold uppercase">â— OPERATIONAL</span>
          </p>
        </div>
        
        <div className="flex flex-wrap items-center gap-3">
          <button 
            type="button"
            id="btn-run-billing"
            onClick={onTriggerBillingJob}
            className="inline-flex items-center gap-2 px-3 py-1.5 text-xs font-mono tracking-widest uppercase font-bold text-white bg-[#141414] hover:bg-white hover:text-[#141414] border border-[#141414] rounded-none transition-colors cursor-pointer"
          >
            <RefreshCw className="h-3 w-3 animate-spin-reverse hover:rotate-180 transition duration-500" />
            RUN_BILLING_ENGINE
          </button>
          
          <div className="inline-flex items-center gap-2 px-3 py-1.5 border border-[#141414] bg-[#E4E3E0] text-xs font-mono font-bold">
            <span className={`w-2 h-2 rounded-full ${router.isConnected ? 'bg-[#228B22] pulse-active' : 'bg-[#FF4500]'}`}></span>
            <span>MIKROTIK: <span>{router.isConnected ? 'ONLINE' : 'OFFLINE'}</span></span>
          </div>
        </div>
      </div>

      {/* KPI Stats Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Metric 1 */}
        <div id="kpi-total-revenue" className="border border-[#141414] p-4 bg-white rounded-none">
          <div className="text-xs font-mono opacity-50 uppercase tracking-wider">TOTAL_REVENUE_MTD</div>
          <div className="text-3xl font-mono tracking-tighter mt-1 font-bold italic text-[#141414]">
            Ksh {totalPaid.toLocaleString()}
          </div>
          <div className="text-xs text-[#228B22] font-mono font-bold mt-1 uppercase">
            +14.2% VS L_MONTH
          </div>
        </div>

        {/* Metric 2 */}
        <div id="kpi-active-subscribers" className="border border-[#141414] p-4 bg-white rounded-none">
          <div className="text-xs font-mono opacity-50 uppercase tracking-wider">ACTIVE_SESSIONS</div>
          <div className="text-3xl font-mono tracking-tighter mt-1 font-bold text-[#141414]">
            {activeSubs.length} <span className="text-xs font-normal opacity-50">/ {subscribers.length} total</span>
          </div>
          <div className="text-xs text-[#141414]/70 font-mono font-bold mt-1 uppercase">
            {expiredSubs.length} accounts pending renewal
          </div>
        </div>

        {/* Metric 3 */}
        <div id="kpi-hotspot-vouchers" className="border border-[#141414] p-4 bg-white rounded-none">
          <div className="text-xs font-mono opacity-50 uppercase tracking-wider">HOTSPOT_COUPONS</div>
          <div className="text-3xl font-mono tracking-tighter mt-1 font-bold text-[#141414]">
            {activeVouchers.length} <span className="text-xs font-normal opacity-50"> / {vouchers.length} created</span>
          </div>
          <div className="text-xs text-[#141414]/70 font-mono font-bold mt-1 uppercase">
            {unusedVouchers.length} ready coupons remaining
          </div>
        </div>

        {/* Metric 4 */}
        <div id="kpi-outstanding-billing" className="border border-[#141414] p-4 bg-white rounded-none">
          <div className="text-xs font-mono opacity-50 uppercase tracking-wider">INVOICES_PENDING</div>
          <div className="text-3xl font-mono tracking-tighter mt-1 font-bold text-[#FF4500]">
            Ksh {(totalUnpaid + totalOverdue).toLocaleString()}
          </div>
          <div className="text-xs text-[#FF4500] font-mono font-bold mt-1 uppercase">
            AUTO_RETRY_ACTIVE
          </div>
        </div>
      </div>

      {/* Main Charts & Traffic Dashboard */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        {/* Real-time Traffic Graph & MikroTik Info */}
        <div className="lg:col-span-2 border border-[#141414] bg-white p-4 rounded-none flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between border-b border-[#141414]/20 pb-3">
              <div>
                <h3 className="text-sm font-serif italic font-bold uppercase tracking-tight text-[#141414]">
                  MikroTik Live Interfaces Rate
                </h3>
                <p className="text-xs text-[#141414]/70 font-mono mt-0.5">
                  INTERFACE: <span className="font-bold bg-[#E4E3E0] text-[#141414] px-1.5 py-0.2 border border-[#141414]/20">{router.hotspotInterface}</span>
                </p>
              </div>
              <div className="flex items-center gap-4 font-mono text-xs">
                <span className="text-[#228B22] flex items-center gap-1 font-bold">
                  <span className="h-2 w-2 rounded-full bg-[#228B22] animate-pulse"></span>
                  RX: {liveDownload} MBPS
                </span>
                <span className="text-[#141414] flex items-center gap-1 font-bold">
                  <span className="h-2 w-2 rounded-full bg-[#141414] animate-pulse"></span>
                  TX: {liveUpload} MBPS
                </span>
              </div>
            </div>
 
            {/* Custom SVG Line Chart representation */}
            <div className="h-44 mt-4 w-full relative">
              <svg className="w-full h-full overflow-visible" preserveAspectRatio="none" viewBox="0 0 300 100">
                <defs>
                  <linearGradient id="rxGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#228B22" stopOpacity="0.25"/>
                    <stop offset="100%" stopColor="#228B22" stopOpacity="0"/>
                  </linearGradient>
                  <linearGradient id="txGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="#141414" stopOpacity="0.15"/>
                    <stop offset="100%" stopColor="#141414" stopOpacity="0"/>
                  </linearGradient>
                </defs>
                
                {/* Horizontal assist lines */}
                <line x1="0" y1="20" x2="300" y2="20" stroke="#141414" strokeWidth="0.5" strokeDasharray="3,3" strokeOpacity="0.1" />
                <line x1="0" y1="50" x2="300" y2="50" stroke="#141414" strokeWidth="0.5" strokeDasharray="3,3" strokeOpacity="0.1" />
                <line x1="0" y1="80" x2="300" y2="80" stroke="#141414" strokeWidth="0.5" strokeDasharray="3,3" strokeOpacity="0.1" />
                
                {/* RX Download Path */}
                <path
                  d={`M ${trafficHistory.map((pt, i) => `${(i / (trafficHistory.length - 1)) * 300},${100 - (pt.rx / 100) * 100}`).join(' L ')}`}
                  fill="none"
                  stroke="#228B22"
                  strokeWidth="2"
                  strokeLinecap="square"
                />
                
                {/* RX Download Fill */}
                <path
                  d={`M 0,100 L ${trafficHistory.map((pt, i) => `${(i / (trafficHistory.length - 1)) * 300},${100 - (pt.rx / 100) * 100}`).join(' L ')} L 300,100 Z`}
                  fill="url(#rxGrad)"
                />
 
                {/* TX Upload Path */}
                <path
                  d={`M ${trafficHistory.map((pt, i) => `${(i / (trafficHistory.length - 1)) * 300},${100 - (pt.tx / 50) * 100}`).join(' L ')}`}
                  fill="none"
                  stroke="#141414"
                  strokeWidth="1.5"
                  strokeLinecap="square"
                />
 
                {/* TX Upload Fill */}
                <path
                  d={`M 0,100 L ${trafficHistory.map((pt, i) => `${(i / (trafficHistory.length - 1)) * 300},${100 - (pt.tx / 50) * 100}`).join(' L ')} L 300,100 Z`}
                  fill="url(#txGrad)"
                />
              </svg>
              <div className="absolute top-1 text-[11px] font-mono opacity-50">100 MBPS (BANDWIDTH_CAP)</div>
              <div className="absolute bottom-1 right-1 text-[11px] font-mono opacity-50">SYNC RATE: 2500MS_POLL</div>
            </div>
          </div>
 
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 bg-[#f0efec] p-3 rounded-none border border-[#141414] mt-4 font-mono text-[11px]">
            <div className="text-center sm:text-left">
              <span className="opacity-50 block">ADDRESS_POOL</span>
              <span className="font-bold">192.168.88.100/24</span>
            </div>
            <div className="text-center sm:text-left sm:border-l border-[#141414]/20 sm:pl-3">
              <span className="opacity-50 block">ACTIVE_ARP_LEASES</span>
              <span className="font-bold">{activeSubs.length + activeVouchers.length} LEASES</span>
            </div>
            <div className="text-center sm:text-left sm:border-l border-[#141414]/20 sm:pl-3">
              <span className="opacity-50 block">LIMIT_QUEUES</span>
              <span className="font-bold">{subscribers.length} TARGETS</span>
            </div>
            <div className="text-center sm:text-left sm:border-l border-[#141414]/20 sm:pl-3">
              <span className="opacity-50 block">HOTSPOT_PROFILE</span>
              <span className="font-bold">ros_hspot_cluster</span>
            </div>
          </div>
        </div>
 
        {/* Sidebar Packages / Plan Capping list & quick voucher overview */}
        <div className="border border-[#141414] bg-[#141414] text-[#E4E3E0] p-4 rounded-none font-mono flex flex-col justify-between">
          <div>
            <div className="flex justify-between items-center mb-4 italic font-serif uppercase text-xs">
              <span>BANDWIDTH_DISTRIBUTION</span>
              <button 
                onClick={() => onNavigate('plans')} 
                className="hover:underline opacity-80 cursor-pointer"
              >
                [PLAN_EDIT]
              </button>
            </div>
            
            <div className="space-y-3">
              {profileBreakdown.map((item, index) => (
                <div key={index} className="flex items-center justify-between border-b border-[#E4E3E0]/15 pb-2 last:border-o">
                  <div>
                    <div className="text-xs font-bold text-white tracking-widest uppercase">
                      {item.name}
                    </div>
                    <div className="text-[10px] opacity-60 mt-0.5">
                      SUBS: {item.subs} | VOUCHERS: {item.vouchs}
                    </div>
                  </div>
                  <div className="text-right">
                    <span className="text-[11px] font-bold text-white">
                      Ksh {item.revenue.toLocaleString()}
                    </span>
                    <span className="text-[10px] opacity-50 block">KES</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
 
          <button 
            onClick={() => onNavigate('hotspot')} 
            className="w-full mt-4 py-2 border border-white hover:bg-white hover:text-[#141414] uppercase font-bold text-xs transition-colors cursor-pointer"
          >
            PRINTABLE_VOUCHERS_GRID
          </button>
        </div>
      </div>
 
      {/* Audit Log / Real-time Terminal Events & Actions */}
      <div className="border border-[#141414] bg-white p-4 rounded-none">
        <div className="flex items-center justify-between border-b border-[#141414]/20 pb-3 mb-4">
          <div>
            <h3 className="text-sm font-serif italic font-bold uppercase tracking-tight text-[#141414]">
              AUTO-INVOICE & AUDIT LOGS
            </h3>
            <p className="text-xs text-[#141414]/70 font-mono mt-0.5">
              Live streaming transaction feeds from MikroTik ROS API interface layer.
            </p>
          </div>
          <button 
            onClick={() => onNavigate('mikrotik')}
            className="text-xs font-mono font-bold text-[#141414] hover:underline"
          >
            [ACCESS_MIKROTIK_CONSOLE]
          </button>
        </div>
 
        <div className="space-y-2.5 max-h-56 overflow-y-auto pr-1">
          {logs.slice().reverse().map((log) => (
            <div key={log.id} className="flex text-xs items-start border-b border-[#141414]/5 pb-2 last:border-0 last:pb-0 font-mono gap-3">
              <span className="opacity-50 shrink-0">[{log.timestamp.split(' ')[1] || log.timestamp}]</span>
              
              <span className={`px-1.5 py-0.2 border shrink-0 text-[10px] font-bold uppercase ${
                log.category === 'Router' ? 'bg-[#f0efec] text-[#141414] border-[#141414]/30' :
                log.category === 'Billing' ? 'bg-[#E4E3E0] text-[#141414] border-[#141414]' :
                log.category === 'Subscriber' ? 'bg-zinc-100 text-[#141414] border-zinc-400' :
                'bg-emerald-50 text-[#228B22] border-[#228B22]/40'
              }`}>
                {log.category}
              </span>
 
              <div className="flex-1 text-[#141414] truncate">
                {log.type === 'error' && <span className="text-[#FF4500] font-bold mr-1">[FAILURE]</span>}
                {log.type === 'warning' && <span className="text-[#FF4500] mr-1">[WARN]</span>}
                {log.message}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// Extra helper icon because of name matching 
function ArrowRightCircle(props: React.SVGProps<SVGSVGElement>) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      width="24"
      height="24"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeJoin="round"
      className={props.className}
      {...props}
    >
      <circle cx="12" cy="12" r="10" />
      <path d="M12 16l4-4-4-4" />
      <path d="M8 12h8" />
    </svg>
  );
}
