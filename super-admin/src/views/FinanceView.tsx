import { useState } from 'react';
import { Scale, TrendingDown, TrendingUp, Wallet } from 'lucide-react';
import { api, ksh, num, type PnlRow } from '../api/client';
import PayoutsPanel from './PayoutsPanel';
import {
  Badge,
  Btn,
  Empty,
  ErrorBox,
  Panel,
  RefreshBtn,
  Spinner,
  Stat,
  STATUS_TONE,
  Table,
  td,
  useLoad,
} from '../components/ui';
import { SERIES } from '../components/charts';

/**
 * Tenant P&L — the screen that pays for itself.
 *
 * Revenue alone is a vanity number: Danamo ABSORBS every M-Pesa/bank cost, so an
 * ISP can look lucrative and still be thin once its collection costs are charged
 * back against it. This is the only place that subtracts them per tenant.
 */
export default function FinanceView({ onOpenTenant }: { onOpenTenant: (id: number) => void }) {
  const [tab, setTab] = useState<'pnl' | 'payouts'>('pnl');
  return (
    <div className="space-y-5">
      <div className="flex items-center gap-1.5">
        <Btn variant={tab === 'pnl' ? 'dark' : 'outline'} onClick={() => setTab('pnl')}>
          <Scale className="h-3.5 w-3.5" /> Tenant P&amp;L
        </Btn>
        <Btn variant={tab === 'payouts' ? 'dark' : 'outline'} onClick={() => setTab('payouts')}>
          <Wallet className="h-3.5 w-3.5" /> Payouts
        </Btn>
      </div>
      {tab === 'pnl' ? <Pnl onOpenTenant={onOpenTenant} /> : <PayoutsPanel />}
    </div>
  );
}

function Pnl({ onOpenTenant }: { onOpenTenant: (id: number) => void }) {
  const { data, error, reload } = useLoad(() => api.pnl(), []);

  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return <Spinner />;

  const rows = data.tenants;
  const paying = rows.filter((r) => !r.is_platform_owned);
  const thin = paying.filter((r) => Number(r.revenue) > 0 && r.margin_pct < 50);
  const totalRevenue = Number(data.totals.revenue);
  const totalNet = Number(data.totals.net_margin);
  const blended = totalRevenue > 0 ? Math.round((1000 * totalNet) / totalRevenue) / 10 : 0;

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
        <Stat label="Platform revenue" value={ksh(data.totals.revenue)} hint="All time, all ISPs" />
        <Stat
          label="Transaction costs absorbed"
          value={ksh(data.totals.transaction_costs)}
          accent={SERIES.costs}
          hint="What the M-Pesa / bank rails took"
        />
        <Stat
          label="Net margin"
          value={ksh(data.totals.net_margin)}
          accent={SERIES.net}
          size="lg"
          hint="What we actually kept"
        />
        <Stat
          label="Blended margin"
          value={`${blended}%`}
          hint="Of every shilling we bill, this is what survives"
        />
      </div>

      {thin.length > 0 && (
        <div
          className="panel p-3.5 text-xs flex items-start gap-2"
          style={{ color: 'var(--warning)' }}
        >
          <TrendingDown className="h-4 w-4 shrink-0 mt-0.5" />
          <span>
            <b>{thin.length}</b> ISP{thin.length > 1 ? 's are' : ' is'} keeping under half of what
            they bill — their collection costs are eating the margin. Likely high-value PPPoE
            packages. Check the rate they're on.
          </span>
        </div>
      )}

      <Panel
        title="Profit &amp; loss per ISP"
        subtitle="Revenue minus the transaction costs we absorb on their behalf. Sorted by what they actually net us."
        right={<RefreshBtn onClick={reload} />}
      >
        {rows.length === 0 ? (
          <Empty message="No ISPs yet." />
        ) : (
          <Table
            head={[
              'ISP',
              'Status',
              'Collected',
              'Revenue',
              'Tx costs',
              'Net margin',
              'Margin',
              'PPPoE',
              'Wallet',
            ]}
          >
            {rows.map((r) => (
              <Row key={r.id} r={r} onOpen={() => onOpenTenant(r.id)} />
            ))}
          </Table>
        )}
      </Panel>
    </div>
  );
}

function Row({ r, onOpen }: { r: PnlRow; onOpen: () => void }) {
  const revenue = Number(r.revenue);
  const healthy = r.margin_pct >= 50;

  return (
    <tr className="hover:bg-[#f0efec] cursor-pointer transition" onClick={onOpen}>
      <td className={td}>
        <span className="font-medium text-[#141414]">{r.name}</span>
        <span className="block text-[11px]" style={{ color: 'var(--text-muted)' }}>
          {r.slug}
        </span>
      </td>
      <td className={td}>
        <div className="flex flex-wrap gap-1">
          <Badge tone={STATUS_TONE[r.status] ?? 'gray'}>{r.status}</Badge>
          {r.in_trial && <Badge tone="blue">trial</Badge>}
          {r.is_platform_owned && <Badge tone="gray">ours</Badge>}
        </div>
      </td>
      <td className={`${td} tnum`} style={{ color: 'var(--text-secondary)' }}>
        {ksh(r.gross_collected, true)}
      </td>
      <td className={`${td} tnum`}>
        {ksh(r.revenue, true)}
      </td>
      <td className={`${td} tnum`} style={{ color: SERIES.costs }}>
        {Number(r.transaction_costs) > 0 ? `−${ksh(r.transaction_costs, true)}` : '—'}
      </td>
      <td className={`${td} tnum font-medium`} style={{ color: SERIES.net }}>
        {ksh(r.net_margin, true)}
      </td>
      <td className={td}>
        {revenue > 0 ? (
          <span
            className="inline-flex items-center gap-1 tnum"
            style={{ color: healthy ? '#228B22' : 'var(--warning)' }}
          >
            {healthy ? (
              <TrendingUp className="h-3 w-3" />
            ) : (
              <TrendingDown className="h-3 w-3" />
            )}
            {r.margin_pct}%
          </span>
        ) : (
          <span style={{ color: 'var(--text-muted)' }}>—</span>
        )}
      </td>
      <td className={`${td} tnum`} style={{ color: 'var(--text-secondary)' }}>
        {num(r.pppoe_users)}
      </td>
      <td className={`${td} tnum`} style={{ color: 'var(--text-secondary)' }}>
        {ksh(r.wallet_balance, true)}
      </td>
    </tr>
  );
}
