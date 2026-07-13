import { useCallback, useEffect, useState } from 'react';
import { BarChart3, Download, Loader2 } from 'lucide-react';
import { api, RevenueReport } from '../api/client';
import { fmtKsh, inputCls, Panel, RefreshBtn, ViewHeader } from './ui';

/** yyyy-mm-dd for <input type=date> and the API. */
const iso = (d: Date) => d.toISOString().slice(0, 10);

/**
 * Reports & exports — the numbers an ISP runs the business on, plus the CSVs an
 * accountant reconciles against the M-Pesa statement. Pick a range, see the split, and
 * download the raw rows.
 */
export default function ReportsView() {
  const today = new Date();
  const monthAgo = new Date(today.getTime() - 30 * 864e5);
  const [from, setFrom] = useState(iso(monthAgo));
  const [to, setTo] = useState(iso(today));
  const [report, setReport] = useState<RevenueReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setReport(await api.reports.revenue(from, to));
      setError('');
    } catch {
      setError('Could not load the report.');
    } finally {
      setLoading(false);
    }
  }, [from, to]);

  useEffect(() => {
    load();
  }, [load]);

  const peak = Math.max(1, ...(report?.daily.map((d) => d.revenue) ?? [1]));

  return (
    <div className="space-y-5 text-[#141414]">
      <ViewHeader
        icon={<BarChart3 className="h-4.5 w-4.5" />}
        title="Reports"
        subtitle="Revenue over any period, split by source and plan. Export the raw payments to reconcile against your M-Pesa statement."
      >
        <RefreshBtn onClick={load} spinning={loading} />
      </ViewHeader>

      {/* Range picker */}
      <div className="flex flex-wrap items-end gap-3 bg-white border border-[#141414] p-3.5">
        <label className="block">
          <span className="text-[10px] font-bold font-mono uppercase text-[#141414]/60">From</span>
          <input type="date" value={from} max={to} onChange={(e) => setFrom(e.target.value)} className={inputCls} />
        </label>
        <label className="block">
          <span className="text-[10px] font-bold font-mono uppercase text-[#141414]/60">To</span>
          <input type="date" value={to} min={from} max={iso(today)} onChange={(e) => setTo(e.target.value)} className={inputCls} />
        </label>
        <div className="ml-auto flex flex-wrap gap-2">
          <ExportBtn kind="transactions" from={from} to={to} label="Hotspot payments" />
          <ExportBtn kind="pppoe-payments" from={from} to={to} label="PPPoE payments" />
          <ExportBtn kind="ledger" from={from} to={to} label="Wallet ledger" />
        </div>
      </div>

      {error && <p className="text-xs font-mono text-[#B22222]">{error}</p>}

      {report && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Kpi label="Total revenue" value={fmtKsh(report.total)} accent />
            <Kpi label="Hotspot" value={fmtKsh(report.hotspot_total)} sub={`${report.hotspot_count} payments`} />
            <Kpi label="PPPoE" value={fmtKsh(report.pppoe_total)} sub={`${report.pppoe_count} payments`} />
            <Kpi
              label="Busiest day"
              value={fmtKsh(peak)}
              sub={report.daily.length ? 'in this range' : '—'}
            />
          </div>

          <Panel title="Daily revenue">
            {report.daily.length === 0 ? (
              <p className="text-xs font-mono text-[#141414]/50 py-6 text-center">No revenue in this range.</p>
            ) : (
              <div className="flex items-end gap-1 h-40 overflow-x-auto pt-2">
                {report.daily.map((d) => (
                  <div key={d.day} className="flex flex-col items-center gap-1 shrink-0" style={{ width: 26 }} title={`${d.day}: ${fmtKsh(d.revenue)}`}>
                    <div
                      className="w-full bg-[#228B22]"
                      style={{ height: `${Math.max(2, (d.revenue / peak) * 130)}px` }}
                    />
                    <span className="text-[8px] font-mono text-[#141414]/40 rotate-45 origin-left whitespace-nowrap">
                      {d.day.slice(5)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </Panel>

          <Panel title="By plan">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-[#141414] font-mono text-[11px] uppercase text-[#141414]/60">
                  <th className="py-2 px-2">Plan</th>
                  <th className="py-2 px-2 text-right">Payments</th>
                  <th className="py-2 px-2 text-right">Revenue</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#141414]/10">
                {report.by_plan.length === 0 ? (
                  <tr><td colSpan={3} className="py-6 text-center font-mono text-[#141414]/50">No hotspot sales in this range.</td></tr>
                ) : (
                  report.by_plan.map((p) => (
                    <tr key={p.plan}>
                      <td className="py-2 px-2 font-bold">{p.plan}</td>
                      <td className="py-2 px-2 text-right font-mono">{p.count}</td>
                      <td className="py-2 px-2 text-right font-mono font-bold">{fmtKsh(p.revenue)}</td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </Panel>
        </>
      )}

      {!report && loading && (
        <div className="flex justify-center py-16">
          <Loader2 className="h-6 w-6 animate-spin text-[#141414]/40" />
        </div>
      )}
    </div>
  );
}

function Kpi({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: boolean }) {
  return (
    <div className="bg-white border border-[#141414] p-3.5">
      <p className="text-[11px] font-mono uppercase text-[#141414]/60">{label}</p>
      <p className={`text-xl font-black font-mono mt-1 ${accent ? 'text-[#228B22]' : ''}`}>{value}</p>
      {sub && <p className="text-[10px] font-mono text-[#141414]/50 mt-0.5">{sub}</p>}
    </div>
  );
}

function ExportBtn({ kind, from, to, label }: { kind: 'transactions' | 'pppoe-payments' | 'ledger'; from: string; to: string; label: string }) {
  return (
    <a
      href={api.reports.csvUrl(kind, from, to)}
      className="inline-flex items-center gap-1.5 px-3 py-2 text-[11px] font-bold font-mono uppercase border border-[#141414] bg-white hover:bg-[#f0efec] transition cursor-pointer"
    >
      <Download className="h-3.5 w-3.5" />
      {label}
    </a>
  );
}
