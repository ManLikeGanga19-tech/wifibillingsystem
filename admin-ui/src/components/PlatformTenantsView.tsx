import { Building2, Check, Ban, Eye } from 'lucide-react';
import { api, ApiTenant } from '../api/client';
import { Badge, Btn, RefreshBtn, TableShell, tdCls, toast, useList, ViewHeader, fmtDateTime, fmtKsh } from './ui';

const STATUS_COLOR: Record<ApiTenant['status'], 'green' | 'amber' | 'red' | 'gray' | 'blue'> = {
  pending: 'amber',
  active: 'green',
  suspended: 'red',
};

/** True while the ISP's first-month free trial still covers the base fee. */
const inTrial = (trialEndsAt: string | null): boolean =>
  !!trialEndsAt && new Date(trialEndsAt) >= new Date(new Date().toDateString());

export default function PlatformTenantsView({ onViewAs }: { onViewAs: (slug: string) => void }) {
  const { rows, count, error, reload } = useList(() => api.platform.tenants.list());

  const approve = async (t: ApiTenant) => {
    try {
      await api.platform.tenants.approve(t.id);
      toast('success', `${t.name} approved — their console is now live.`);
      reload();
    } catch {
      toast('error', 'Approval failed.');
    }
  };

  const suspend = async (t: ApiTenant) => {
    if (!confirm(`Suspend ${t.name}? Their staff will lose console access immediately.`)) return;
    try {
      await api.platform.tenants.suspend(t.id);
      toast('warning', `${t.name} suspended.`);
      reload();
    } catch {
      toast('error', 'Suspension failed.');
    }
  };

  return (
    <div className="space-y-5 text-[#141414]">
      <ViewHeader
        icon={<Building2 className="h-4.5 w-4.5" />}
        title="ISP Tenants"
        subtitle="Every ISP on the platform: approve applications, manage billing rates, suspend defaulters."
      >
        <RefreshBtn onClick={reload} />
      </ViewHeader>

      <TableShell
        headers={['ISP', 'Subdomain', 'Owner', 'Status', 'Routers', 'Staff', 'Rates', 'Applied', '']}
        loading={rows === null}
        error={error}
        empty="No ISP tenants yet — they appear here when someone registers."
      >
        {(rows ?? []).map((t) => (
          <tr key={t.id} className="hover:bg-[#f0efec]/40 transition">
            <td className={`${tdCls} font-bold`}>{t.name}</td>
            <td className={`${tdCls} font-mono`}>{t.slug}</td>
            <td className={tdCls}>
              {t.owner_name || '—'}
              <span className="block text-[11px] font-mono text-[#141414]/50">{t.contact_phone}</span>
            </td>
            <td className={tdCls}><Badge color={STATUS_COLOR[t.status]}>{t.status}</Badge></td>
            <td className={`${tdCls} font-mono text-center`}>{t.router_count}</td>
            <td className={`${tdCls} font-mono text-center`}>{t.staff_count}</td>
            <td className={`${tdCls} font-mono text-[11px] whitespace-nowrap`}>
              {inTrial(t.trial_ends_at)
                ? <span className="text-[#228B22]">free until {t.trial_ends_at}</span>
                : `${fmtKsh(t.base_fee)}/mo`} · {Number(t.hotspot_commission_pct)}% ·{' '}
              {Number(t.pppoe_user_fee) > 0 ? `${fmtKsh(t.pppoe_user_fee)}/pppoe` : 'std/pppoe'}
            </td>
            <td className={`${tdCls} font-mono whitespace-nowrap`}>{fmtDateTime(t.created_at)}</td>
            <td className={`${tdCls} whitespace-nowrap space-x-1.5`}>
              {t.status === 'active' && (
                <Btn variant="outline" onClick={() => onViewAs(t.slug)} title="Open this ISP's console (support view)">
                  <Eye className="h-3.5 w-3.5" /> View as
                </Btn>
              )}
              {t.status === 'pending' && (
                <Btn variant="green" onClick={() => approve(t)}>
                  <Check className="h-3.5 w-3.5" /> Approve
                </Btn>
              )}
              {t.status === 'active' && (
                <Btn variant="danger" onClick={() => suspend(t)}>
                  <Ban className="h-3.5 w-3.5" /> Suspend
                </Btn>
              )}
              {t.status === 'suspended' && (
                <Btn variant="outline" onClick={() => approve(t)}>
                  <Check className="h-3.5 w-3.5" /> Reactivate
                </Btn>
              )}
            </td>
          </tr>
        ))}
      </TableShell>
      <p className="text-[11px] font-mono text-[#141414]/50">{count} tenants total</p>
    </div>
  );
}
