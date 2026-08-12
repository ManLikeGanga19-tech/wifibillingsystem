import { useState } from 'react';
import { ArrowDownRight, ArrowUpRight, TrendingUp } from 'lucide-react';
import { api, ksh, type MrrMover } from '../api/client';
import {
  Badge, Empty, ErrorBox, Panel, RefreshBtn, Spinner, Stat, Table, td, useLoad,
} from '../components/ui';

const BUCKET_TONE: Record<MrrMover['bucket'], 'green' | 'red' | 'amber'> = {
  new: 'green',
  expansion: 'green',
  contraction: 'amber',
  churned: 'red',
};

const pct = (r: number | null) => (r === null ? '—' : `${(r * 100).toFixed(1)}%`);
const signed = (v: string | number) => {
  const n = Number(v);
  return `${n >= 0 ? '+' : '−'}${ksh(Math.abs(n))}`;
};

/**
 * Platform growth — is the BUSINESS growing, not just "how much money right now".
 *
 * MRR here is the platform's recurring fee revenue (commission + base + PPPoE per-user).
 * The waterfall splits each month's change into new / expansion / contraction / churned, so
 * a flat MRR that's actually churn-masked-by-new-signups can't hide. The demo tenant is
 * excluded everywhere.
 */
export default function GrowthView() {
  const [months, setMonths] = useState(6);
  const { data, error, reload } = useLoad(() => api.mrrMovement(months), [months]);

  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return <Spinner />;

  const cur = data.months[data.months.length - 1];

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <h1 className="text-lg font-semibold flex items-center gap-2">
          <TrendingUp className="h-5 w-5" /> Growth
        </h1>
        <div className="flex items-center gap-1.5">
          {[3, 6, 12].map((m) => (
            <button
              key={m}
              onClick={() => setMonths(m)}
              className={`px-2.5 py-1 text-xs font-mono border cursor-pointer ${
                months === m ? 'bg-[#141414] text-white border-[#141414]' : 'border-[#141414]/40'
              }`}
            >
              {m}m
            </button>
          ))}
          <RefreshBtn onClick={reload} />
        </div>
      </div>

      {/* This month at a glance */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <Stat label="MRR" value={ksh(cur?.mrr ?? 0)} hint="recurring fees / month" />
        <Stat label="Net new MRR" value={signed(cur?.net ?? 0)} hint="this month" />
        <Stat label="New MRR" value={ksh(cur?.new ?? 0)} hint={`${cur?.new_tenants ?? 0} new tenants`} />
        <Stat label="Churned MRR" value={ksh(cur?.churned ?? 0)} hint={`${cur?.churned_tenants ?? 0} tenants lost`} />
        <Stat label="Tenant churn" value={pct(cur?.tenant_churn_rate ?? null)} hint="of paying ISPs" />
      </div>

      <Panel title="Movement by month" subtitle="New + expansion − contraction − churned = net.">
        <Table head={['Month', 'MRR', 'New', 'Expansion', 'Contraction', 'Churned', 'Net', 'Churn']}>
          {data.months.map((m) => (
            <tr key={m.month}>
              <td className={`${td} font-mono`}>{m.month}</td>
              <td className={`${td} tnum`}>{ksh(m.mrr)}</td>
              <td className={`${td} tnum`} style={{ color: 'var(--good-fg)' }}>{ksh(m.new)}</td>
              <td className={`${td} tnum`} style={{ color: 'var(--good-fg)' }}>{ksh(m.expansion)}</td>
              <td className={`${td} tnum`} style={{ color: 'var(--warning)' }}>{ksh(m.contraction)}</td>
              <td className={`${td} tnum`} style={{ color: 'var(--critical)' }}>{ksh(m.churned)}</td>
              <td className={`${td} tnum font-bold`}>{signed(m.net)}</td>
              <td className={`${td} tnum`}>{pct(m.tenant_churn_rate)}</td>
            </tr>
          ))}
        </Table>
      </Panel>

      <Panel title="Top movers this month" subtitle="The biggest MRR changes, and which ISP.">
        {data.movers.length === 0 ? (
          <Empty message="No MRR changes this month." />
        ) : (
          <Table head={['ISP', 'Change', 'Δ MRR', 'MRR now']}>
            {data.movers.map((mv) => (
              <tr key={mv.operator}>
                <td className={`${td} font-medium`}>{mv.name}</td>
                <td className={td}>
                  <Badge tone={BUCKET_TONE[mv.bucket]}>{mv.bucket}</Badge>
                </td>
                <td className={`${td} tnum`}>
                  <span className="inline-flex items-center gap-1">
                    {Number(mv.delta) >= 0
                      ? <ArrowUpRight className="h-3.5 w-3.5" style={{ color: 'var(--good-fg)' }} />
                      : <ArrowDownRight className="h-3.5 w-3.5" style={{ color: 'var(--critical)' }} />}
                    {signed(mv.delta)}
                  </span>
                </td>
                <td className={`${td} tnum`}>{ksh(mv.mrr)}</td>
              </tr>
            ))}
          </Table>
        )}
      </Panel>
    </div>
  );
}
