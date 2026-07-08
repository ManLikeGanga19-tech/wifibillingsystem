import React, { useState } from 'react';
import { BandwidthProfile } from '../types';
import { 
  Router, 
  Plus, 
  Edit3, 
  Trash2, 
  DollarSign, 
  Radio, 
  HelpCircle, 
  Check, 
  X, 
  ShieldAlert,
  Info,
  Clock,
  Gauge,
  Laptop
} from 'lucide-react';

interface PlanConfiguratorProps {
  profiles: BandwidthProfile[];
  onAddProfile: (profile: Omit<BandwidthProfile, 'id'>) => void;
  onUpdateProfile: (profile: BandwidthProfile) => void;
  onDeleteProfile: (id: string) => void;
  onAddLog: (category: 'Router' | 'Billing' | 'Subscriber' | 'Hotspot', type: 'info' | 'success' | 'warning' | 'error', message: string) => void;
}

export default function PlanConfigurator({
  profiles,
  onAddProfile,
  onUpdateProfile,
  onDeleteProfile,
  onAddLog
}: PlanConfiguratorProps) {
  // Modal states
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [editingProfile, setEditingProfile] = useState<BandwidthProfile | null>(null);

  // Form states
  const [name, setName] = useState('');
  const [downloadSpeed, setDownloadSpeed] = useState('5 Mbps');
  const [uploadSpeed, setUploadSpeed] = useState('2 Mbps');
  const [price, setPrice] = useState(1.50);
  const [validityDays, setValidityDays] = useState(1);
  const [validityLabel, setValidityLabel] = useState('Daily');
  const [sharedUsersLimit, setSharedUsersLimit] = useState(1);
  const [description, setDescription] = useState('');

  const resetForm = () => {
    setName('');
    setDownloadSpeed('5 Mbps');
    setUploadSpeed('2 Mbps');
    setPrice(1.5);
    setValidityDays(1);
    setValidityLabel('Daily');
    setSharedUsersLimit(1);
    setDescription('');
  };

  const handleAddSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!name) return;

    onAddProfile({
      name,
      downloadSpeed,
      uploadSpeed,
      price,
      validityDays,
      validityLabel,
      sharedUsersLimit,
      description,
      isActive: true
    });

    onAddLog(
      'Router',
      'success',
      `Hotspot & Queue Profile Sync: Synchronized new bandwidth package profile '${name}' with QoS limits: ${downloadSpeed} Down / ${uploadSpeed} Up.`
    );

    setIsAddOpen(false);
    resetForm();
  };

  const handleEditSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingProfile) return;

    onUpdateProfile(editingProfile);
    onAddLog(
      'Router',
      'info',
      `Synchronized plan updates for '${editingProfile.name}' (Price: KSh ${editingProfile.price.toLocaleString()}).`
    );

    setEditingProfile(null);
  };

  return (
    <div className="space-y-6 text-[#141414]">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-sm font-serif italic font-bold text-[#141414] flex items-center gap-2 uppercase">
            <Gauge className="h-4.5 w-4.5" />
            <span>Bandwidth Packages & Pricing</span>
          </h2>
          <p className="text-xs font-mono text-[#141414]/70 mt-0.5">
            Specify download/upload speed limits (cappings) and prices. These values compile to MikroTik Dynamic Queues and hotspot profiles.
          </p>
        </div>

        <button
          onClick={() => setIsAddOpen(true)}
          className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-bold font-mono text-white bg-[#141414] hover:bg-[#E4E3E0] hover:text-[#141414] border border-[#141414] rounded-none transition cursor-pointer self-start uppercase"
        >
          <Plus className="h-4 w-4" />
          Create Speed Package
        </button>
      </div>

      {/* Package Profiles Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {profiles.map((prof) => (
          <div 
            key={prof.id} 
            className={`bg-white border border-[#141414] rounded-none p-4 flex flex-col justify-between shadow-none relative ${!prof.isActive ? 'opacity-60' : ''}`}
          >
            {/* Header info */}
            <div>
              <div className="flex justify-between items-start">
                <span className="text-[11px] bg-[#E4E3E0] border border-[#141414]/30 text-[#141414] px-1.5 py-0.5 rounded-none font-bold uppercase tracking-tight font-mono">
                  {prof.validityLabel} Validity
                </span>
                <span className="text-sm font-black font-mono text-[#228B22]">
                  KSh {prof.price.toLocaleString()}
                </span>
              </div>

              <h3 className="text-sm font-serif italic font-bold text-[#141414] tracking-tight mt-3">
                {prof.name}
              </h3>

              <p className="text-[10.5px] text-[#141414]/80 mt-1 leading-normal font-mono min-h-[3rem]">
                {prof.description || 'Standard QoS user restrictions applied globally.'}
              </p>
            </div>

            {/* Profile specifications list */}
            <div className="border-t border-b border-[#141414]/20 py-2.5 my-3 grid grid-cols-2 gap-2 text-[11px] font-mono">
              <div className="space-y-0.5">
                <div className="text-[#141414]/50 font-bold flex items-center gap-1 uppercase text-[11px]">
                  <Gauge className="h-3 w-3" /> Speed Limits:
                </div>
                <div className="font-bold text-[#141414]">
                  D: {prof.downloadSpeed} / U: {prof.uploadSpeed}
                </div>
              </div>
              <div className="space-y-0.5">
                <div className="text-[#141414]/50 font-bold flex items-center gap-1 uppercase text-[11px]">
                  <Laptop className="h-3 w-3" /> MAC Quota:
                </div>
                <div className="font-bold text-[#141414]">
                  {prof.sharedUsersLimit} Active Device{prof.sharedUsersLimit > 1 ? 's' : ''}
                </div>
              </div>
            </div>

            {/* Actions toolbar */}
            <div className="flex items-center justify-between font-mono">
              <div className="flex items-center gap-1.5">
                <span className={`w-1.5 h-1.5 ${prof.isActive ? 'bg-[#228B22]' : 'bg-red-500'}`}></span>
                <span className="text-[11px] font-bold text-[#141414]/50 uppercase">{prof.isActive ? 'ACTIVE_SYNC' : 'SUSPENDED'}</span>
              </div>

              <div className="flex items-center gap-1.5">
                <button
                  onClick={() => setEditingProfile(prof)}
                  className="p-1 px-2 text-[11px] font-bold border border-[#141414] bg-[#E4E3E0]/30 hover:bg-[#E4E3E0] text-[#141414] rounded-none transition cursor-pointer uppercase"
                >
                  Configure
                </button>
                <button
                  onClick={() => {
                    if (confirm(`Remove custom package ${prof.name}?`)) {
                      onDeleteProfile(prof.id);
                      onAddLog('Router', 'warning', `Deleted QoS speed profile folder ${prof.name}.`);
                    }
                  }}
                  className="p-1 border border-red-500 hover:bg-red-550 hover:bg-red-500 hover:text-white text-red-500 rounded-none transition cursor-pointer"
                  title="Remove Profile"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Add Plan Modal */}
      {isAddOpen && (
        <div className="fixed inset-0 bg-[#141414]/65 flex items-center justify-center p-4 z-50">
          <div className="bg-white border-2 border-[#141414] rounded-none w-full max-w-lg overflow-hidden relative shadow-none">
            <div className="flex items-center justify-between px-4 py-2 bg-[#E4E3E0] border-b border-[#141414]">
              <h3 className="text-xs font-bold font-mono text-[#141414] flex items-center gap-1.5 uppercase">
                <Plus className="h-4 w-4" />
                <span>Create Speed/Price WiFi Plan</span>
              </h3>
              <button 
                onClick={() => setIsAddOpen(false)}
                className="p-1 border border-[#141414]/30 bg-white hover:bg-[#141414] hover:text-white rounded-none transition cursor-pointer"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <form onSubmit={handleAddSubmit} className="p-5 space-y-4 max-h-[75vh] overflow-y-auto font-mono text-xs">
              <div className="space-y-1">
                <label className="text-xs font-bold text-[#141414]/60 uppercase block">Profile Name *</label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Monthly Standard SME"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  className="w-full bg-white border border-[#141414] p-2 text-xs rounded-none outline-none text-[#141414] placeholder-[#141414]/40"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-xs font-bold text-[#141414]/60 uppercase block">Download Bandwidth Target</label>
                  <select
                    value={downloadSpeed}
                    onChange={(e) => setDownloadSpeed(e.target.value)}
                    className="w-full bg-white border border-[#141414] p-2 text-xs rounded-none outline-none text-[#141414]"
                  >
                    <option value="1 Mbps">1 Mbps (Low Speed)</option>
                    <option value="3 Mbps">3 Mbps (Daily standard)</option>
                    <option value="5 Mbps">5 Mbps (Broadband Light)</option>
                    <option value="10 Mbps">10 Mbps (Fiber Standard)</option>
                    <option value="20 Mbps">20 Mbps (Fiber High Limit)</option>
                    <option value="50 Mbps">50 Mbps (Fibre SME Pro)</option>
                  </select>
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-bold text-[#141414]/60 uppercase block">Upload Bandwidth rate-limit</label>
                  <select
                    value={uploadSpeed}
                    onChange={(e) => setUploadSpeed(e.target.value)}
                    className="w-full bg-white border border-[#141414] p-2 text-xs rounded-none outline-none text-[#141414]"
                  >
                    <option value="1 Mbps">1 Mbps Uplink</option>
                    <option value="2 Mbps">2 Mbps Uplink</option>
                    <option value="5 Mbps">5 Mbps Uplink</option>
                    <option value="10 Mbps">10 Mbps Uplink</option>
                    <option value="20 Mbps">20 Mbps Uplink</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-xs font-bold text-[#141414]/60 uppercase block">Price (KSh)</label>
                  <input
                    type="number"
                    step="0.01"
                    required
                    value={price}
                    onChange={(e) => setPrice(Number(e.target.value))}
                    className="w-full bg-white border border-[#141414] p-2 text-xs rounded-none outline-none text-[#141414]"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-bold text-[#141414]/60 uppercase block">Shared MAC Limit</label>
                  <select
                    value={sharedUsersLimit}
                    onChange={(e) => setSharedUsersLimit(Number(e.target.value))}
                    className="w-full bg-white border border-[#141414] p-2 text-xs rounded-none outline-none text-[#141414]"
                  >
                    <option value="1">1 Device Limit</option>
                    <option value="2">2 Devices Concurrent</option>
                    <option value="3">3 Devices Concurrent</option>
                    <option value="5">5 Devices Concurrent (SME)</option>
                    <option value="10">10 Devices Joint Limit</option>
                  </select>
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-xs font-bold text-[#141414]/60 uppercase block">Cycle Days (Validity)</label>
                  <input
                    type="number"
                    step="0.01"
                    required
                    value={validityDays}
                    onChange={(e) => setValidityDays(Number(e.target.value))}
                    className="w-full bg-white border border-[#141414] p-2 text-xs rounded-none outline-none text-[#141414]"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-bold text-[#141414]/60 uppercase block">Cycle Label</label>
                  <input
                    type="text"
                    required
                    placeholder="e.g. Daily, 3 Hours, Monthly"
                    value={validityLabel}
                    onChange={(e) => setValidityLabel(e.target.value)}
                    className="w-full bg-white border border-[#141414] p-2 text-xs rounded-none outline-none text-[#141414]"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-xs font-bold text-[#141414]/60 uppercase block">Brief Package Description</label>
                <textarea
                  placeholder="e.g. Perfect for SMEs and residential users needing basic internet access..."
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  className="w-full bg-white border border-[#141414] p-2 text-xs rounded-none outline-none text-[#141414] placeholder-[#141414]/40 h-16 resize-none"
                />
              </div>

              <div className="flex items-center gap-3 pt-3 border-t border-[#141414]/15">
                <button
                  type="button"
                  onClick={() => setIsAddOpen(false)}
                  className="flex-1 py-2 border border-[#141414] rounded-none hover:bg-[#E4E3E0] text-xs font-bold uppercase transition text-[#141414]"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="flex-1 py-2 bg-[#228B22] border border-[#228B22] text-white hover:bg-white hover:text-[#228B22] rounded-none text-xs font-bold uppercase transition"
                >
                  Sync New Plan
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Edit Plan Modal */}
      {editingProfile && (
        <div className="fixed inset-0 bg-[#141414]/65 flex items-center justify-center p-4 z-50">
          <div className="bg-white border-2 border-[#141414] rounded-none w-full max-w-lg overflow-hidden relative shadow-none">
            <div className="flex items-center justify-between px-4 py-2 bg-[#E4E3E0] border-b border-[#141414]">
              <h3 className="text-xs font-bold font-mono text-[#141414] flex items-center gap-1.5 uppercase">
                <Edit3 className="h-4 w-4 text-blue-600" />
                <span>Modify Bandwidth Profile Parameters</span>
              </h3>
              <button 
                onClick={() => setEditingProfile(null)}
                className="p-1 border border-[#141414]/30 bg-white hover:bg-[#141414] hover:text-white rounded-none transition cursor-pointer"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <form onSubmit={handleEditSubmit} className="p-5 space-y-4 max-h-[75vh] overflow-y-auto font-mono text-xs">
              <div className="space-y-1">
                <label className="text-xs font-bold text-[#141414]/60 uppercase block">Profile Title</label>
                <input
                  type="text"
                  required
                  value={editingProfile.name}
                  onChange={(e) => setEditingProfile({...editingProfile, name: e.target.value})}
                  className="w-full bg-white border border-[#141414] p-2 text-xs rounded-none outline-none text-[#141414]"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-xs font-bold text-[#141414]/60 uppercase block">Download Cap</label>
                  <input
                    type="text"
                    required
                    value={editingProfile.downloadSpeed}
                    onChange={(e) => setEditingProfile({...editingProfile, downloadSpeed: e.target.value})}
                    className="w-full bg-white border border-[#141414] p-2 text-xs rounded-none outline-none text-[#141414]"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-bold text-[#141414]/60 uppercase block">Upload Cap</label>
                  <input
                    type="text"
                    required
                    value={editingProfile.uploadSpeed}
                    onChange={(e) => setEditingProfile({...editingProfile, uploadSpeed: e.target.value})}
                    className="w-full bg-white border border-[#141414] p-2 text-xs rounded-none outline-none text-[#141414]"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-xs font-bold text-[#141414]/60 uppercase block">Price ($)</label>
                  <input
                    type="number"
                    step="0.01"
                    required
                    value={editingProfile.price}
                    onChange={(e) => setEditingProfile({...editingProfile, price: Number(e.target.value)})}
                    className="w-full bg-white border border-[#141414] p-2 text-xs rounded-none outline-none text-[#141414]"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-bold text-[#141414]/60 uppercase block">Shared limit (Device limits)</label>
                  <input
                    type="number"
                    required
                    value={editingProfile.sharedUsersLimit}
                    onChange={(e) => setEditingProfile({...editingProfile, sharedUsersLimit: Number(e.target.value)})}
                    className="w-full bg-white border border-[#141414] p-2 text-xs rounded-none outline-none text-[#141414]"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-xs font-bold text-[#141414]/60 uppercase block">Validity Index (Days)</label>
                  <input
                    type="number"
                    step="0.01"
                    required
                    value={editingProfile.validityDays}
                    onChange={(e) => setEditingProfile({...editingProfile, validityDays: Number(e.target.value)})}
                    className="w-full bg-white border border-[#141414] p-2 text-xs rounded-none outline-none text-[#141414]"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-bold text-[#141414]/60 uppercase block">Validity Heading Category</label>
                  <input
                    type="text"
                    required
                    value={editingProfile.validityLabel}
                    onChange={(e) => setEditingProfile({...editingProfile, validityLabel: e.target.value})}
                    className="w-full bg-white border border-[#141414] p-2 text-xs rounded-none outline-none text-[#141414] mt-1"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-xs font-bold text-[#141414]/60 uppercase block">Package Description</label>
                <textarea
                  value={editingProfile.description || ''}
                  onChange={(e) => setEditingProfile({...editingProfile, description: e.target.value})}
                  className="w-full bg-white border border-[#141414] p-2 text-xs rounded-none outline-none text-[#141414] h-16 resize-none"
                />
              </div>

              <div className="flex items-center gap-2 py-2">
                <input
                  type="checkbox"
                  id="chk-profile-active"
                  checked={editingProfile.isActive}
                  onChange={(e) => setEditingProfile({...editingProfile, isActive: e.target.checked})}
                  className="h-3.5 w-3.5 bg-white border-[#141414] rounded-none cursor-pointer text-[#141414]"
                />
                <label htmlFor="chk-profile-active" className="text-xs text-[#141414]/70 select-none cursor-pointer font-bold">
                  Toggle status as Active WiFi subscription target
                </label>
              </div>

              <div className="flex items-center gap-3 pt-3 border-t border-[#141414]/15">
                <button
                  type="button"
                  onClick={() => setEditingProfile(null)}
                  className="flex-1 py-2 border border-[#141414] rounded-none hover:bg-[#E4E3E0] text-xs font-bold uppercase transition text-[#141414]"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="flex-1 py-2 bg-[#228B22] border border-[#228B22] text-white hover:bg-white hover:text-[#228B22] rounded-none text-xs font-bold uppercase transition"
                >
                  Save Profile
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
