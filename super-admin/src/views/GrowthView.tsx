import { useState } from 'react';
import { ArrowDownRight, ArrowUpRight, Filter, TrendingUp } from 'lucide-react';
import { api, ksh, type MrrMover } from '../api/client';
import {
  Badge, Btn, Empty, ErrorBox, Panel, RefreshBtn, Spinner, Stat, Table, td, useLoad,
} from '../components/ui';

const BUCKET_TONE: Record<MrrMover['bucket'], 'green' | 'red' | 'amber'> = {
  new: 'green',
  expansion: 'green',
  contraction: 'amber',
  churned: 'red',
};

const pct = (r: number | null) => (r === null ? '—' : `${(r * 100).toFixed(1)}%`);
const days = (v: number | null) => (v === null ? '—' : `${v}d`);
const signed = (v: string | number) => {
  const n = Number(v);
  return `${n >= 0 ? '+' : '−'}${ksh(Math.abs(n))}`;
};

/**
 * Platform growth — is the BUSINESS growing? Two lenses: REVENUE (are paying ISPs expanding
 * or churning?) and ONBOARDING (do new signups actually turn into revenue, and where do they
 * stall?). The demo tenant is excluded from both.
 */
export default function GrowthView() {
  const [lens, setLens] = useState<'revenue' | 'onboarding'>('revenue');
  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <h1 className="text-lg font-semibold flex items-center gap-2">
          <TrendingUp className="h-5 w-5" /> Growth
        </h1>
        <div className="flex items-center gap-1.5">
          <Btn variant={lens === 'revenue' ? 'dark' : 'outline'} onClick={() => setLens('revenue')}>
            Revenue movement
          </Btn>
          <Btn
            variant={lens === 'onboarding' ? 'dark' : 'outline'}
            onClick={() => setLens('onboarding')}
          >
            Onboarding funnel
          </Btn>
        </div>
      </div>
      {lens === 'revenue' ? <RevenueMovement /> : <OnboardingFunnel />}
    </div>
  );
}

/**
 * MRR is the platform's recurring fee revenue (commission + base + PPPoE per-user). The
 * waterfall splits each month's change into new / expansion / contraction / churned, so a
 * flat MRR that's actually churn-masked-by-new-signups can't hide. Tenant CHURN is separate
 * and precise — it counts real suspension events, not "their MRR hit zero", so a
 * billing-timing gap isn't mistaken for a lost ISP.
 */
function RevenueMovement() {
  const [months, setMonths] = useState(6);
  const { data, error, reload } = useLoad(() => api.mrrMovement(months), [months]);

  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return <Spinner />;

  const cur = data.months[data.months.length - 1];

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-end gap-1.5">
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

      {/* This month at a glance */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <Stat label="MRR" value={ksh(cur?.mrr ?? 0)} hint="recurring fees / month" />
        <Stat label="Net new MRR" value={signed(cur?.net ?? 0)} hint="this month" />
        <Stat label="New MRR" value={ksh(cur?.new ?? 0)} hint={`${cur?.new_tenants ?? 0} new tenants`} />
        <Stat label="Churned MRR" value={ksh(cur?.churned ?? 0)} hint={`${cur?.churned_tenants ?? 0} ISPs suspended`} />
        <Stat
          label="Tenant churn"
          value={pct(cur?.tenant_churn_rate ?? null)}
          hint={`${cur?.churned_tenants ?? 0} of ${cur?.active_tenants ?? 0} live ISPs`}
        />
      </div>

      <Panel
        title="Movement by month"
        subtitle="MRR: new + expansion − contraction − churned = net. Churn %: ISPs actually suspended."
      >
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

const WINDOWS: { label: string; days: number }[] = [
  { label: '30d', days: 30 },
  { label: '90d', days: 90 },
  { label: '1y', days: 365 },
  { label: 'All', days: 0 },
];

/**
 * Onboarding funnel — of the ISPs that signed up in the window, how many reached activated →
 * settlement-verified → first-payment, where they drop off, how long each step takes, and who
 * is stuck RIGHT NOW. Answers "why aren't new signups turning into revenue?"
 */
function OnboardingFunnel() {
  const [win, setWin] = useState(90);
  const { data, error, reload } = useLoad(() => api.onboardingFunnel(win), [win]);

  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return <Spinner />;

  const cohort = data.cohort_size || 1;
  const stuck = data.stuck.pending_over_7d + data.stuck.activated_no_payment_over_14d;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-end gap-1.5">
        {WINDOWS.map((w) => (
          <button
            key={w.days}
            onClick={() => setWin(w.days)}
            className={`px-2.5 py-1 text-xs font-mono border cursor-pointer ${
              win === w.days ? 'bg-[#141414] text-white border-[#141414]' : 'border-[#141414]/40'
            }`}
          >
            {w.label}
          </button>
        ))}
        <RefreshBtn onClick={reload} />
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat
          label="Signups"
          value={String(data.cohort_size)}
          hint={data.window_days ? `last ${data.window_days} days` : 'all time'}
        />
        <Stat
          label="Reached first payment"
          value={pct(data.stages[data.stages.length - 1]?.pct ?? null)}
          hint="of signups, now earning"
        />
        <Stat label="Median time to activate" value={days(data.median_days_to_activate)} hint="signup → live" />
        <Stat
          label="Median time to first payment"
          value={days(data.median_days_to_first_payment)}
          hint="activation → earning"
        />
      </div>

      {stuck > 0 && (
        <div className="panel p-3.5 text-xs flex items-start gap-2" style={{ color: 'var(--warning)' }}>
          <Filter className="h-4 w-4 shrink-0 mt-0.5" />
          <span>
            <b>{data.stuck.pending_over_7d}</b> signed up over a week ago and still aren&apos;t
            activated; <b>{data.stuck.activated_no_payment_over_14d}</b> have been live 2+ weeks
            without a single payment. These are the ISPs to call.
          </span>
        </div>
      )}

      <Panel
        title="Signup → revenue"
        subtitle="Each bar is the share of signups that reached this stage. The gap is where they drop off."
      >
        {data.cohort_size === 0 ? (
          <Empty message="No signups in this window." />
        ) : (
          <div className="space-y-2.5">
            {data.stages.map((s, i) => {
              const width = Math.max(2, Math.round((s.count / cohort) * 100));
              return (
                <div key={s.key} className="flex items-center gap-3">
                  <div className="w-40 shrink-0 text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>
                    {s.label}
                  </div>
                  <div className="flex-1 h-7 relative" style={{ background: 'var(--surface-2)' }}>
                    <div
                      className="h-full flex items-center px-2 text-xs font-mono font-bold"
                      style={{
                        width: `${width}%`,
                        background: i === 0 ? 'var(--accent, #141414)' : 'var(--good-fg)',
                        color: '#fff',
                        transition: 'width .3s',
                      }}
                    >
                      {s.count}
                    </div>
                  </div>
                  <div className="w-28 shrink-0 text-right text-xs tnum" style={{ color: 'var(--text-muted)' }}>
                    {pct(s.pct)}
                    {i > 0 && s.drop_from_prev > 0 && (
                      <span style={{ color: 'var(--critical)' }}> · −{s.drop_from_prev}</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Panel>
    </div>
  );
}
