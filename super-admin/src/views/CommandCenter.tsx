import { useState } from 'react';
import { AlertTriangle, ArrowRight, Gauge } from 'lucide-react';
import { api, ksh, num, type Kpis } from '../api/client';
import { EarningsChart, SignupChart, StreamChart, VolumeChart } from '../components/charts';
import { Btn, ErrorBox, Panel, RefreshBtn, Spinner, Stat, useLoad, ViewHeader } from '../components/ui';
import { SERIES } from '../components/charts';

const RANGES = [7, 30, 90] as const;

/** Every alert is a number that SHOULD be zero. If it isn't, a human must act —
 * so each one links to the place where you act on it. */
const ALERTS: {
  key: keyof Kpis['alerts'];
  label: string;
  tab: string;
  bad?: boolean;
}[] = [
  { key: 'pending_approvals', label: 'ISPs awaiting approval', tab: 'tenants' },
  { key: 'payouts_stale_2d', label: 'Payouts pending >2 days', tab: 'finance', bad: true },
  { key: 'unmatched_payments', label: 'Payments matching no account', tab: 'ops', bad: true },
  { key: 'trials_expiring_7d', label: 'Trials ending this week', tab: 'tenants' },
  { key: 'routers_offline', label: 'Routers offline', tab: 'ops' },
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
      <ViewHeader
        icon={<Gauge className="h-4.5 w-4.5" />}
        title="Platform Dashboard"
        subtitle="Danamo Tech across every ISP — what we earn, what the rails take, and what needs a human."
      >
        <RefreshBtn
          onClick={() => {
            kpis.reload();
            ts.reload();
          }}
        />
      </ViewHeader>

      {/* ================= CARDS — all of them, up top ================= */}

      {/* The headline: what we actually keep after the rails take their cut. */}
      <div className="bg-white border border-[#141414] p-5">
        <p className="text-[10px] font-bold font-mono uppercase tracking-widest text-[#141414]/60">
          Net margin · this month
        </p>
        <p className="text-4xl font-black font-mono mt-1.5 tnum">{ksh(k.net_margin_month)}</p>
        <p className="text-[11px] font-mono text-[#141414]/60 mt-2">
          {ksh(k.earnings_month)} earned − {ksh(k.transaction_costs_month)} absorbed in M-Pesa /
          bank costs ·{' '}
          <b style={{ color: k.margin_pct >= 50 ? '#228B22' : '#B26B00' }}>{k.margin_pct}% kept</b>
        </p>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat label="MRR" value={ksh(k.mrr)} hint={`${ksh(k.arr)} annualised`} />
        <Stat
          label="Float held for ISPs"
          value={ksh(k.float_held)}
          hint="Their money, in our custody"
        />
        <Stat label="Gross volume" value={ksh(k.gross_volume_month)} hint="Collected this month" />
        <Stat
          label="Active ISPs"
          value={num(k.tenants_active)}
          hint={`${k.new_tenants_30d} joined in 30d`}
        />
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat
          label="Platform earnings"
          value={ksh(k.earnings_month)}
          accent={SERIES.earnings}
          hint="Gross, before rail costs"
        />
        <Stat
          label="Transaction costs"
          value={ksh(k.transaction_costs_month)}
          accent={SERIES.costs}
          hint="Absorbed by us, not the ISP"
        />
        <Stat
          label="Routers online"
          value={`${num(k.routers_online)} / ${num(k.routers_total)}`}
          accent={k.routers_online < k.routers_total ? '#B26B00' : undefined}
        />
        <Stat label="Active sessions" value={num(k.active_sessions)} hint="Customers online now" />
      </div>

      {/* Only rendered when something actually needs a human. */}
      {live.length > 0 && (
        <Panel title="Needs attention">
          <div className="flex flex-col sm:flex-row flex-wrap gap-2">
            {live.map((a) => (
              <button
                key={a.key}
                onClick={() => onNavigate(a.tab)}
                className={`flex items-center gap-2.5 px-3 py-2 border text-[11px] font-mono font-bold uppercase cursor-pointer transition text-left hover:bg-[#141414] hover:text-white ${
                  a.bad
                    ? 'border-[#B22222]/50 text-[#B22222] bg-[#B22222]/5'
                    : 'border-[#B26B00]/50 text-[#B26B00] bg-[#B26B00]/5'
                }`}
              >
                <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
                <span className="text-sm font-black tnum">{k.alerts[a.key]}</span>
                <span>{a.label}</span>
                <ArrowRight className="h-3 w-3 opacity-60" />
              </button>
            ))}
          </div>
        </Panel>
      )}

      {/* ================= GRAPHS — bottom half ================= */}

      <div className="flex items-center justify-between border-t border-[#141414] pt-5">
        <h2 className="text-xs font-bold font-mono uppercase tracking-wide">Trends</h2>
        <div className="flex items-center gap-1.5">
          {RANGES.map((r) => (
            <Btn key={r} variant={days === r ? 'dark' : 'outline'} onClick={() => setDays(r)}>
              {r}d
            </Btn>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">
        <Panel
          title="Where the money goes"
          subtitle="What we keep vs what the rails take back — the true cost of being an aggregator."
        >
          {ts.data ? <EarningsChart series={ts.data.series} /> : <Spinner />}
        </Panel>

        <Panel
          title="Gross volume collected"
          subtitle="All ISPs' customer payments, held in our custody"
        >
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
    </div>
  );
}
