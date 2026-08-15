import { ShieldAlert, ShieldCheck } from 'lucide-react';
import { api, type RiskFinding } from '../api/client';
import {
  Badge, ErrorBox, Panel, RefreshBtn, Spinner, Stat, Table, td, type Tone, useLoad,
} from '../components/ui';

const SEV_TONE: Record<RiskFinding['severity'], Tone> = {
  high: 'red',
  medium: 'amber',
  low: 'gray',
};

const SIGNAL_LABEL: Record<RiskFinding['signal'], string> = {
  collection_spike: 'Collection spike',
  duplicate_identity: 'Shared identity',
  reactivation_cycling: 'Suspend/reactivate cycling',
  large_payout: 'Large payout',
  offboarding_bad_debt: 'Offboarding bad debt',
};

/**
 * Fraud / risk — read-only HINTS for a human to look, never automatic action. Deliberately
 * conservative: a missed signal is cheaper than a false alarm that trains staff to ignore the
 * screen. Demo + the platform's own tenant are excluded (they can't defraud us).
 */
export default function RiskView() {
  const { data, error, reload } = useLoad(() => api.risk(), []);

  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return <Spinner />;

  const clean = data.findings.length === 0;

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <h1 className="text-lg font-semibold flex items-center gap-2">
          <ShieldAlert className="h-5 w-5" /> Risk signals
        </h1>
        <RefreshBtn onClick={reload} />
      </div>

      <div className="grid grid-cols-3 gap-3">
        <Stat label="High" value={String(data.counts.high)} hint="look now" />
        <Stat label="Medium" value={String(data.counts.medium)} hint="worth a glance" />
        <Stat label="Low" value={String(data.counts.low)} hint="informational" />
      </div>

      <Panel
        title="Findings"
        subtitle="Hints, not verdicts. Each row is a tenant worth a second look, most severe first."
      >
        {clean ? (
          <div className="flex items-center gap-2 py-6 justify-center" style={{ color: 'var(--good-fg)' }}>
            <ShieldCheck className="h-5 w-5" />
            <span className="text-sm">No risk signals right now — all clear.</span>
          </div>
        ) : (
          <Table head={['Severity', 'Tenant', 'Signal', 'What tripped it']}>
            {data.findings.map((f, i) => (
              <tr key={`${f.operator}-${f.signal}-${i}`}>
                <td className={td}><Badge tone={SEV_TONE[f.severity]}>{f.severity}</Badge></td>
                <td className={td}>
                  <span className="font-medium">{f.name}</span>
                  <span className="block text-[11px]" style={{ color: 'var(--text-muted)' }}>{f.slug}</span>
                </td>
                <td className={td}><Badge tone="gray">{SIGNAL_LABEL[f.signal]}</Badge></td>
                <td className={td} style={{ color: 'var(--text-secondary)' }}>{f.headline}</td>
              </tr>
            ))}
          </Table>
        )}
      </Panel>

      {!clean && (
        <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
          These are detection signals only — nothing here suspends or restricts a tenant. Act
          through the tenant tools (impersonate, suspend, offboard) after you&apos;ve confirmed.
        </p>
      )}
    </div>
  );
}
