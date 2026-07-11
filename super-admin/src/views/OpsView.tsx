import { AlertOctagon, AlertTriangle, CheckCircle2, Cpu, RadioTower } from 'lucide-react';
import { api, ksh, num, type HealthCheck, type HealthState } from '../api/client';
import { ErrorBox, Panel, RefreshBtn, Spinner, Stat, useLoad } from '../components/ui';

/**
 * System health.
 *
 * Not a metrics dump — a set of questions that have a right answer. Every check
 * is ranked by what actually hurts, and the worst one decides the board. The
 * check at the top is the one that matters most: a customer who PAID and has no
 * internet.
 */

const STATE: Record<
  HealthState,
  { color: string; bg: string; label: string; Icon: typeof CheckCircle2 }
> = {
  ok: { color: '#3ecf3e', bg: 'rgba(12,163,12,0.12)', label: 'Healthy', Icon: CheckCircle2 },
  warn: { color: '#fab219', bg: 'rgba(250,178,25,0.12)', label: 'Degraded', Icon: AlertTriangle },
  crit: { color: '#f07373', bg: 'rgba(208,59,59,0.14)', label: 'Critical', Icon: AlertOctagon },
};

export default function OpsView() {
  const { data, error, reload } = useLoad(() => api.health(), []);

  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return <Spinner />;

  const s = STATE[data.status];
  const { Icon } = s;

  return (
    <div className="space-y-5">
      {/* ---- verdict ---- */}
      <section className="panel sheen p-5 flex flex-wrap items-center justify-between gap-4">
        <div className="flex items-center gap-4">
          <div
            className="h-12 w-12 rounded-xl flex items-center justify-center shrink-0"
            style={{ background: s.bg }}
          >
            <Icon className="h-6 w-6" style={{ color: s.color }} />
          </div>
          <div>
            <p
              className="text-[11px] uppercase tracking-[0.2em]"
              style={{ color: 'var(--text-muted)' }}
            >
              System status
            </p>
            <p className="text-2xl font-semibold" style={{ color: s.color }}>
              {s.label}
            </p>
          </div>
        </div>
        <RefreshBtn onClick={reload} />
      </section>

      {/* ---- the checks, worst first ---- */}
      <Panel
        title="Checks"
        subtitle="Ordered by what actually hurts. Each of these should read zero."
      >
        <div className="space-y-2">
          {[...data.checks]
            .sort((a, b) => rank(b.state) - rank(a.state))
            .map((c) => (
              <CheckRow key={c.key} c={c} />
            ))}
        </div>
      </Panel>

      {/* ---- money integrity ---- */}
      <Panel
        title="Money integrity"
        subtitle="Customer money that is stranded, and customers who paid but got nothing."
      >
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
          <Stat
            label="Paid, no service"
            value={num(data.money.undelivered_service)}
            accent={data.money.undelivered_service ? '#f07373' : undefined}
            hint="Provisioning failed or never ran"
          />
          <Stat
            label="Unmatched payments"
            value={num(data.money.unmatched_payments)}
            accent={data.money.unmatched_payments ? '#f07373' : undefined}
            hint="Arrived with an unknown account number"
          />
          <Stat
            label="Unattributed value"
            value={ksh(data.money.unmatched_value)}
            hint="Real money sitting with no owner"
          />
          <Stat
            label="Awaiting callback"
            value={num(data.money.stuck_payments)}
            accent={data.money.stuck_payments ? '#fab219' : undefined}
            hint="The reconciliation sweep should clear these"
          />
        </div>
      </Panel>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* ---- fleet ---- */}
        <Panel
          title="Router fleet"
          subtitle="Across every ISP"
          right={<RadioTower className="h-4 w-4" style={{ color: 'var(--text-muted)' }} />}
        >
          <div className="grid grid-cols-2 gap-3">
            <Stat
              label="Online"
              value={`${num(data.fleet.online)} / ${num(data.fleet.total)}`}
              accent={data.fleet.online === data.fleet.total ? '#3ecf3e' : '#fab219'}
            />
            <Stat
              label="Offline"
              value={num(data.fleet.offline)}
              accent={data.fleet.offline ? '#f07373' : undefined}
            />
            <Stat
              label="Needs re-onboarding"
              value={num(data.fleet.needs_reonboarding)}
              accent={data.fleet.needs_reonboarding ? '#fab219' : undefined}
              hint="Credentials rejected — likely factory reset"
            />
            <Stat
              label="Not seen recently"
              value={num(data.fleet.stale)}
              hint="No contact in over 2 hours"
            />
          </div>
        </Panel>

        {/* ---- workers ---- */}
        <Panel
          title="Background workers"
          subtitle="Celery runs provisioning, reconciliation, invoicing and suspension"
          right={<Cpu className="h-4 w-4" style={{ color: 'var(--text-muted)' }} />}
        >
          <div className="grid grid-cols-2 gap-3">
            <Stat
              label="Workers responding"
              value={num(data.workers.count)}
              accent={data.workers.reachable ? '#3ecf3e' : '#f07373'}
              size="lg"
            />
            <div className="panel-flat p-4">
              <p
                className="text-[11px] uppercase tracking-wider mb-1.5"
                style={{ color: 'var(--text-muted)' }}
              >
                Nodes
              </p>
              {data.workers.names.length ? (
                data.workers.names.map((n) => (
                  <p key={n} className="text-[11px] tnum truncate" title={n}>
                    {n}
                  </p>
                ))
              ) : (
                <p className="text-xs" style={{ color: '#f07373' }}>
                  No workers responding — nothing is being provisioned or billed.
                </p>
              )}
            </div>
          </div>
        </Panel>
      </div>
    </div>
  );
}

const rank = (s: HealthState) => ({ ok: 0, warn: 1, crit: 2 })[s];

function CheckRow({ c }: { c: HealthCheck }) {
  const s = STATE[c.state];
  const { Icon } = s;
  return (
    <div
      className="flex items-start gap-3 p-3 rounded-lg"
      style={{ background: c.state === 'ok' ? 'transparent' : s.bg }}
    >
      <Icon className="h-4 w-4 shrink-0 mt-0.5" style={{ color: s.color }} />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-medium">{c.label}</span>
          <span className="tnum text-sm font-semibold" style={{ color: s.color }}>
            {num(c.value)}
          </span>
        </div>
        <p className="text-[11px] mt-0.5 leading-relaxed" style={{ color: 'var(--text-muted)' }}>
          {c.detail}
        </p>
      </div>
    </div>
  );
}
