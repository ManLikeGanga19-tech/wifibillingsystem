import { useState } from 'react';
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Building2,
  Radio,
  TrendingUp,
  Wallet,
} from 'lucide-react';
import { api, ksh, num, type Kpis } from '../api/client';
import { EarningsChart, SignupChart, StreamChart, VolumeChart } from '../components/charts';
import { Btn, ErrorBox, Panel, RefreshBtn, Spinner, Stat, useLoad } from '../components/ui';

const RANGES = [7, 30, 90] as const;

/** Every alert is a number that SHOULD be zero. If it isn't, a human must act —
 * so each one is a link to the place where you act on it. */
const ALERTS: {
  key: keyof Kpis['alerts'];
  label: string;
  tab: string;
  tone: 'warning' | 'critical';
}[] = [
  { key: 'pending_approvals', label: 'ISPs awaiting approval', tab: 'tenants', tone: 'warning' },
  { key: 'payouts_stale_2d', label: 'Payouts pending >2 days', tab: 'finance', tone: 'critical' },
  { key: 'unmatched_payments', label: 'Payments matching no account', tab: 'search', tone: 'critical' },
  { key: 'trials_expiring_7d', label: 'Trials ending this week', tab: 'tenants', tone: 'warning' },
  { key: 'routers_offline', label: 'Routers offline', tab: 'tenants', tone: 'warning' },
];

export default function CommandCenter({ onNavigate }: { onNavigate: (tab: string) => void }) {
  const [days, setDays] = useState<number>(30);
  const kpis = useLoad(() => api.kpis(), []);
  const ts = useLoad(() => api.timeseries(days), [days]);

  if (kpis.error) return <ErrorBox message={kpis.error} onRetry={kpis.reload} />;
  if (!kpis.data) return <Spinner />;
  const k = kpis.data;

  const live = ALERTS.filter((a) => k.alerts[a.key] > 0);

  return (
    <div className="space-y-5">
      {/* ---- Hero: the one number that matters, and what it cost to get it ---- */}
      <section className="panel sheen p-5 sm:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p
              className="text-[11px] uppercase tracking-[0.2em] mb-2"
              style={{ color: 'var(--accent)' }}
            >
              Net margin · this month
            </p>
            <p className="text-4xl sm:text-5xl font-semibold tracking-tight">
              {ksh(k.net_margin_month)}
            </p>
            <p className="text-xs mt-2.5" style={{ color: 'var(--text-secondary)' }}>
              {ksh(k.earnings_month)} earned − {ksh(k.transaction_costs_month)} absorbed in M-Pesa
              / bank costs
              <span className="mx-2" style={{ color: 'var(--hairline-strong)' }}>
                |
              </span>
              <span style={{ color: k.margin_pct >= 50 ? '#3ecf3e' : 'var(--warning)' }}>
                {k.margin_pct}% kept
              </span>
            </p>
          </div>
          <div className="flex items-center gap-2 text-xs" style={{ color: 'var(--text-muted)' }}>
            <span className="h-2 w-2 rounded-full pulse" style={{ background: 'var(--accent)' }} />
            LIVE
            <RefreshBtn
              onClick={() => {
                kpis.reload();
                ts.reload();
              }}
            />
          </div>
        </div>

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mt-6">
          <Stat label="MRR" value={ksh(k.mrr)} hint={`${ksh(k.arr)} annualised`} />
          <Stat
            label="Float held for ISPs"
            value={ksh(k.float_held)}
            hint="Their money, in our custody"
          />
          <Stat
            label="Gross volume"
            value={ksh(k.gross_volume_month)}
            hint="Collected this month"
          />
          <Stat
            label="Active ISPs"
            value={num(k.tenants_active)}
            hint={`${k.new_tenants_30d} joined in 30d`}
          />
        </div>
      </section>

      {/* ---- Alerts: only rendered when something actually needs a human ---- */}
      {live.length > 0 && (
        <section className="panel p-4">
          <h2 className="text-[11px] uppercase tracking-wider mb-3 flex items-center gap-1.5">
            <AlertTriangle className="h-3.5 w-3.5" style={{ color: 'var(--warning)' }} />
            <span style={{ color: 'var(--text-secondary)' }}>Needs attention</span>
          </h2>
          <div className="flex flex-col sm:flex-row flex-wrap gap-2">
            {live.map((a) => (
              <button
                key={a.key}
                onClick={() => onNavigate(a.tab)}
                className="flex items-center gap-2.5 px-3 py-2 rounded-lg text-xs cursor-pointer transition hover:brightness-125 text-left"
                style={{
                  background:
                    a.tone === 'critical' ? 'rgba(208,59,59,0.12)' : 'rgba(250,178,25,0.10)',
                  color: a.tone === 'critical' ? '#f07373' : '#fab219',
                }}
              >
                <span className="text-base font-semibold tnum">{k.alerts[a.key]}</span>
                <span>{a.label}</span>
                <ArrowRight className="h-3 w-3 opacity-60" />
              </button>
            ))}
          </div>
        </section>
      )}

      {/* ---- Range filter: one row above the charts ---- */}
      <div className="flex items-center gap-1.5">
        {RANGES.map((r) => (
          <Btn key={r} variant={days === r ? 'primary' : 'ghost'} onClick={() => setDays(r)}>
            {r}d
          </Btn>
        ))}
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        <Panel
          title="Where the money goes"
          subtitle="What we keep vs what the rails take back. The gap is the true cost of being an aggregator."
        >
          {ts.data ? <EarningsChart series={ts.data.series} /> : <Spinner />}
        </Panel>

        <Panel title="Gross volume collected" subtitle="All ISPs' customer payments, in our custody">
          {ts.data ? <VolumeChart series={ts.data.series} /> : <Spinner />}
        </Panel>

        <Panel
          title="Revenue by stream"
          subtitle="Which part of the pricing model is actually earning, this month"
        >
          <StreamChart streams={k.revenue_by_stream} />
        </Panel>

        <Panel title="New ISPs" subtitle="Signups per day">
          {ts.data ? <SignupChart series={ts.data.series} /> : <Spinner />}
        </Panel>
      </div>

      {/* ---- Fleet strip ---- */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat
          label="Routers online"
          value={`${num(k.routers_online)} / ${num(k.routers_total)}`}
          accent={k.routers_online < k.routers_total ? 'var(--warning)' : undefined}
        />
        <Stat label="Active sessions" value={num(k.active_sessions)} />
        <Stat label="Payouts pending" value={num(k.alerts.payouts_pending)} />
        <Stat label="ISPs (all states)" value={num(k.tenants_total)} />
      </div>

      <div className="flex flex-wrap gap-2">
        <Btn onClick={() => onNavigate('finance')}>
          <TrendingUp className="h-3.5 w-3.5" /> Tenant P&amp;L
        </Btn>
        <Btn onClick={() => onNavigate('tenants')}>
          <Building2 className="h-3.5 w-3.5" /> ISPs
        </Btn>
        <Btn onClick={() => onNavigate('governance')}>
          <Activity className="h-3.5 w-3.5" /> Audit trail
        </Btn>
        <Btn onClick={() => onNavigate('search')}>
          <Radio className="h-3.5 w-3.5" /> Search
        </Btn>
        <Btn onClick={() => onNavigate('finance')}>
          <Wallet className="h-3.5 w-3.5" /> Payouts
        </Btn>
      </div>
    </div>
  );
}
