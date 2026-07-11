import { useCallback, useEffect, useState } from 'react';
import { Scale, Loader2, AlertTriangle } from 'lucide-react';
import { api, Reconciliation } from '../api/client';
import { Btn, RefreshBtn, ViewHeader, fmtKsh } from './ui';

/** The aggregator balance sheet: what Danamo holds and owes across ALL ISPs. */
export default function ReconciliationView() {
  const [data, setData] = useState<Reconciliation | null>(null);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      setData(await api.platform.reconciliation());
      setError('');
    } catch {
      setError('Could not load reconciliation.');
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (error)
    return (
      <div className="bg-white border border-[#141414] p-8 text-center space-y-3">
        <AlertTriangle className="h-8 w-8 mx-auto text-[#B22222]" />
        <p className="text-sm font-mono">{error}</p>
        <Btn onClick={load}>Retry</Btn>
      </div>
    );

  if (!data)
    return <div className="flex justify-center py-24"><Loader2 className="h-8 w-8 animate-spin text-[#141414]/40" /></div>;

  return (
    <div className="space-y-5 text-[#141414]">
      <ViewHeader
        icon={<Scale className="h-4.5 w-4.5" />}
        title="Reconciliation"
        subtitle="Danamo Tech's custody position across ALL ISPs — money collected, owed, and disbursed."
      >
        <RefreshBtn onClick={load} />
      </ViewHeader>

      <div className="border border-[#2563EB]/40 bg-[#2563EB]/5 px-3 py-2 text-[11px] font-mono uppercase tracking-wide text-[#2563EB]">
        Scope: all ISPs combined — this is the platform's money position, not any one ISP's
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Big label="Current Float (owed to ISPs)" value={fmtKsh(data.current_float)} accent
          hint="What Danamo is holding on behalf of ISPs right now — should match your bank/M-Pesa balance minus your own earnings." />
        <Big label="Net Margin (after rails)" value={fmtKsh(data.net_margin)} accent
          hint="True take-home: gross platform fees minus the estimated M-Pesa/bank transaction costs the platform absorbs." />
      </div>

      {/* True-margin waterfall: gross fees → what the rails take → net */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <Tile label="Gross Platform Earnings" value={fmtKsh(data.platform_earnings)} />
        <Tile label="− Transaction Costs" value={fmtKsh(data.transaction_costs)} sub={`collect ${fmtKsh(data.collection_costs)} · payout ${fmtKsh(data.payout_costs)}`} negative />
        <Tile label="= Net Margin" value={fmtKsh(data.net_margin)} accent />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Tile label="Total Collected" value={fmtKsh(data.total_collected)} />
        <Tile label="Owed to ISPs" value={fmtKsh(data.owed_to_isps)} />
        <Tile label="Total Disbursed" value={fmtKsh(data.total_disbursed)} />
        <Tile label="Pending Payouts" value={fmtKsh(data.pending_payouts)} />
      </div>

      <p className="text-[11px] font-mono text-[#141414]/50 leading-relaxed">
        Identity: <b>collected − platform earnings − disbursed = float owed to ISPs</b>. Transaction
        costs are <b>estimated</b> from the tariff table and trued-up monthly against the M-Pesa/I&M
        statement. When you automate payouts (I&M), disbursed rises and float falls as ISPs are paid.
      </p>
    </div>
  );
}

function Big({ label, value, hint, accent }: { label: string; value: string; hint: string; accent?: boolean }) {
  return (
    <div className="bg-white border border-[#141414] p-4">
      <p className="text-[11px] font-mono uppercase text-[#141414]/60">{label}</p>
      <p className={`text-2xl font-black font-mono mt-1 ${accent ? 'text-[#228B22]' : ''}`}>{value}</p>
      <p className="text-[11px] font-mono text-[#141414]/50 mt-2 leading-relaxed">{hint}</p>
    </div>
  );
}

function Tile({ label, value, sub, accent, negative }: { label: string; value: string; sub?: string; accent?: boolean; negative?: boolean }) {
  return (
    <div className="bg-white border border-[#141414] p-3.5">
      <p className="text-[11px] font-mono uppercase text-[#141414]/60">{label}</p>
      <p className={`text-lg font-black font-mono mt-1 ${accent ? 'text-[#228B22]' : negative ? 'text-[#B22222]' : ''}`}>{value}</p>
      {sub && <p className="text-[10px] font-mono text-[#141414]/45 mt-1">{sub}</p>}
    </div>
  );
}
