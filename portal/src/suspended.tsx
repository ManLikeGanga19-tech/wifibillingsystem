import { useEffect, useState } from 'react';
import { WifiOff, Loader2, Search } from 'lucide-react';

interface Notice {
  provider: string;
  paybill: string | null;
  how_to_pay: string;
  client?: {
    account_number: string;
    full_name: string;
    plan: string;
    monthly: string;
    balance: string;
    status: string;
    suspended: boolean;
  };
}

const BASE = (import.meta as { env?: Record<string, string> }).env?.VITE_API_BASE_URL ?? '';

function routerId(): string {
  return new URLSearchParams(window.location.search).get('router') ?? '';
}

/** Page a suspended PPPoE client is redirected to. Shows why they're offline,
 * their balance, and how to pay. */
export default function SuspendedNotice() {
  const [notice, setNotice] = useState<Notice | null>(null);
  const [error, setError] = useState('');
  const [account, setAccount] = useState('');
  const [looking, setLooking] = useState(false);

  const q = (extra = '') => {
    const rid = routerId();
    const parts = [rid ? `router=${rid}` : '', extra].filter(Boolean);
    return parts.length ? `?${parts.join('&')}` : '';
  };

  useEffect(() => {
    const acc = new URLSearchParams(window.location.search).get('account') ?? '';
    fetch(`${BASE}/api/v1/pppoe/suspended-notice/${q(acc ? `account=${acc}` : '')}`)
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then(setNotice)
      .catch(() => setError('Could not load your provider details.'));
  }, []);

  const lookup = async () => {
    if (!account.trim()) return;
    setLooking(true);
    try {
      const r = await fetch(`${BASE}/api/v1/pppoe/account-lookup/${q(`account=${account.trim()}`)}`);
      if (r.ok) {
        const client = await r.json();
        setNotice((n) => (n ? { ...n, client } : n));
      } else {
        setError('Account not found — check the number on your account sheet.');
      }
    } finally {
      setLooking(false);
    }
  };

  return (
    <div className="min-h-screen flex flex-col items-center px-4 py-8">
      <div className="w-full max-w-md space-y-5">
        <div className="bg-white border border-[#141414] p-5 text-center space-y-2">
          <WifiOff className="h-10 w-10 mx-auto text-[#B22222]" />
          <h1 className="font-bold text-lg">Your internet is suspended</h1>
          <p className="text-sm text-[#141414]/70">
            {notice?.provider ? `${notice.provider}: ` : ''}your account is overdue. Pay to
            reconnect — it restores automatically once payment is received.
          </p>
        </div>

        {error && <div className="bg-white border border-[#141414] p-3 text-sm text-[#B22222]">{error}</div>}

        {!notice && !error && (
          <div className="flex justify-center py-8"><Loader2 className="h-8 w-8 animate-spin text-[#141414]/40" /></div>
        )}

        {notice?.client && (
          <div className="bg-white border border-[#141414] p-4 font-mono text-sm space-y-2">
            <Row label="Account" value={notice.client.account_number} big />
            <Row label="Name" value={notice.client.full_name} />
            <Row label="Plan" value={notice.client.plan} />
            <Row label="Monthly" value={`KSh ${Number(notice.client.monthly).toLocaleString()}`} />
            <Row
              label="Balance"
              value={`KSh ${Number(notice.client.balance).toLocaleString()}`}
              danger={Number(notice.client.balance) < 0}
            />
          </div>
        )}

        {notice && !notice.client && (
          <div className="bg-white border border-[#141414] p-4 space-y-2">
            <label className="text-xs font-bold uppercase text-[#141414]/60">Enter your account number</label>
            <div className="flex gap-2">
              <input
                value={account}
                onChange={(e) => setAccount(e.target.value.toUpperCase())}
                placeholder="e.g. HOME04231"
                className="flex-1 border border-[#141414] p-2.5 font-mono uppercase outline-none"
              />
              <button onClick={lookup} disabled={looking} className="bg-[#141414] text-white px-4 flex items-center">
                {looking ? <Loader2 className="h-4 w-4 animate-spin" /> : <Search className="h-4 w-4" />}
              </button>
            </div>
            <p className="text-[11px] text-[#141414]/50">It's on the account sheet your provider gave you.</p>
          </div>
        )}

        {notice && (
          <div className="bg-[#141414] text-[#E4E3E0] p-4 space-y-2">
            <p className="text-xs uppercase opacity-60 font-mono">How to pay (M-Pesa)</p>
            {notice.paybill && (
              <p className="font-mono text-lg">
                Paybill <b className="text-[#7FEF7F]">{notice.paybill}</b>
              </p>
            )}
            <p className="text-sm leading-relaxed">{notice.how_to_pay}</p>
            {notice.client && (
              <p className="text-sm">
                Account: <b className="font-mono">{notice.client.account_number}</b>
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function Row({ label, value, big, danger }: { label: string; value: string; big?: boolean; danger?: boolean }) {
  return (
    <div className="flex justify-between items-center">
      <span className="text-[#141414]/50 text-xs uppercase">{label}</span>
      <span className={`font-bold ${big ? 'text-lg tracking-wider' : ''} ${danger ? 'text-[#B22222]' : ''}`}>{value}</span>
    </div>
  );
}
