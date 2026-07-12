import { useCallback, useEffect, useState } from 'react';
import { Receipt, RefreshCw, Loader2, AlertTriangle, Wifi, CheckCircle2 } from 'lucide-react';
import { api, ApiTransaction } from '../api/client';
import { toast } from './ui';

const STATUS_STYLE: Record<ApiTransaction['status'], string> = {
  success: 'text-[#228B22] border-[#228B22]/40 bg-[#228B22]/5',
  reconciled: 'text-[#228B22] border-[#228B22]/40 bg-[#228B22]/5',
  pending: 'text-[#141414]/70 border-[#141414]/30 bg-[#141414]/5',
  failed: 'text-[#B22222] border-[#B22222]/40 bg-[#B22222]/5',
  timeout: 'text-[#B26B00] border-[#B26B00]/40 bg-[#B26B00]/5',
};

const FILTERS = ['all', 'success', 'pending', 'failed', 'timeout'] as const;

export default function TransactionsView() {
  const [rows, setRows] = useState<ApiTransaction[] | null>(null);
  const [count, setCount] = useState(0);
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('all');
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  // The "paid but never connected" queue — the customers who paid and are stuck.
  const [unconnected, setUnconnected] = useState<ApiTransaction[]>([]);
  const [reconnecting, setReconnecting] = useState<number | null>(null);

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      const [resp, stuck] = await Promise.all([
        api.transactions.list(filter === 'all' ? undefined : filter),
        api.transactions.unconnected(),
      ]);
      setRows(resp.results);
      setCount(resp.count);
      setUnconnected(stuck.results);
      setError('');
    } catch {
      setError('Could not load transactions.');
    } finally {
      setRefreshing(false);
    }
  }, [filter]);

  useEffect(() => {
    setRows(null);
    load();
    const t = window.setInterval(load, 10_000);
    return () => window.clearInterval(t);
  }, [load]);

  const reconnect = async (tx: ApiTransaction) => {
    if (reconnecting) return;
    setReconnecting(tx.id);
    try {
      const r = await api.transactions.reconnect(tx.id);
      toast('success', r.detail);
      load();
    } catch (e) {
      toast('error', e instanceof Error ? e.message : 'Could not reconnect them.');
    } finally {
      setReconnecting(null);
    }
  };

  return (
    <div className="space-y-6 text-[#141414]">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-sm font-serif italic font-bold flex items-center gap-2 uppercase">
            <Receipt className="h-4.5 w-4.5" />
            <span>M-Pesa Transactions</span>
          </h2>
          <p className="text-xs font-mono text-[#141414]/70 mt-0.5">
            Live payment feed straight from the Daraja gateway. Refreshes every 10 seconds.
          </p>
        </div>
        <button
          onClick={load}
          className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-bold font-mono border border-[#141414] hover:bg-[#141414] hover:text-white transition cursor-pointer self-start uppercase"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* THE STUCK-CUSTOMER QUEUE. They paid — including payments that only landed via
          reconciliation — but never got online. This is the one screen an ISP needs to
          rescue a far-away customer. Reconnecting grants a fresh full window, because
          they paid and got nothing. */}
      {unconnected.length > 0 && (
        <div className="border border-[#B26B00] bg-[#FFF8EC]">
          <div className="flex items-center gap-2 px-3 py-2.5 border-b border-[#B26B00]/40">
            <AlertTriangle className="h-4 w-4 text-[#B26B00]" />
            <p className="text-xs font-bold font-mono uppercase text-[#B26B00]">
              {unconnected.length} paid customer{unconnected.length > 1 ? 's' : ''} not connected
            </p>
          </div>
          <div className="divide-y divide-[#B26B00]/15">
            {unconnected.map((tx) => (
              <div key={tx.id} className="flex items-center gap-3 px-3 py-2.5 text-xs">
                <div className="flex-1 min-w-0">
                  <p className="font-mono font-bold">{tx.phone}</p>
                  <p className="text-[#141414]/60 font-mono">
                    {tx.plan_name} · KSh {Number(tx.amount).toLocaleString()}
                    {tx.mpesa_receipt && ` · ${tx.mpesa_receipt}`}
                    {tx.status === 'reconciled' && ' · reconciled'}
                  </p>
                </div>
                <button
                  onClick={() => reconnect(tx)}
                  disabled={reconnecting === tx.id}
                  className="inline-flex items-center gap-1.5 px-3 py-2 font-bold font-mono uppercase border border-[#228B22] bg-[#228B22] text-white hover:opacity-85 transition cursor-pointer disabled:opacity-40 shrink-0"
                >
                  {reconnecting === tx.id ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Wifi className="h-3.5 w-3.5" />
                  )}
                  Reconnect
                </button>
              </div>
            ))}
          </div>
          <p className="px-3 py-2 text-[10px] font-mono text-[#141414]/50 border-t border-[#B26B00]/15">
            Reconnecting starts their time over from now — they keep the full plan they paid for.
          </p>
        </div>
      )}

      {/* Status filter */}
      <div className="flex flex-wrap gap-1.5">
        {FILTERS.map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`px-3 py-1.5 border text-xs font-bold font-mono uppercase transition cursor-pointer ${
              filter === f ? 'bg-[#141414] text-[#E4E3E0] border-[#141414]' : 'bg-white border-[#141414]/40 hover:border-[#141414]'
            }`}
          >
            {f}
          </button>
        ))}
        <span className="ml-auto self-center text-[11px] font-mono text-[#141414]/50">{count} total</span>
      </div>

      <div className="bg-white border border-[#141414] overflow-x-auto">
        {error && (
          <p className="p-6 text-center text-xs font-mono text-[#B22222] flex items-center justify-center gap-2">
            <AlertTriangle className="h-4 w-4" /> {error}
          </p>
        )}
        {!error && rows === null && (
          <div className="flex justify-center py-16">
            <Loader2 className="h-6 w-6 animate-spin text-[#141414]/40" />
          </div>
        )}
        {!error && rows !== null && rows.length === 0 && (
          <p className="p-8 text-center text-xs font-mono text-[#141414]/50">No transactions match this filter yet.</p>
        )}
        {!error && rows !== null && rows.length > 0 && (
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-[#141414] font-mono text-[11px] uppercase text-[#141414]/60">
                <th className="py-2.5 px-3">Time</th>
                <th className="py-2.5 px-3">Phone</th>
                <th className="py-2.5 px-3">Plan</th>
                <th className="py-2.5 px-3 text-right">Amount</th>
                <th className="py-2.5 px-3">Status</th>
                <th className="py-2.5 px-3">Connected</th>
                <th className="py-2.5 px-3">Receipt</th>
                <th className="py-2.5 px-3">Detail</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#141414]/10">
              {rows.map((tx) => (
                <tr key={tx.id} className="text-xs hover:bg-[#f0efec]/40 transition">
                  <td className="py-2.5 px-3 font-mono whitespace-nowrap">
                    {new Date(tx.created_at).toLocaleString('en-KE', {
                      day: '2-digit',
                      month: 'short',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </td>
                  <td className="py-2.5 px-3 font-mono">{tx.phone}</td>
                  <td className="py-2.5 px-3">{tx.plan_name}</td>
                  <td className="py-2.5 px-3 text-right font-mono font-bold whitespace-nowrap">
                    KSh {Number(tx.amount).toLocaleString()}
                  </td>
                  <td className="py-2.5 px-3">
                    <span className={`inline-block px-1.5 py-0.5 border text-[11px] font-bold font-mono uppercase ${STATUS_STYLE[tx.status]}`}>
                      {tx.status}
                    </span>
                  </td>
                  <td className="py-2.5 px-3">
                    {tx.status !== 'success' && tx.status !== 'reconciled' ? (
                      <span className="text-[#141414]/30">—</span>
                    ) : tx.provisioning === 'active' ? (
                      <span className="inline-flex items-center gap-1 text-[#228B22] font-mono text-[11px]">
                        <CheckCircle2 className="h-3.5 w-3.5" /> online
                      </span>
                    ) : tx.provisioning === 'failed' ? (
                      <button
                        onClick={() => reconnect(tx)}
                        disabled={reconnecting === tx.id}
                        className="inline-flex items-center gap-1 text-[#B26B00] font-mono text-[11px] font-bold underline underline-offset-2 cursor-pointer disabled:opacity-40"
                      >
                        {reconnecting === tx.id ? (
                          <Loader2 className="h-3 w-3 animate-spin" />
                        ) : (
                          <Wifi className="h-3 w-3" />
                        )}
                        reconnect
                      </button>
                    ) : (
                      <span className="text-[#141414]/50 font-mono text-[11px]">connecting…</span>
                    )}
                  </td>
                  <td className="py-2.5 px-3 font-mono">{tx.mpesa_receipt || '—'}</td>
                  <td className="py-2.5 px-3 text-[#141414]/60 max-w-[16rem] truncate" title={tx.result_desc}>
                    {tx.result_desc || '—'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
