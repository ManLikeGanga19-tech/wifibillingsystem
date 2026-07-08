import React, { useState } from 'react';
import { Subscriber, BandwidthProfile, SystemLog } from '../types';
import { 
  Users, 
  Plus, 
  Search, 
  Trash2, 
  Edit3, 
  X, 
  Check, 
  AlertCircle, 
  CheckCircle,
  ToggleLeft,
  ToggleRight,
  ShieldAlert,
  Router,
  Flame,
  Info,
  ExternalLink,
  Smartphone,
  Mail,
  Locate
} from 'lucide-react';

interface SubscriberManagerProps {
  subscribers: Subscriber[];
  profiles: BandwidthProfile[];
  onAddSubscriber: (newSub: Omit<Subscriber, 'id' | 'createdAt'>) => void;
  onUpdateSubscriber: (updatedSub: Subscriber) => void;
  onDeleteSubscriber: (id: string) => void;
  onTriggerManualInvoice: (sub: Subscriber) => void;
  onAddLog: (category: 'Router' | 'Billing' | 'Subscriber' | 'Hotspot', type: 'info' | 'success' | 'warning' | 'error', message: string) => void;
}

export default function SubscriberManager({
  subscribers,
  profiles,
  onAddSubscriber,
  onUpdateSubscriber,
  onDeleteSubscriber,
  onTriggerManualInvoice,
  onAddLog
}: SubscriberManagerProps) {
  const [searchQuery, setSearchQuery] = useState('');
  const [filterType, setFilterType] = useState<'all' | 'Daily' | 'Monthly'>('all');
  const [filterStatus, setFilterStatus] = useState<'all' | 'Active' | 'Expired' | 'Suspended'>('all');
  const [selectedSubIds, setSelectedSubIds] = useState<string[]>([]);
  
  // Modal visibility
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [editingSub, setEditingSub] = useState<Subscriber | null>(null);
  
  // Add Form State Variables
  const [name, setName] = useState('');
  const [phone, setPhone] = useState('');
  const [email, setEmail] = useState('');
  const [address, setAddress] = useState('');
  const [ipAddress, setIpAddress] = useState('192.168.88.');
  const [macAddress, setMacAddress] = useState('');
  const [planId, setPlanId] = useState(profiles[3]?.id || '');
  const [billingType, setBillingType] = useState<'Daily' | 'Monthly'>('Monthly');
  const [autoInvoice, setAutoInvoice] = useState(true);
  const [nextBillingDate, setNextBillingDate] = useState(new Date().toISOString().substring(0, 10));

  // Reset form helper
  const resetForm = () => {
    setName('');
    setPhone('');
    setEmail('');
    setAddress('');
    setIpAddress('192.168.88.');
    setMacAddress('');
    setPlanId(profiles[3]?.id || '');
    setBillingType('Monthly');
    setAutoInvoice(true);
    setNextBillingDate(new Date().toISOString().substring(0, 10));
  };

  const handleAddSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name || !ipAddress) {
      alert('Name and IP Address are mandatory fields.');
      return;
    }
    
    onAddSubscriber({
      name,
      phone,
      email,
      address,
      ipAddress,
      macAddress: macAddress.toUpperCase() || undefined,
      planId,
      status: 'Active',
      billingType,
      nextBillingDate,
      autoInvoice,
      balance: 0
    });
    
    onAddLog(
      'Subscriber', 
      'success', 
      `Customer account created: ${name} (IP: ${ipAddress}) on automated ${billingType} cycle.`
    );
    
    // Simulating MikroTik dynamic push
    const activePlan = profiles.find(p => p.id === planId);
    onAddLog(
      'Router',
      'info',
      `MikroTik sync: Added static IP lease for client MAC: ${macAddress || 'Dynamic'} and bound queue limit-at=${activePlan?.downloadSpeed}`
    );

    setIsAddOpen(false);
    resetForm();
  };

  const handleEditSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingSub) return;

    onUpdateSubscriber(editingSub);
    onAddLog(
      'Subscriber',
      'info',
      `Updated user profile details for account ${editingSub.name}.`
    );

    const oldSub = subscribers.find(s => s.id === editingSub.id);
    if (oldSub?.planId !== editingSub.planId) {
      const activePlan = profiles.find(p => p.id === editingSub.planId);
      onAddLog(
        'Router',
        'success',
        `MikroTik Queue Updated: Reconfigured download limit for ${editingSub.name} to ${activePlan?.downloadSpeed}.`
      );
    }

    setEditingSub(null);
  };

  // Change Subscriber Status helper
  const handleToggleStatus = (sub: Subscriber, currentStatus: string) => {
    let nextStatus: 'Active' | 'Expired' | 'Suspended';
    if (currentStatus === 'Active') {
      nextStatus = 'Suspended';
    } else {
      nextStatus = 'Active';
    }

    const updated = { ...sub, status: nextStatus };
    onUpdateSubscriber(updated);

    if (nextStatus === 'Suspended') {
      onAddLog(
        'Router',
        'warning',
        `MikroTik firewall dropped forward rule src-address=${sub.ipAddress} action=drop. subscriber suspended.`
      );
      onAddLog(
        'Subscriber',
        'warning',
        `Account has been put under SUSPENDED list: ${sub.name}`
      );
    } else {
      onAddLog(
        'Router',
        'success',
        `MikroTik firewall bypassed drop rule for src-address=${sub.ipAddress}. subscriber unsuspended.`
      );
      onAddLog(
        'Subscriber',
        'success',
        `Account has been restored: ${sub.name}`
      );
    }
  };

  // Filters logic
  const filteredSubscribers = subscribers.filter(sub => {
    const matchesSearch = 
      sub.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      sub.phone.includes(searchQuery) ||
      sub.email.toLowerCase().includes(searchQuery.toLowerCase()) ||
      sub.ipAddress.includes(searchQuery);

    const matchesType = filterType === 'all' || sub.billingType === filterType;
    const matchesStatus = filterStatus === 'all' || sub.status === filterStatus;

    return matchesSearch && matchesType && matchesStatus;
  });

  return (
    <div className="space-y-6 animate-fade-in">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between border-b border-[#141414] pb-4 gap-4">
        <div>
          <h2 className="text-lg font-serif italic font-bold uppercase tracking-tight text-[#141414] flex items-center gap-2">
            <Users className="h-4 w-4" />
            <span>Subscriber Accounts Directory</span>
          </h2>
          <p className="text-xs text-[#141414]/70 font-mono mt-0.5">
            Manage your daily and monthly active connections. Limit queues automatically sync to local interfaces.
          </p>
        </div>
        
        <button
          type="button"
          id="btn-add-sub"
          onClick={() => setIsAddOpen(true)}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-mono tracking-widest uppercase font-bold text-white bg-[#141414] hover:bg-white hover:text-[#141414] border border-[#141414] rounded-none transition-colors cursor-pointer self-start"
        >
          <Plus className="h-3.5 w-3.5" />
          ADD_FIBER_SUBSCRIBER
        </button>
      </div>

      {/* Filter and Search Bar */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3 bg-white border border-[#141414] p-3 rounded-none">
        {/* Search */}
        <div className="flex items-center gap-2 px-2.5 border border-[#141414]/30 bg-white rounded-none">
          <Search className="h-3.5 w-3.5 text-[#141414]/40" />
          <input
            type="text"
            placeholder="Search matching accounts..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-transparent outline-none py-1.5 text-xs text-[#141414] placeholder-[#141414]/40 font-mono"
          />
        </div>

        {/* Filter Billing type */}
        <div className="flex items-center gap-2">
          <label className="text-xs font-mono text-[#141414]/60 uppercase shrink-0">CYCLE:</label>
          <select
            value={filterType}
            onChange={(e) => setFilterType(e.target.value as any)}
            className="w-full bg-white border border-[#141414]/30 p-1.5 text-xs font-mono text-[#141414] rounded-none outline-none"
          >
            <option value="all">ALL_PERIODS</option>
            <option value="Daily">DAILY_Validity</option>
            <option value="Monthly">MONTHLY_Validity</option>
          </select>
        </div>

        {/* Filter Status */}
        <div className="flex items-center gap-2">
          <label className="text-xs font-mono text-[#141414]/60 uppercase shrink-0">STATUS:</label>
          <select
            value={filterStatus}
            onChange={(e) => setFilterStatus(e.target.value as any)}
            className="w-full bg-white border border-[#141414]/30 p-1.5 text-xs font-mono text-[#141414] rounded-none outline-none"
          >
            <option value="all">ALL_STATUSES</option>
            <option value="Active">ACTIVE_CLIENTS</option>
            <option value="Expired">EXPIRED_RENEWAL</option>
            <option value="Suspended">FIREWALL_SUSPEND</option>
          </select>
        </div>

        {/* Metrics Counter */}
        <div className="flex items-center justify-end text-right font-mono text-xs text-[#141414]/55">
          QUERIED {filteredSubscribers.length} OF {subscribers.length} ACCOUNTS
        </div>
      </div>

      {/* Batch Action Panel */}
      {selectedSubIds.length > 0 && (
        <div className="bg-[#E4E3E0] border border-[#141414] p-3 text-xs font-mono flex flex-col md:flex-row items-start md:items-center justify-between gap-3 animate-fade-in">
          <div className="flex items-center gap-2">
            <span className="bg-[#141414] text-white px-2 py-0.5 text-[11px] font-bold uppercase">Batch Action</span>
            <span className="font-bold text-[#141414]">{selectedSubIds.length} subscriber(s) selected</span>
          </div>
          
          <div className="flex flex-wrap items-center gap-2">
            <button
              onClick={() => {
                selectedSubIds.forEach(id => {
                  const sub = subscribers.find(s => s.id === id);
                  if (sub && sub.status !== 'Active') {
                    onUpdateSubscriber({ ...sub, status: 'Active' });
                  }
                });
                onAddLog('Subscriber', 'success', `Batch Action: Activated status for ${selectedSubIds.length} subscribers.`);
                setSelectedSubIds([]);
              }}
              className="bg-[#228B22] text-white border border-[#228B22] px-2.5 py-1 text-[11px] font-bold uppercase transition hover:bg-white hover:text-[#228B22] cursor-pointer"
            >
              Batch Activate [ALLOW]
            </button>
            <button
              onClick={() => {
                selectedSubIds.forEach(id => {
                  const sub = subscribers.find(s => s.id === id);
                  if (sub && sub.status !== 'Suspended') {
                    onUpdateSubscriber({ ...sub, status: 'Suspended' });
                  }
                });
                onAddLog('Subscriber', 'warning', `Batch Action: Suspended traffic for ${selectedSubIds.length} subscribers.`);
                setSelectedSubIds([]);
              }}
              className="bg-[#FF4500] text-white border border-[#FF4500] px-2.5 py-1 text-[11px] font-bold uppercase transition hover:bg-white hover:text-[#FF4500] cursor-pointer"
            >
              Batch Suspend [BLOCK]
            </button>
            
            <div className="flex items-center gap-1 border border-[#141414]/30 bg-white px-1 py-0.5">
              <span className="text-[10px] uppercase font-bold text-[#141414]/60 px-1">PLAN:</span>
              <select
                onChange={(e) => {
                  const newPlanId = e.target.value;
                  if (!newPlanId) return;
                  const targetPlan = profiles.find(p => p.id === newPlanId);
                  
                  selectedSubIds.forEach(id => {
                    const sub = subscribers.find(s => s.id === id);
                    if (sub) {
                      onUpdateSubscriber({ ...sub, planId: newPlanId });
                    }
                  });
                  onAddLog('Router', 'success', `Batch Sync: Changed plan speed configs for ${selectedSubIds.length} subscribers to "${targetPlan?.name}".`);
                  setSelectedSubIds([]);
                }}
                className="bg-transparent text-[11px] font-mono border-0 outline-none pr-1 py-0.5 cursor-pointer max-w-[120px]"
                defaultValue=""
              >
                <option value="" disabled>Change Plan...</option>
                {profiles.map(p => (
                  <option key={p.id} value={p.id}>{p.name} (Ksh {p.price})</option>
                ))}
              </select>
            </div>

            <button
              onClick={() => {
                selectedSubIds.forEach(id => {
                  const sub = subscribers.find(s => s.id === id);
                  if (sub) {
                    onTriggerManualInvoice(sub);
                  }
                });
                onAddLog('Billing', 'success', `Batch Bill: Generated manual outstanding invoices for ${selectedSubIds.length} subscribers.`);
                setSelectedSubIds([]);
              }}
              className="bg-white text-[#141414] border border-[#141414] px-2.5 py-1 text-[11px] font-bold uppercase transition hover:bg-[#141414] hover:text-white cursor-pointer"
            >
              Batch Bill [INVOICE]
            </button>

            <button
              onClick={() => setSelectedSubIds([])}
              className="text-[#141414]/60 hover:text-[#141414] px-2 text-[11px] font-bold uppercase cursor-pointer"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* Subscribers Grid Table */}
      <div className="bg-white border border-[#141414] rounded-none overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="bg-[#E4E3E0] border-b border-[#141414] text-[#141414] text-[11px] font-mono uppercase tracking-wider">
                <th className="py-2.5 px-3 font-bold w-10">
                  <input
                    type="checkbox"
                    checked={filteredSubscribers.length > 0 && selectedSubIds.length === filteredSubscribers.length}
                    onChange={(e) => {
                      if (e.target.checked) {
                        setSelectedSubIds(filteredSubscribers.map(s => s.id));
                      } else {
                        setSelectedSubIds([]);
                      }
                    }}
                    className="cursor-pointer accent-[#141414] h-3.5 w-3.5 block"
                  />
                </th>
                <th className="py-2.5 px-3 font-bold">SUBSCRIBER_LABEL</th>
                <th className="py-2.5 px-3 font-bold">MAC_IP_ADDRESS</th>
                <th className="py-2.5 px-3 font-bold">BILLING_STATE</th>
                <th className="py-2.5 px-3 font-bold">ROS_BANDWIDTH_LIMIT</th>
                <th className="py-2.5 px-3 font-bold">FIREWALL</th>
                <th className="py-2.5 px-3 font-bold">BALANCE</th>
                <th className="py-2.5 px-3 font-bold text-right">OPERATIONS</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#141414]/10">
              {filteredSubscribers.map((sub) => {
                const plan = profiles.find(p => p.id === sub.planId);
                const isSelected = selectedSubIds.includes(sub.id);
                return (
                  <tr key={sub.id} className={`hover:bg-[#f0efec] transition text-xs ${isSelected ? 'bg-[#f0efec]' : ''}`}>
                    <td className="py-3 px-3">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={(e) => {
                          if (e.target.checked) {
                            setSelectedSubIds(prev => [...prev, sub.id]);
                          } else {
                            setSelectedSubIds(prev => prev.filter(id => id !== sub.id));
                          }
                        }}
                        className="cursor-pointer accent-[#141414] h-3.5 w-3.5 block"
                      />
                    </td>
                    {/* Column 1: Client profile info */}
                    <td className="py-3 px-3">
                      <div className="font-bold text-[#141414]">{sub.name}</div>
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 mt-0.5 font-mono text-[11px] text-[#141414]/60">
                        <span className="flex items-center gap-0.5">
                          <Smartphone className="h-2 w-2" />
                          {sub.phone}
                        </span>
                        {sub.email && (
                          <span className="flex items-center gap-0.5">
                            <Mail className="h-2 w-2" />
                            {sub.email}
                          </span>
                        )}
                      </div>
                    </td>

                    {/* Column 2: IP and MAC Addresses */}
                    <td className="py-3 px-3 font-mono">
                      <div className="font-bold text-[#141414]">{sub.ipAddress}</div>
                      <div className="text-[10px] text-[#141414]/65">
                        MAC: {sub.macAddress || 'STATIC_LEASE'}
                      </div>
                    </td>

                    {/* Column 3: Invoicing terms and validity dates */}
                    <td className="py-3 px-3 font-mono text-xs">
                      <div className="flex items-center gap-1">
                        <span className={`inline-block w-1 h-1 ${sub.billingType === 'Daily' ? 'bg-[#FF4500]' : 'bg-[#141414]'}`}></span>
                        <span className="font-bold uppercase">{sub.billingType}</span>
                        {sub.autoInvoice ? (
                          <span className="text-[10px] bg-[#E4E3E0] text-[#141414] border border-[#141414]/20 px-1 py-0.1 font-bold">AUTO</span>
                        ) : (
                          <span className="text-[10px] bg-white text-[#141414]/60 border border-[#141414]/15 px-1 py-0.1">MANL</span>
                        )}
                      </div>
                      <div className="text-[10px] text-[#141414]/60 mt-0.5">
                        NEXT_CYCLE: {sub.nextBillingDate}
                      </div>
                    </td>

                    {/* Column 4: Speed rate limits */}
                    <td className="py-3 px-3 font-mono">
                      {plan ? (
                        <div>
                          <div className="text-xs font-bold text-[#141414] flex items-center gap-1">
                            <Router className="h-3 w-3" />
                            <span>{plan.downloadSpeed} rx / {plan.uploadSpeed} tx</span>
                          </div>
                          <div className="text-[10px] text-[#141414]/60 uppercase truncate max-w-40">
                            {plan.name}
                          </div>
                        </div>
                      ) : (
                        <span className="text-[11px] text-[#FF4500] font-bold">UNCONFIG_LIMIT</span>
                      )}
                    </td>

                    {/* Column 5: Health & Suspension indicators */}
                    <td className="py-3 px-3">
                      <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 text-[11px] font-bold font-mono border ${
                        sub.status === 'Active' ? 'bg-[#228B22]/10 text-[#228B22] border-[#228B22]/40' :
                        sub.status === 'Suspended' ? 'bg-[#FF4500]/10 text-[#FF4500] border-[#FF4500]/40' :
                        'bg-[#E4E3E0] text-[#141414] border-[#141414]/30'
                      }`}>
                        <span className={`h-1 w-1 rounded-full ${
                          sub.status === 'Active' ? 'bg-[#228B22]' :
                          sub.status === 'Suspended' ? 'bg-[#FF4500]' :
                          'bg-[#141414]'
                        }`}></span>
                        {sub.status.toUpperCase()}
                      </span>
                    </td>

                    {/* Column 6: Subscriber outstanding client balance */}
                    <td className="py-3 px-3 font-mono font-bold text-xs text-[#141414]">
                      Ksh {sub.balance.toLocaleString()}
                    </td>

                    {/* Column 7: Operational triggers */}
                    <td className="py-3 px-3 text-right">
                      <div className="flex items-center justify-end gap-1 font-mono">
                        {/* Auto invoice manual generator */}
                        <button
                          type="button"
                          onClick={() => onTriggerManualInvoice(sub)}
                          title="Generate instant on-demand invoice"
                          className="p-1 px-1.5 text-[11px] border border-[#141414]/30 hover:border-[#141414] bg-white hover:bg-[#E4E3E0] text-[#141414] rounded-none transition cursor-pointer"
                        >
                          BILL
                        </button>

                        {/* Suspension toggler */}
                        <button
                          type="button"
                          onClick={() => handleToggleStatus(sub, sub.status)}
                          title={sub.status === 'Active' ? 'Suspend account traffic' : 'Activate account traffic'}
                          className={`p-1 px-1.5 text-[11px] border rounded-none transition cursor-pointer ${
                            sub.status === 'Active' 
                            ? 'bg-[#FF4500] text-white border-[#FF4500]' 
                            : 'bg-[#228B22] text-white border-[#228B22]'
                          }`}
                        >
                          {sub.status === 'Active' ? 'BLOCK' : 'ALLOW'}
                        </button>

                        <button
                          type="button"
                          onClick={() => setEditingSub(sub)}
                          className="p-1 text-[#141414] hover:bg-[#E4E3E0] border border-[#141414]/30 rounded-none transition cursor-pointer"
                          title="Edit Subscriber Profile"
                        >
                          <Edit3 className="h-3 w-3" />
                        </button>
                        
                        <button
                          type="button"
                          onClick={() => {
                            if (confirm(`Remove subscriber ${sub.name}? This will free up IP IP-address ${sub.ipAddress}.`)) {
                              onDeleteSubscriber(sub.id);
                              onAddLog('Subscriber', 'warning', `Deleted subscriber folder for key ${sub.name}.`);
                            }
                          }}
                          className="p-1 text-[#FF4500] hover:bg-[#FF4500]/10 border border-[#FF4500]/30 hover:border-[#FF4500] rounded-none transition cursor-pointer"
                          title="Delete Subscriber Profile"
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* Add Subscriber Slide-over Modal */}
      {isAddOpen && (
        <div className="fixed inset-0 bg-[#141414]/65 flex items-center justify-center p-4 z-50 animate-fade-in">
          <div className="bg-white border-2 border-[#141414] rounded-none w-full max-w-lg overflow-hidden relative">
            <div className="flex items-center justify-between px-6 py-3.5 border-b border-[#141414] bg-[#E4E3E0]">
              <h3 className="text-xs font-serif italic font-bold text-[#141414] flex items-center gap-1.5 uppercase">
                <Plus className="h-3.5 w-3.5" />
                <span>Register_New_WiFi/Fiber_Account</span>
              </h3>
              <button 
                onClick={() => setIsAddOpen(false)}
                className="p-1 border border-[#141414]/30 bg-white hover:bg-[#141414] hover:text-white transition cursor-pointer"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <form onSubmit={handleAddSubmit} className="p-6 space-y-4 max-h-[75vh] overflow-y-auto">
              <div className="space-y-1">
                <label className="text-[11px] font-mono font-bold uppercase text-[#141414]/60 block">Full Name *</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. John Doe"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full bg-white border border-[#141414] p-2 text-xs font-mono rounded-none outline-none text-[#141414] focus:bg-[#f0efec]"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-[11px] font-mono font-bold uppercase text-[#141414]/60 block">Phone Number</label>
                  <input
                    type="tel"
                    placeholder="e.g. +254..."
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                    className="w-full bg-white border border-[#141414] p-2 text-xs font-mono rounded-none outline-none text-[#141414] focus:bg-[#f0efec]"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-[11px] font-mono font-bold uppercase text-[#141414]/60 block">Email Address</label>
                  <input
                    type="email"
                    placeholder="e.g. user@domain.com"
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    className="w-full bg-white border border-[#141414] p-2 text-xs font-mono rounded-none outline-none text-[#141414] focus:bg-[#f0efec]"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-[11px] font-mono font-bold uppercase text-[#141414]/60 block">Physical Location / Room</label>
                <input
                  type="text"
                  placeholder="e.g. Villa Block C, Apt 12"
                  value={address}
                  onChange={(e) => setAddress(e.target.value)}
                  className="w-full bg-white border border-[#141414] p-2 text-xs font-mono rounded-none outline-none text-[#141414] focus:bg-[#f0efec]"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-[11px] font-mono font-bold uppercase text-[#141414]/60 block">Static IP Pool binding *</label>
                  <input
                    type="text"
                    required
                    placeholder="192.168.88.x"
                    value={ipAddress}
                    onChange={(e) => setIpAddress(e.target.value)}
                    className="w-full bg-white border border-[#141414] p-2 text-xs font-mono rounded-none outline-none text-[#141414] focus:bg-[#f0efec]"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-[11px] font-mono font-bold uppercase text-[#141414]/60 block">MAC Hardware (Optional)</label>
                  <input
                    type="text"
                    placeholder="A1:B2:C3:D4:E5:F6"
                    value={macAddress}
                    onChange={(e) => setMacAddress(e.target.value)}
                    className="w-full bg-white border border-[#141414] p-2 text-xs font-mono rounded-none outline-none text-[#141414] focus:bg-[#f0efec]"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-[11px] font-mono font-bold uppercase text-[#141414]/60 block">Assigned Bandwidth Plan</label>
                  <select
                    value={planId}
                    onChange={(e) => setPlanId(e.target.value)}
                    className="w-full bg-white border border-[#141414] p-2 text-xs font-mono rounded-none outline-none text-[#141414]"
                  >
                    {profiles.map(p => (
                      <option key={p.id} value={p.id}>{p.name} (Ksh {p.price.toLocaleString()})</option>
                    ))}
                  </select>
                </div>
                <div className="space-y-1">
                  <label className="text-[11px] font-mono font-bold uppercase text-[#141414]/60 block">Validity Cycle Schedule</label>
                  <select
                    value={billingType}
                    onChange={(e) => setBillingType(e.target.value as any)}
                    className="w-full bg-white border border-[#141414] p-2 text-xs font-mono rounded-none outline-none text-[#141414]"
                  >
                    <option value="Daily">Daily Validity</option>
                    <option value="Monthly">Monthly Validity</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-[11px] font-mono font-bold uppercase text-[#141414]/60 block">Anchor Billing Trigger Date</label>
                  <input
                    type="date"
                    value={nextBillingDate}
                    onChange={(e) => setNextBillingDate(e.target.value)}
                    className="w-full bg-white border border-[#141414] p-2 text-xs font-mono rounded-none outline-none text-[#141414]"
                  />
                </div>
                <div className="space-y-1 flex flex-col justify-end">
                  <button
                    type="button"
                    onClick={() => setAutoInvoice(!autoInvoice)}
                    className="flex items-center gap-2 select-none text-xs text-left text-[#141414] p-2 bg-[#f0efec] border border-[#141414]/30 rounded-none hover:bg-[#E4E3E0] transition"
                  >
                    {autoInvoice ? (
                      <ToggleRight className="h-5 w-5 text-[#228B22] cursor-pointer" />
                    ) : (
                      <ToggleLeft className="h-5 w-5 text-[#141414]/50 cursor-pointer" />
                    )}
                    <div>
                      <div className="font-bold">AUTO_INVOICING</div>
                      <div className="text-[10px] opacity-60">Generate invoices on renewal</div>
                    </div>
                  </button>
                </div>
              </div>

              <div className="flex items-center gap-3 pt-4 border-t border-[#141414]/15">
                <button
                  type="button"
                  onClick={() => setIsAddOpen(false)}
                  className="flex-1 py-2 border border-[#141414]/40 hover:bg-[#f0efec] text-xs font-bold uppercase rounded-none transition text-[#141414]"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="flex-1 py-2 bg-[#141414] text-white hover:bg-white hover:text-[#141414] border border-[#141414] text-xs font-bold uppercase rounded-none transition"
                >
                  REGISTER_CLIENT
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Edit Subscriber Modal */}
      {editingSub && (
        <div className="fixed inset-0 bg-[#141414]/65 flex items-center justify-center p-4 z-50 animate-fade-in">
          <div className="bg-white border-2 border-[#141414] rounded-none w-full max-w-lg overflow-hidden relative">
            <div className="flex items-center justify-between px-6 py-3.5 border-b border-[#141414] bg-[#E4E3E0]">
              <h3 className="text-xs font-serif italic font-bold text-[#141414] flex items-center gap-1.5 uppercase">
                <Edit3 className="h-3 w-3" />
                <span>Modify_Subscriber_Profile</span>
              </h3>
              <button 
                onClick={() => setEditingSub(null)}
                className="p-1 border border-[#141414]/30 bg-white hover:bg-[#141414] hover:text-white transition cursor-pointer"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <form onSubmit={handleEditSubmit} className="p-6 space-y-4 max-h-[75vh] overflow-y-auto">
              <div className="space-y-1">
                <label className="text-[11px] font-mono font-bold uppercase text-[#141414]/60 block">Full Name</label>
                <input
                  type="text"
                  required
                  value={editingSub.name}
                  onChange={(e) => setEditingSub({...editingSub, name: e.target.value})}
                  className="w-full bg-white border border-[#141414] p-2 text-xs font-mono rounded-none outline-none text-[#141414] focus:bg-[#f0efec]"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-[11px] font-mono font-bold uppercase text-[#141414]/60 block">Phone</label>
                  <input
                    type="tel"
                    value={editingSub.phone}
                    onChange={(e) => setEditingSub({...editingSub, phone: e.target.value})}
                    className="w-full bg-white border border-[#141414] p-2 text-xs font-mono rounded-none outline-none text-[#141414] focus:bg-[#f0efec]"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-[11px] font-mono font-bold uppercase text-[#141414]/60 block">Email</label>
                  <input
                    type="email"
                    value={editingSub.email}
                    onChange={(e) => setEditingSub({...editingSub, email: e.target.value})}
                    className="w-full bg-white border border-[#141414] p-2 text-xs font-mono rounded-none outline-none text-[#141414] focus:bg-[#f0efec]"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-[11px] font-mono font-bold uppercase text-[#141414]/60 block">IP Address</label>
                  <input
                    type="text"
                    required
                    value={editingSub.ipAddress}
                    onChange={(e) => setEditingSub({...editingSub, ipAddress: e.target.value})}
                    className="w-full bg-white border border-[#141414] p-2 text-xs font-mono rounded-none outline-none text-[#141414] focus:bg-[#f0efec]"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-[11px] font-mono font-bold uppercase text-[#141414]/60 block">MAC Address</label>
                  <input
                    type="text"
                    placeholder="Dynamic Address"
                    value={editingSub.macAddress || ''}
                    onChange={(e) => setEditingSub({...editingSub, macAddress: e.target.value})}
                    className="w-full bg-white border border-[#141414] p-2 text-xs font-mono rounded-none outline-none text-[#141414] focus:bg-[#f0efec]"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-[11px] font-mono font-bold uppercase text-[#141414]/60 block">Package Profile</label>
                  <select
                    value={editingSub.planId}
                    onChange={(e) => setEditingSub({...editingSub, planId: e.target.value})}
                    className="w-full bg-white border border-[#141414] p-2 text-xs font-mono rounded-none outline-none text-[#141414]"
                  >
                    {profiles.map(p => (
                      <option key={p.id} value={p.id}>{p.name} (Ksh {p.price.toLocaleString()})</option>
                    ))}
                  </select>
                </div>
                <div className="space-y-1">
                  <label className="text-[11px] font-mono font-bold uppercase text-[#141414]/60 block">Cycle Code</label>
                  <select
                    value={editingSub.billingType}
                    onChange={(e) => setEditingSub({...editingSub, billingType: e.target.value as any})}
                    className="w-full bg-white border border-[#141414] p-2 text-xs font-mono rounded-none outline-none text-[#141414]"
                  >
                    <option value="Daily">Daily Validity Cycle</option>
                    <option value="Monthly">Monthly Validity Cycle</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-[11px] font-mono font-bold uppercase text-[#141414]/60 block">Next Automatic Billing</label>
                  <input
                    type="date"
                    value={editingSub.nextBillingDate}
                    onChange={(e) => setEditingSub({...editingSub, nextBillingDate: e.target.value})}
                    className="w-full bg-white border border-[#141414] p-2 text-xs font-mono rounded-none outline-none text-[#141414]"
                  />
                </div>
                <div className="space-y-1 flex flex-col justify-end">
                  <button
                    type="button"
                    onClick={() => setEditingSub({...editingSub, autoInvoice: !editingSub.autoInvoice})}
                    className="flex items-center gap-2 select-none text-xs text-left text-[#141414] p-2 bg-[#f0efec] border border-[#141414]/30 rounded-none hover:bg-[#E4E3E0] transition"
                  >
                    {editingSub.autoInvoice ? (
                      <ToggleRight className="h-5 w-5 text-[#228B22]" />
                    ) : (
                      <ToggleLeft className="h-5 w-5 text-[#141414]/50" />
                    )}
                    <div>
                      <span className="font-bold block">AUTO_INVOICING</span>
                      <span className="text-[10px] opacity-60">Generate invoice on date</span>
                    </div>
                  </button>
                </div>
              </div>

              <div className="flex items-center gap-3 pt-4 border-t border-[#141414]/15">
                <button
                  type="button"
                  onClick={() => setEditingSub(null)}
                  className="flex-1 py-1.5 border border-[#141414]/40 hover:bg-[#f0efec] text-xs font-bold uppercase rounded-none transition text-[#141414]"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="flex-1 py-1.5 bg-[#141414] text-white hover:bg-white hover:text-[#141414] border border-[#141414] text-xs font-bold uppercase rounded-none transition"
                >
                  SAVE_CHANGES
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
