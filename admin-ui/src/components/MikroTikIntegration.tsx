import React, { useState } from 'react';
import { RouterConfig, SystemLog, Subscriber, HotspotVoucher } from '../types';
import { 
  Cpu, 
  Terminal, 
  Network, 
  Settings, 
  RefreshCw, 
  CheckCircle, 
  AlertTriangle, 
  Play, 
  Activity, 
  HelpCircle,
  Database,
  Unplug,
  Flame,
  Search,
  BookOpen
} from 'lucide-react';

interface MikroTikIntegrationProps {
  router: RouterConfig;
  subscribers: Subscriber[];
  vouchers: HotspotVoucher[];
  onUpdateRouter: (updatedRouter: RouterConfig) => void;
  logs: SystemLog[];
  onAddLog: (category: 'Router' | 'Billing' | 'Subscriber' | 'Hotspot', type: 'info' | 'success' | 'warning' | 'error', message: string) => void;
}

const PRESET_SCRIPTS = [
  {
    name: 'Fetch Active Queues',
    command: '/queue simple print detail',
    description: 'Lists all subscriber rate limits active inside MikroTik Simple Queues.'
  },
  {
    name: 'Print Hotspot IP Pool',
    command: '/ip pool print',
    description: 'Displays current IP lease ranges for the Hotspot interface.'
  },
  {
    name: 'Firewall Filter Status',
    command: '/ip firewall filter print where comment~"Billing"',
    description: 'View custom firewall lists used to drop expired subscriber interfaces.'
  },
  {
    name: 'Verify ARP Leases',
    command: '/ip arp print',
    description: 'Lists MAC to IP state table mapped to ethernet interfaces.'
  }
];

