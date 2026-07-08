import React, { useState } from 'react';
import { HotspotVoucher, BandwidthProfile } from '../types';
import { 
  Tag, 
  Plus, 
  Printer, 
  Check, 
  Radio, 
  Shuffle, 
  FileText, 
  Key, 
  CircleDot,
  CheckCircle2,
  Trash2,
  QrCode,
  Wifi,
  Ticket,
  ChevronDown,
  Activity,
  UserCheck
} from 'lucide-react';
import { generateVoucherCode } from '../utils/billingEngine';

interface HotspotBillingViewProps {
  vouchers: HotspotVoucher[];
  profiles: BandwidthProfile[];
  onGenerateVouchers: (profileId: string, count: number, prefix: string) => void;
  onClearExpiredVouchers: () => void;
  onUseVoucher: (code: string, mac: string) => void;
  onDeleteVoucher: (id: string) => void;
  onAddLog: (category: 'Router' | 'Billing' | 'Subscriber' | 'Hotspot', type: 'info' | 'success' | 'warning' | 'error', message: string) => void;
}

export default function HotspotBillingView({
  vouchers,
  profiles,
  onGenerateVouchers,
  onClearExpiredVouchers,
  onUseVoucher,
  onDeleteVoucher,
  onAddLog
}: HotspotBillingViewProps) {
  // Bulk Generator State
  const [profileId, setProfileId] = useState(profiles[0]?.id || '');
  const [count, setCount] = useState(10);
  const [prefix, setPrefix] = useState('WF-');
  const [filterProfile, setFilterProfile] = useState<string>('all');
  const [filterStatus, setFilterStatus] = useState<'all' | 'Unused' | 'Active' | 'Expired'>('all');
  const [selectedVoucherIds, setSelectedVoucherIds] = useState<string[]>([]);

  // Hotspot Login Simulator State
  const [simCode, setSimCode] = useState('');
  const [simMac, setSimMac] = useState('02:FE:55:BC:3A:91');
  const [simulationResult, setSimulationResult] = useState<{success: boolean; text: string} | null>(null);

  const handleGenerate = (e: React.FormEvent) => {
    e.preventDefault();
    if (!profileId) {
      alert('Please select a bandwidth package.');
      return;
    }
    const selectedProfile = profiles.find(p => p.id === profileId);
    
    onGenerateVouchers(profileId, count, prefix);
    onAddLog(
      'Hotspot',
      'success',
      `Hotspot Engine: Bulk generated ${count} unused vouchers with profile '${selectedProfile?.name}' (Prefix: "${prefix}").`
    );
    onAddLog(
      'Router',
      'info',
      `MikroTik sync: Registered ${count} hotspot user credentials for profile: ${selectedProfile?.name}.`
    );
  };

  const handleSimulationSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!simCode) {
      setSimulationResult({ success: false, text: 'Please enter or click a voucher code.' });
      return;
    }

    const found = vouchers.find(v => v.code.toUpperCase() === simCode.toUpperCase());
    if (!found) {
      setSimulationResult({ success: false, text: 'Voucher code not found in database.' });
      return;
    }

    if (found.status === 'Active') {
      setSimulationResult({ success: false, text: 'Voucher already in active use.' });
      return;
    }

    if (found.status === 'Expired') {
      setSimulationResult({ success: false, text: 'Voucher has already expired.' });
      return;
    }

    // Trigger activation
    onUseVoucher(found.code, simMac);
    
    // Success log
    const profile = profiles.find(p => p.id === found.profileId);
    setSimulationResult({ 
      success: true, 
      text: `Voucher authenticated! Client MAC registered. Speed caps applied: ${profile?.downloadSpeed} Down / ${profile?.uploadSpeed} Up.` 
    });
    
    onAddLog(
      'Hotspot',
      'success',
      `Hotspot Session: Interactive Login Success. Code ${found.code} bound to MAC ${simMac}.`
    );

    onAddLog(
      'Router',
      'info',
      `MikroTik Hotspot Server: Added active IP host binding for MAC: ${simMac} under speed Profile: ${profile?.name}.`
    );

    // reset simulation after a while
    setTimeout(() => {
      setSimCode('');
    }, 4500);
  };

  // Filter vouchers list
  const filteredVouchers = vouchers.filter(v => {
    const matchesProfile = filterProfile === 'all' || v.profileId === filterProfile;
    const matchesStatus = filterStatus === 'all' || v.status === filterStatus;
    return matchesProfile && matchesStatus;
  });

  // Calculate stats
  const totalEarnedHotspot = vouchers
    .filter(v => v.status === 'Active' || v.status === 'Expired')
    .reduce((sum, v) => sum + v.price, 0);

  return (
    <div className="space-y-6 animate-fade-in text-[#141414]">
      
      {/* Cards Header */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        
        {/* Bulk Generator Console */}
        <div className="lg:col-span-2 bg-white border border-[#141414] p-4 rounded-none">
          <div className="flex items-center gap-2 border-b border-[#141414]/20 pb-3 mb-4">
            <Ticket className="h-4 w-4" />
            <div>
              <h3 className="text-sm font-serif italic font-bold uppercase tracking-tight text-[#141414]">
                Bulk Coupon Code Cryptographic Generator
              </h3>
              <p className="text-xs text-[#141414]/70 font-mono">
                Instantly batch-compile and register wireless hotspot tokens to the active MikroTik queue array.
              </p>
            </div>
          </div>
 
          <form onSubmit={handleGenerate} className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {/* Package */}
            <div className="space-y-1">
              <label className="text-[11px] font-mono font-bold uppercase text-[#141414]/70">WIFI_SPEED_PROFILE</label>
              <select
                value={profileId}
                onChange={(e) => setProfileId(e.target.value)}
                className="w-full bg-white border border-[#141414] p-2 text-xs font-mono rounded-none outline-none text-[#141414]"
              >
                {profiles.map(p => (
                  <option key={p.id} value={p.id}>{p.name} (Ksh {p.price.toLocaleString()})</option>
                ))}
              </select>
            </div>
 
            {/* Print count */}
            <div className="space-y-1">
              <label className="text-[11px] font-mono font-bold uppercase text-[#141414]/70">BATCH_SIZE_COUNT</label>
              <select
                value={count}
                onChange={(e) => setCount(Number(e.target.value))}
                className="w-full bg-white border border-[#141414] p-2 text-xs font-mono rounded-none outline-none text-[#141414]"
              >
                <option value="5">5 Tickets</option>
                <option value="10">10 Tickets</option>
                <option value="20">20 Tickets</option>
                <option value="50">50 Tickets</option>
              </select>
            </div>
 
            {/* Custom Prefix */}
            <div className="space-y-1">
              <label className="text-[11px] font-mono font-bold uppercase text-[#141414]/70">TICKET_CODE_PREFIX</label>
              <div className="flex gap-2">
                <input
                  type="text"
                  placeholder="e.g. WF-"
                  value={prefix}
                  onChange={(e) => setPrefix(e.target.value.toUpperCase())}
                  className="w-full bg-white border border-[#141414] p-1.5 text-xs font-mono rounded-none outline-none text-[#141414]"
                />
                <button
                  type="submit"
                  id="btn-trigger-generation"
                  className="bg-[#141414] text-white hover:bg-[#E4E3E0] hover:text-[#141414] border border-[#141414] px-4 py-1.5 text-xs font-mono font-bold tracking-wider uppercase rounded-none transition cursor-pointer shrink-0"
                >
                  COMPILE
                </button>
              </div>
            </div>
          </form>
        </div>
 
        {/* Hotspot Authorization Simulator Panel */}
        <div className="bg-white border border-[#141414] p-4 rounded-none flex flex-col justify-between">
          <div>
            <div className="flex items-center gap-1.5 border-b border-[#141414]/20 pb-3 mb-3">
              <UserCheck className="h-4 w-4 text-[#228B22] animate-pulse" />
              <div>
                <h3 className="text-xs font-bold text-[#141414] uppercase font-mono tracking-wider">
                  HOTSPOT CAPTIVE SIMULATOR
                </h3>
                <span className="text-[11px] text-[#141414]/60 block font-mono">Simulate customer captive portal validation sequence</span>
              </div>
            </div>
 
            <form onSubmit={handleSimulationSubmit} className="space-y-2">
              <div className="grid grid-cols-2 gap-2 font-mono">
                <div>
                  <label className="text-[10px] font-bold text-[#141414]/75 uppercase block">COUPON_CODE</label>
                  <input
                    type="text"
                    placeholder="W-CODE"
                    value={simCode}
                    onChange={(e) => setSimCode(e.target.value)}
                    className="w-full bg-white border border-[#141414] p-1.5 text-xs rounded-none outline-none text-[#141414]"
                  />
                </div>
                <div>
                  <label className="text-[10px] font-bold text-[#141414]/75 uppercase block">CLIENT_MAC_ADDR</label>
                  <input
                    type="text"
                    value={simMac}
                    onChange={(e) => setSimMac(e.target.value)}
                    className="w-full bg-white border border-[#141414] p-1.5 text-xs rounded-none outline-none text-[#141414]"
                  />
                </div>
              </div>
 
              <button
                type="submit"
                className="w-full bg-[#141414] text-white hover:bg-white hover:text-[#141414] border border-[#141414] text-xs py-1.5 font-mono font-bold uppercase rounded-none transition"
              >
                AUTHORIZE_SESSION
              </button>
            </form>
          </div>
 
          <div className="mt-2.5">
            {simulationResult ? (
              <div className={`p-2 border text-[11px] leading-relaxed font-mono ${simulationResult.success ? 'bg-[#228B22]/10 text-[#228B22] border-[#228B22]/30' : 'bg-[#FF4500]/10 text-[#FF4500] border-[#FF4500]/30'}`}>
                {simulationResult.text}
              </div>
            ) : (
              <div className="bg-[#f0efec] border border-[#141414]/15 p-2 rounded-none text-[10px] font-mono text-[#141414]/60 text-center uppercase">
                * Click any coupon card in directory grid to auto-load code
              </div>
            )}
          </div>
        </div>
      </div>
 
      {/* Filter and Print Settings */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between bg-white border border-[#141414] p-3 rounded-none gap-3 font-mono text-[11px]">
        <div className="flex flex-wrap items-center gap-3">
          {/* Filter package */}
          <div className="flex items-center gap-1.5">
            <span className="text-[#141414]/60 uppercase font-bold">PROFILE:</span>
            <select
              value={filterProfile}
              onChange={(e) => setFilterProfile(e.target.value)}
              className="bg-white border border-[#141414]/30 p-1 rounded-none outline-none text-[#141414]"
            >
              <option value="all">ALL_PROFILES</option>
              {profiles.map(p => (
                <option key={p.id} value={p.id}>{p.name.toUpperCase()}</option>
              ))}
            </select>
          </div>
 
          {/* Filter Status */}
          <div className="flex items-center gap-1.5">
            <span className="text-[#141414]/60 uppercase font-bold">STATE:</span>
            <select
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value as any)}
              className="bg-white border border-[#141414]/30 p-1 rounded-none outline-none text-[#141414]"
            >
              <option value="all">ALL_STATES</option>
              <option value="Unused">UNUSED_TICKETS</option>
              <option value="Active">ACTIVE_CLIENTS</option>
              <option value="Expired">EXPIRED_REDEEM</option>
            </select>
          </div>
        </div>
 
        <div className="flex items-center gap-2">
          {/* Clear expired */}
          <button
            onClick={onClearExpiredVouchers}
            className="px-2 py-1 border border-[#141414]/30 hover:border-[#FF4500] hover:text-[#FF4500] rounded-none font-bold uppercase transition scale-98 active:scale-95 cursor-pointer"
          >
            purge_expired
          </button>
          
          {/* Global print list trigger */}
          <button
            onClick={() => window.print()}
            className="bg-[#141414] hover:bg-white hover:text-[#141414] text-white border border-[#141414] px-3 py-1.5 font-bold uppercase rounded-none transition inline-flex items-center gap-1.5 cursor-pointer"
          >
            <Printer className="h-3 w-3" />
            PRINT_COUPONS_HTML
          </button>
        </div>
      </div>
 
      {/* Batch Voucher actions panel */}
      {selectedVoucherIds.length > 0 && (
        <div className="bg-[#E4E3E0] border border-[#141414] p-3 text-xs font-mono flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 animate-fade-in text-[#141414]">
          <div className="flex items-center gap-2">
            <span className="bg-[#141414] text-white px-2 py-0.5 text-[11px] font-bold uppercase">Batch Action</span>
            <span className="font-bold">{selectedVoucherIds.length} WiFi voucher(s) selected</span>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => {
                if (confirm(`Are you sure you want to delete ${selectedVoucherIds.length} selected vouchers?`)) {
                  selectedVoucherIds.forEach(id => onDeleteVoucher(id));
                  onAddLog('Hotspot', 'warning', `Batch Action: Bulk deleted ${selectedVoucherIds.length} hotspot vouchers.`);
                  setSelectedVoucherIds([]);
                }
              }}
              className="bg-[#FF4500] text-white border border-[#FF4500] px-3 py-1 text-[11px] font-bold uppercase transition hover:bg-white hover:text-[#FF4500] cursor-pointer"
            >
              Batch Delete [PURGE]
            </button>
            <button
              onClick={() => {
                const printWindow = window.open('', '_blank');
                if (printWindow) {
                  const itemsToPrint = vouchers.filter(v => selectedVoucherIds.includes(v.id));
                  let htmlString = `
                    <html>
                    <head>
                      <title>Print Selected Hotspot Coupons</title>
                      <style>
                        body { font-family: monospace; background: white; color: black; padding: 20px; }
                        .grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; }
                        .card { border: 2px dashed black; padding: 15px; text-align: center; }
                        .code { font-size: 18px; font-weight: bold; margin: 10px 0; letter-spacing: 1px; }
                        .price { font-weight: bold; }
                      </style>
                    </head>
                    <body>
                      <h2>WIFI.OS â€” HOTSPOT PRINT SHEET</h2>
                      <div class="grid">
                  `;
                  itemsToPrint.forEach(item => {
                    const planInfo = profiles.find(p => p.id === item.profileId);
                    htmlString += `
                      <div class="card">
                        <div><b>${planInfo ? planInfo.name.toUpperCase() : 'WIFI ACCESS'}</b></div>
                        <div>SSID: WIFI_INTERNET_OS</div>
                        <div class="code">${item.code}</div>
                        <div>VALIDITY: ${planInfo ? planInfo.validityLabel : '1 Hour'}</div>
                        <div class="price">PRICE: Ksh ${item.price}</div>
                        <div style="font-size: 9px; opacity: 0.7; margin-top: 5px;">* Enter code on captivity portal login screen *</div>
                      </div>
                    `;
                  });
                  htmlString += '</div></body></html>';
                  printWindow.document.write(htmlString);
                  printWindow.document.close();
                  printWindow.print();
                } else {
                  alert("Popup blocker prevented ticket printing layout tab.");
                }
              }}
              className="bg-[#141414] text-white border border-[#141414] px-3 py-1 text-[11px] font-bold uppercase transition hover:bg-white hover:text-[#141414] cursor-pointer"
            >
              Batch Print [TICKETS]
            </button>
            <button
              onClick={() => {
                selectedVoucherIds.forEach(id => {
                  const vouch = vouchers.find(v => v.id === id);
                  if (vouch && vouch.status === 'Unused') {
                    onUseVoucher(vouch.code, '02:FE:55:BC:3A:91');
                  }
                });
                onAddLog('Hotspot', 'success', `Batch Activate: Simulated portal login for ${selectedVoucherIds.length} vouchers under MAC 02:FE:55:BC:3A:91.`);
                setSelectedVoucherIds([]);
              }}
              className="bg-[#228B22] text-white border border-[#228B22] px-3 py-1 text-[11px] font-bold uppercase transition hover:bg-white hover:text-[#228B22] cursor-pointer"
            >
              Simulate Active Use
            </button>
            <button
              onClick={() => setSelectedVoucherIds([])}
              className="text-[#141414]/60 hover:text-[#141414] px-2 text-[11px] font-bold uppercase cursor-pointer"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
 
      {/* Grid of Printable Voucher Cards */}
      <div id="section-printable-vouchers" className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-4">
        {filteredVouchers.map((vouch) => {
          const plan = profiles.find(p => p.id === vouch.profileId);
          const isVouchSelected = selectedVoucherIds.includes(vouch.id);
          return (
            <div 
              key={vouch.id} 
              className={`bg-white border p-4 flex flex-col justify-between relative rounded-none transition group overflow-hidden ${
                isVouchSelected ? 'border-[#141414] ring-2 ring-[#141414] h-52' :
                vouch.status === 'Unused' ? 'border-dashed border-[#141414]/60 hover:border-[#141414] h-52' :
                vouch.status === 'Active' ? 'border-[#228B22] bg-[#f2f8f2] h-52' :
                'border-[#141414]/15 opacity-60 h-52'
              }`}
            >
              {/* Checkbox for batch selection */}
              <div className="absolute top-1.5 left-2 z-10">
                <input
                  type="checkbox"
                  checked={isVouchSelected}
                  onChange={(e) => {
                    if (e.target.checked) {
                      setSelectedVoucherIds(prev => [...prev, vouch.id]);
                    } else {
                      setSelectedVoucherIds(prev => prev.filter(id => id !== vouch.id));
                    }
                  }}
                  className="cursor-pointer h-3 w-3 accent-[#141414] block"
                />
              </div>

              {/* Card top details */}
              <div className="flex items-start justify-between pl-4">
                <div>
                  <span className="text-[10px] bg-[#E4E3E0] text-[#141414] border border-[#141414]/25 px-1.5 py-0.5 rounded-none font-bold uppercase tracking-wider font-mono">
                    {plan?.validityLabel || 'GENERIC'} VALIDITY
                  </span>
                  
                  <h4 className="text-xs font-serif italic font-bold text-[#141414] mt-1 tracking-tight">
                    {plan?.name || 'WiFi Ticket'}
                  </h4>
                </div>
 
                <div className="text-right">
                  <div className="text-xs font-bold text-[#228B22] font-mono bg-white border border-[#228B22]/30 px-1.5 py-0.2 rounded-none">
                    Ksh {vouch.price}
                  </div>
                </div>
              </div>
 
              {/* Code display central */}
              <div className="my-3 text-center bg-[#f0efec] p-2.5 rounded-none border border-[#141414]/25 relative">
                <span className="text-[10px] text-[#141414]/60 block font-mono uppercase tracking-widest font-bold">ACCESS PORTAL CODE</span>
                <span className="text-sm font-bold font-mono tracking-wider text-[#141414] block mt-0.5">
                  {vouch.code}
                </span>
 
                {/* Quick copy/simulate click */}
                {vouch.status === 'Unused' && (
                  <button
                    onClick={() => {
                      setSimCode(vouch.code);
                      onAddLog('Hotspot', 'info', `Captured coupon code ${vouch.code} inside capt portal buffer.`);
                    }}
                    className="absolute inset-x-0 inset-y-0 w-full h-full opacity-0 cursor-pointer"
                    title="Click to mount in portal simulation"
                  />
                )}
              </div>
 
              {/* Card footer details / Mock QR codes & limits */}
              <div className="flex items-center justify-between border-t border-[#141414]/15 pt-2 text-[11px] font-mono">
                <div className="space-y-0.2 select-none">
                  <div className="text-[#141414]/65">SSID: <span className="font-bold text-[#141414]">WIFI_INTERNET_OS</span></div>
                  <div className="text-[#141414]/65">LIMIT: <span className="text-[#FF4500] font-bold">{plan?.downloadSpeed} UP</span></div>
                </div>
 
                {/* Mock QR image using simple absolute boxes */}
                <div className="bg-white p-0.5 border border-[#141414]/40 select-none">
                  <div className="grid grid-cols-3 gap-0.5 h-5 w-5">
                    <div className="bg-[#141414]"></div>
                    <div className="bg-[#141414]"></div>
                    <div className="bg-transparent"></div>
                    <div className="bg-[#141414]"></div>
                    <div className="bg-transparent"></div>
                    <div className="bg-[#141414]"></div>
                    <div className="bg-[#141414]"></div>
                    <div className="bg-[#141414]"></div>
                    <div className="bg-[#141414]"></div>
                  </div>
                </div>
              </div>
 
              {/* Status Ribbon banner of the card */}
              <div className="mt-2.5 flex items-center justify-between border-t border-[#141414]/10 pt-1 text-[10px] font-mono">
                <span className={`inline-block font-bold uppercase ${
                  vouch.status === 'Unused' ? 'text-[#141414]/55' :
                  vouch.status === 'Active' ? 'text-[#228B22] animate-pulse font-extrabold' :
                  'text-[#FF4500]'
                }`}>
                  â–  {vouch.status.toUpperCase()}
                </span>
 
                <div className="flex items-center gap-1.5 opacity-0 group-hover:opacity-100 transition">
                  <button
                    onClick={() => {
                      if (confirm(`Delete coupon code ${vouch.code}?`)) {
                        onDeleteVoucher(vouch.id);
                        onAddLog('Hotspot', 'warning', `Hotspot voucher code ${vouch.code} removed manually.`);
                      }
                    }}
                    className="text-[#FF4500] hover:bg-[#FF4500]/10 border border-[#FF4500]/30 rounded-none p-0.5 transition cursor-pointer"
                    title="Delete Coupon"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
 
              {vouch.status === 'Active' && vouch.usedByMac && (
                <div className="absolute top-0 right-0 bg-[#228B22] text-white font-mono text-[10px] px-1.5 py-0.5 rounded-none font-bold">
                  {vouch.usedByMac.substring(0, 8).toUpperCase()}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
