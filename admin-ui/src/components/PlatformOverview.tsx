import { useCallback, useEffect, useState } from 'react';
import { Globe, Loader2, AlertTriangle } from 'lucide-react';
import { api, PlatformOverview as Overview } from '../api/client';
import { Btn, Panel, RefreshBtn, ViewHeader, fmtKsh } from './ui';

/** Cross-tenant numbers. Every figure here is explicitly ACROSS ALL ISPs — this is
 * the only screen allowed to aggregate tenants, and it says so loudly. */
export default function PlatformOverview({ onNavigate }: { onNavigate: (tab: string) => void }) {
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    try {
      setData(await api.platform.overview());
      setError('');
    } catch {
      setError('Could not load platform overview.');
    }
  }, []);

  useEffect(() => {
    load();
    const t = window.setInterval(load, 30_000);
    return () => window.clearInterval(t);
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
    return (
      <div className="flex justify-center py-24">
        <Loader2 className="h-8 w-8 animate-spin text-[#141414]/40" />
      </div>
    );

  return (
    <div className="space-y-5 text-[#141414]">
      <ViewHeader
        icon={<Globe className="h-4.5 w-4.5" />}
        title="Platform Overview"
        subtitle="Danamo Tech — totals ACROSS ALL ISPs on the platform. Not any single ISP's numbers."
      >
        <RefreshBtn onClick={load} />
      </ViewHeader>

      <div className="border border-[#2563EB]/40 bg-[#2563EB]/5 px-3 py-2 text-[11px] font-mono uppercase tracking-wide text-[#2563EB]">
        Scope: all ISPs combined
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Tile label="Platform Revenue (mo)" value={fmtKsh(data.platform_revenue_month)} accent />
        <Tile label="Gross Volume (mo)" value={fmtKsh(data.gross_volume_month)} sub={`${data.transactions_month} payments`} />
        <Tile label="Active ISPs" value={String(data.tenants_active)} sub={`${data.tenants_total} total`} />
        <Tile
          label="Pending Approval"
          value={String(data.tenants_pending)}
          sub={data.tenants_pending > 0 ? 'needs your review' : 'all clear'}
        />
        <Tile label="Routers Online" value={`${data.routers_online}/${data.routers_total}`} />
        <Tile label="Active Sessions" value={String(data.active_sessions)} sub="customers online now" />
        <Tile label="New ISPs (30d)" value={String(data.new_tenants_30d)} />
        <Tile label="Suspended ISPs" value={String(data.tenants_suspended)} />
      </div>

      {data.tenants_pending > 0 && (
        <Panel>
          <div className="flex items-center justify-between gap-4">
            <p className="text-xs font-mono">
              <b>{data.tenants_pending}</b> ISP application(s) waiting for your approval.
            </p>
            <Btn onClick={() => onNavigate('platform_tenants')}>Review applications</Btn>
          </div>
        </Panel>
      )}
    </div>
  );
}

function Tile({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: boolean }) {
  return (
    <div className="bg-white border border-[#141414] p-3.5">
      <p className="text-[11px] font-mono uppercase text-[#141414]/60">{label}</p>
      <p className={`text-xl font-black font-mono mt-1 leading-none ${accent ? 'text-[#228B22]' : ''}`}>{value}</p>
      {sub && <p className="text-[11px] font-mono text-[#141414]/50 mt-1.5">{sub}</p>}
    </div>
  );
}