export default function MikroTikIntegration({
  router,
  subscribers,
  vouchers,
  onUpdateRouter,
  logs,
  onAddLog
}: MikroTikIntegrationProps) {
  // Setup forms state
  const [ipAddress, setIpAddress] = useState(router.ipAddress);
  const [port, setPort] = useState(router.port);
  const [username, setUsername] = useState(router.username);
  const [password, setPassword] = useState('**********');
  const [hotspotInterface, setHotspotInterface] = useState(router.hotspotInterface);
  
  // Connection Test animation States
  const [isTesting, setIsTesting] = useState(false);
  const [testResult, setTestResult] = useState<{status: 'idle' | 'success' | 'error'; message: string}>({status: 'idle', message: ''});

  // CLI state
  const [cliInput, setCliInput] = useState('');
  const [cliHistory, setCliHistory] = useState<string[]>([
    '# Core_RouterBOARD_951G [MikroTik RouterOS v7.12.1]',
    '# Terminal session initialized over secure API socket...',
    '# Type router commands or select preset recipes to query.',
    ''
  ]);

  const handleUpdateConfig = (e: React.FormEvent) => {
    e.preventDefault();
    onUpdateRouter({
      ...router,
      ipAddress,
      port,
      username,
      hotspotInterface
    });
    onAddLog(
      'Router',
      'info',
      `MikroTik credentials updated: IP: ${ipAddress} on port ${port}. sync updated.`
    );
    alert('Router parameters updated. Refreshing sync states... successful.');
  };

  const handleRunPingTest = () => {
    setIsTesting(true);
    setTestResult({status: 'idle', message: 'Sending dynamic socket packets...'});
    onAddLog('Router', 'info', `Initiating API handshake test with ${ipAddress}:${port}...`);
    
    setTimeout(() => {
      setIsTesting(false);
      setTestResult({
        status: 'success',
        message: 'Ping latency: 12ms. Socket established. SSL/TLS secure API connected. RouterBOARD response verified.'
      });
      onAddLog('Router', 'success', `Ping handshake success: ${ipAddress} responded with latency 12ms. API online.`);
    }, 1800);
  };

  const executeCliCommand = (commandText: string) => {
    if (!commandText.trim()) return;

    setCliHistory(prev => [...prev, `[admin@${router.name}] > ${commandText}`]);

    const cleanCmd = commandText.trim().toLowerCase();
    let response: string[] = [];

    if (cleanCmd.includes('queue simple print')) {
      response.push(
        '# Flags: X - disabled, I - invalid, D - dynamic',
        ' 0   name="sub-1-harun" target=192.168.88.50/32 max-limit=10M/5M limit-at=10M/5M rate=3.4M/1.2M',
        ' 1   name="sub-2-amina" target=192.168.88.51/32 max-limit=20M/10M limit-at=20M/10M rate=12.1M/3.9M',
        ' 2   name="sub-3-john" target=192.168.88.102/32 max-limit=3M/1M limit-at=3M/1M rate=0.1M/0.05M',
        ` 3   name="sub-4-priscilla" max-limit=20M/10M limit-at=20M/10M rate=0/0 [SUSPENDED - DROP CHAIN STAGE 1]`
      );
    } else if (cleanCmd.includes('ip pool print')) {
      response.push(
        '# Flags: X - disabled',
        ' #   NAME                            RANGES',
        ` 0   hs-pool-1                       192.168.88.100-192.168.88.254`
      );
    } else if (cleanCmd.includes('ip firewall filter print')) {
      response.push(
        '# Flags: X - disabled, A - active, D - dynamic',
        ' 0  A chain=forward action=drop src-address=192.168.88.80 comment="SUSPENDED: Priscilla Wanjiku - Billing Unpaid"'
      );
    } else if (cleanCmd.includes('ip arp print')) {
      response.push(
        '# Flags: X - disabled, I - invalid, H - DHCP, D - dynamic',
        ' #   ADDRESS         MAC-ADDRESS       INTERFACE',
        ' 0 H 192.168.88.50   C8:D7:19:AA:BB:CC ether3-hotspot-lan',
        ' 1 H 192.168.88.51   40:B0:34:CC:DD:EE ether3-hotspot-lan',
        ' 2 H 192.168.88.102  90:32:00:1F:11:22 ether3-hotspot-lan',
        ' 3 D 192.168.88.115  D4:12:43:B5:E8:90 ether3-hotspot-lan [Voucher Login WF-9182C]'
      );
    } else {
      // General feedback simulator
      response.push(
        'Command acknowledged. Command syntax compiled with NodeOS.',
        `Status: RouterBOARD ${router.name} processes rule safely.`,
        'No runtime validation error. Execution complete.'
      );
    }

    setCliHistory(prev => [...prev, ...response, '']);
    setCliInput('');
  };

  const handleTerminalSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    executeCliCommand(cliInput);
  };

  return (
    <div className="space-y-6 text-[#141414]">
      
      {/* Cards rows */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        
        {/* Connection Setup Form */}
        <div id="router-credential-settings" className="bg-white border border-[#141414] p-4 rounded-none flex flex-col justify-between">
          <div>
            <div className="flex items-center gap-2 border-b border-[#141414]/20 pb-3 mb-4">
              <Settings className="h-4.5 w-4.5" />
              <div>
                <h3 className="text-xs font-serif italic font-bold uppercase tracking-tight text-[#141414]">
                  MikroTik API Parameters
                </h3>
                <p className="text-xs font-mono text-[#141414]/70 mt-0.5">
                  Configure secure connection credentials to enable direct RouterOS simple queue and DHCP lease controls.
                </p>
              </div>
            </div>

            <form onSubmit={handleUpdateConfig} className="space-y-3 font-mono text-xs">
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-xs font-bold text-[#141414]/60 uppercase">Router IP Address</label>
                  <input
                    type="text"
                    required
                    value={ipAddress}
                    onChange={(e) => setIpAddress(e.target.value)}
                    className="w-full bg-white border border-[#141414] p-2 text-xs rounded-none outline-none text-[#141414]"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-bold text-[#141414]/60 uppercase">API SSL Port</label>
                  <input
                    type="number"
                    required
                    value={port}
                    onChange={(e) => setPort(Number(e.target.value))}
                    className="w-full bg-white border border-[#141414] p-2 text-xs rounded-none outline-none text-[#141414]"
                  />
                </div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1">
                  <label className="text-xs font-bold text-[#141414]/60 uppercase">API Username</label>
                  <input
                    type="text"
                    required
                    value={username}
                    onChange={(e) => setUsername(e.target.value)}
                    className="w-full bg-white border border-[#141414] p-2 text-xs rounded-none outline-none text-[#141414]"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-bold text-[#141414]/60 uppercase">API Password</label>
                  <input
                    type="password"
                    value={password}
                    disabled
                    className="w-full bg-[#f0efec] border border-[#141414]/30 p-2 text-xs rounded-none outline-none text-[#141414]/50"
                  />
                </div>
              </div>

              <div className="space-y-1">
                <label className="text-xs font-bold text-[#141414]/60 uppercase block">Hotspot Interface Profile Bind</label>
                <select
                  value={hotspotInterface}
                  onChange={(e) => setHotspotInterface(e.target.value)}
                  className="w-full bg-white border border-[#141414] p-2 text-xs rounded-none outline-none text-[#141414]"
                >
                  <option value="ether3-hotspot-lan">ether3-hotspot-lan (Hotspot Interface)</option>
                  <option value="ether2-local-lan">ether2-local-lan (Static Clients)</option>
                  <option value="sfp1-optic-uplink">sfp1-optic-uplink (Backbone Optic)</option>
                </select>
              </div>

              <div className="pt-2 border-t border-[#141414]/15 flex gap-2">
                <button
                  type="submit"
                  className="w-full bg-[#141414] border border-[#141414] text-white hover:bg-[#E4E3E0] hover:text-[#141414] py-2 text-xs font-bold uppercase rounded-none transition cursor-pointer"
                >
                  Sync API Settings
                </button>
              </div>
            </form>
          </div>

          <div className="mt-4 p-3 bg-[#E4E3E0]/30 border border-[#141414]/20 rounded-none space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-mono font-bold text-[#141414]/50 uppercase tracking-widest">Device API Socket Health</span>
              <button
                type="button"
                onClick={handleRunPingTest}
                disabled={isTesting}
                className="bg-white border border-[#141414] text-[#141414] hover:bg-[#E4E3E0] text-[11px] font-bold px-2 py-1 rounded-none transition flex items-center gap-1 cursor-pointer uppercase font-mono"
              >
                <RefreshCw className={`h-3 w-3 ${isTesting ? 'animate-spin' : ''}`} />
                Test Link
              </button>
            </div>
            
            <p className="text-xs font-mono leading-relaxed text-[#141414]/80">
              {testResult.message || 'No tests performed in this session. Tap "Test Link" to verify TLS socket.'}
            </p>
          </div>
        </div>

        {/* Sync Operations Recipes */}
        <div className="bg-white border border-[#141414] p-4 rounded-none flex flex-col justify-between">
          <div>
            <div className="flex items-center gap-2 border-b border-[#141414]/20 pb-3 mb-4">
              <BookOpen className="h-4.5 w-4.5" />
              <div>
                <h3 className="text-xs font-serif italic font-bold uppercase tracking-tight text-[#141414]">
                  RouterOS Query Recipes
                </h3>
                <p className="text-xs font-mono text-[#141414]/70 mt-0.5">
                  Select and run typical billing system commands to fetch records from the virtual router kernel in real-time.
                </p>
              </div>
            </div>

            <div className="space-y-2 font-mono">
              {PRESET_SCRIPTS.map((recipe, index) => (
                <div 
                  key={index} 
                  className="p-2.5 border border-[#141414]/25 rounded-none hover:bg-[#f0efec]/40 transition flex items-center justify-between"
                >
                  <div className="space-y-0.5 pr-3 flex-1 min-w-0">
                    <span className="text-[11px] font-bold text-[#141414] block">{recipe.name}</span>
                    <p className="text-[9.5px] text-[#141414]/65 leading-snug">{recipe.description}</p>
                    <code className="text-[11px] text-[#228B22] block font-mono bg-[#E4E3E0]/20 border border-[#141414]/10 px-1 py-0.2 rounded-none mt-1 max-w-sm truncate">{recipe.command}</code>
                  </div>

                  <button
                    onClick={() => {
                      executeCliCommand(recipe.command);
                      onAddLog('Router', 'info', `CLI Tool executed preset: "${recipe.name}"`);
                    }}
                    className="p-1 px-1.5 bg-white border border-[#141414] text-[#141414] hover:bg-[#141414] hover:text-white rounded-none transition cursor-pointer flex items-center justify-center shrink-0"
                    title="Send parameter to terminal"
                  >
                    <Play className="h-3 w-3 fill-current" />
                  </button>
                </div>
              ))}
            </div>
          </div>

          <div className="mt-3 text-[11px] font-mono text-[#141414]/60 text-center leading-relaxed uppercase">
            * All router profile triggers emit structural commands logging direct changes to NAT tables, ARP pools, and simple speed restriction bands.
          </div>
        </div>
      </div>

      {/* Live Interactive Virtual Console Terminal Client */}
      <div id="virtual-microtik-terminal" className="bg-[#141414] text-[#228B22] border-2 border-[#141414] rounded-none shadow-none relative overflow-hidden font-mono text-xs flex flex-col h-96">
        
        {/* Console Header */}
        <div className="bg-[#E4E3E0] border-b border-[#141414] px-4 py-2 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Terminal className="h-4 w-4 text-[#141414]" />
            <span className="text-xs font-bold tracking-tight text-[#141414] uppercase">routerboards_shell_interactive</span>
          </div>
          <div className="flex items-center gap-1.5">
            <button
              onClick={() => setCliHistory([
                '# Core_RouterBOARD_951G [MikroTik RouterOS v7.12.1]',
                '# Terminal buffer cleared.',
                ''
              ])}
              className="text-[11px] font-bold text-[#141414] uppercase bg-white border border-[#141414] px-1.5 py-0.5 rounded-none hover:bg-[#141414] hover:text-white transition cursor-pointer"
            >
              Clear Buffer
            </button>
            <span className="text-[11px] bg-[#228B22]/10 text-[#228B22] px-1.5 py-0.5 rounded-none border border-[#228B22]/40 font-bold uppercase leading-none">Socket ok</span>
          </div>
        </div>

        {/* Console Output Screen Area */}
        <div className="flex-1 overflow-y-auto p-4 space-y-1 flex flex-col scroll-smooth font-mono text-[11px]">
          {cliHistory.map((line, i) => (
            <div key={i} className={`whitespace-pre-wrap leading-relaxed ${line.startsWith('#') ? 'text-zinc-500' : line.startsWith('[') ? 'text-[#ffffff] font-bold' : 'text-[#228B22]'}`}>
              {line}
            </div>
          ))}
        </div>

        {/* Interactive CLI Input Line */}
        <form onSubmit={handleTerminalSubmit} className="bg-[#E4E3E0]/10 border-t border-[#141414] px-4 py-3 flex items-center gap-2">
          <span className="text-[#ffffff]/70 font-bold shrink-0">[admin@{router.name}] &gt;</span>
          <input
            type="text"
            value={cliInput}
            onChange={(e) => setCliInput(e.target.value)}
            placeholder="Type query script here e.g. /ip hotspot user print ... and click Enter"
            className="flex-1 bg-transparent border-0 outline-none p-0 text-[#ffffff] placeholder-[#228B22]/30 font-mono text-xs"
          />
          <button
            type="submit"
            className="p-1 px-3 bg-white border border-[#141414] text-[#141414] font-bold text-xs uppercase rounded-none hover:bg-[#141414] hover:text-white cursor-pointer transition"
          >
            Run
          </button>
        </form>
      </div>
    </div>
  );
}
