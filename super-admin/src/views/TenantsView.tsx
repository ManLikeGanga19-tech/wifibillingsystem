import { useState } from 'react';
import { ArrowLeft, Ban, Check, Eye, Receipt } from 'lucide-react';
import { api, dt, ksh, num, type Tenant } from '../api/client';
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
  tdStyle,
  toast,
  useLoad,
} from '../components/ui';
import ImpersonateDialog from '../components/ImpersonateDialog';

export default function TenantsView({
  openId,
  onOpen,
}: {
  openId: number | null;
  onOpen: (id: number | null) => void;
}) {
  return openId === null ? (
    <TenantList onOpen={onOpen} />
  ) : (
    <TenantDetail id={openId} onBack={() => onOpen(null)} />
  );
}

/* ---- list ---------------------------------------------------------------- */

function TenantList({ onOpen }: { onOpen: (id: number) => void }) {
  const { data, error, reload } = useLoad(() => api.tenants.list(), []);
  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return <Spinner />;

  const act = async (fn: Promise<unknown>, msg: string) => {
    try {
      await fn;
      toast('good', msg);
      reload();
    } catch {
      toast('critical', 'Action failed.');
    }
  };

  return (
    <Panel
      title="ISP tenants"
      subtitle="Every ISP on the platform. Click one to open its full profile."
      right={<RefreshBtn onClick={reload} />}
    >
      {data.results.length === 0 ? (
        <Empty message="No ISPs yet." />
      ) : (
        <Table head={['ISP', 'Owner', 'Status', 'Rates', 'Routers', 'Joined', '']}>
          {data.results.map((t) => (
            <tr
              key={t.id}
              className="hover:bg-white/[0.03] cursor-pointer transition"
              onClick={() => onOpen(t.id)}
            >
              <td className={td} style={tdStyle}>
                <span className="font-medium text-white">{t.name}</span>
                <span className="block text-[11px]" style={{ color: 'var(--text-muted)' }}>
                  {t.slug}
                </span>
              </td>
              <td className={td} style={{ ...tdStyle, color: 'var(--text-secondary)' }}>
                {t.owner_name || '—'}
                <span className="block text-[11px] tnum" style={{ color: 'var(--text-muted)' }}>
                  {t.contact_phone}
                </span>
              </td>
              <td className={td} style={tdStyle}>
                <div className="flex flex-wrap gap-1">
                  <Badge tone={STATUS_TONE[t.status] ?? 'neutral'}>{t.status}</Badge>
                  {inTrial(t.trial_ends_at) && <Badge tone="accent">trial</Badge>}
                </div>
              </td>
              <td
                className={`${td} text-[11px] tnum whitespace-nowrap`}
                style={{ ...tdStyle, color: 'var(--text-secondary)' }}
              >
                {rateSummary(t)}
              </td>
              <td className={`${td} tnum`} style={{ ...tdStyle, color: 'var(--text-secondary)' }}>
                {num(t.router_count)}
              </td>
              <td
                className={`${td} whitespace-nowrap tnum`}
                style={{ ...tdStyle, color: 'var(--text-muted)' }}
              >
                {dt(t.created_at)}
              </td>
              <td className={td} style={tdStyle} onClick={(e) => e.stopPropagation()}>
                <div className="flex gap-1.5">
                  {t.status === 'pending' && (
                    <Btn
                      variant="primary"
                      onClick={() => act(api.tenants.approve(t.id), `${t.name} approved.`)}
                    >
                      <Check className="h-3.5 w-3.5" /> Approve
                    </Btn>
                  )}
                  {t.status === 'active' && (
                    <Btn
                      variant="danger"
                      onClick={() => act(api.tenants.suspend(t.id), `${t.name} suspended.`)}
                    >
                      <Ban className="h-3.5 w-3.5" /> Suspend
                    </Btn>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </Table>
      )}
    </Panel>
  );
}

const inTrial = (until: string | null) =>
  !!until && new Date(until) >= new Date(new Date().toDateString());

const rateSummary = (t: Tenant) =>
  `${ksh(t.base_fee)}/mo · ${Number(t.hotspot_commission_pct)}% · ${
    Number(t.pppoe_user_fee) > 0 ? `${ksh(t.pppoe_user_fee)}/user` : 'tiered'
  }`;

/* ---- detail -------------------------------------------------------------- */

function TenantDetail({ id, onBack }: { id: number; onBack: () => void }) {
  const { data, error, reload } = useLoad(() => api.tenants.detail(id), [id]);
  const [impersonating, setImpersonating] = useState(false);

  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return <Spinner />;
  const { tenant: t, finance, usage } = data;

  const chargeSetup = async () => {
    try {
      const r = await api.tenants.chargeSetup(t.id);
      toast(r.charged ? 'good' : 'warning', r.detail);
      reload();
    } catch {
      toast('critical', 'Could not bill the setup fee.');
    }
  };

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Btn onClick={onBack}>
            <ArrowLeft className="h-3.5 w-3.5" /> All ISPs
          </Btn>
          <div>
            <h1 className="text-lg font-semibold">{t.name}</h1>
            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
              {t.slug}.wifios.co.ke · {t.owner_name} · {t.contact_phone}
            </p>
          </div>
          <Badge tone={STATUS_TONE[t.status] ?? 'neutral'}>{t.status}</Badge>
          {data.in_trial && <Badge tone="accent">trial ends {t.trial_ends_at}</Badge>}
        </div>
        <div className="flex gap-2">
          <Btn onClick={chargeSetup} title="Only for ISPs who opted into assisted onboarding">
            <Receipt className="h-3.5 w-3.5" /> Bill setup fee
          </Btn>
          {/* The audited door. Everything above exists so this is rarely needed. */}
          <Btn variant="primary" onClick={() => setImpersonating(true)}>
            <Eye className="h-3.5 w-3.5" /> Enter their console
          </Btn>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat
          label="Platform revenue"
          value={ksh(finance.platform_revenue)}
          hint="What this ISP has earned us"
        />
        <Stat
          label="Gross collected"
          value={ksh(finance.gross_collected)}
          hint="Customer money we handled"
        />
        <Stat
          label="Wallet balance"
          value={ksh(finance.wallet_balance)}
          hint="What we owe them right now"
        />
        <Stat label="Payouts pending" value={ksh(finance.payouts_pending)} />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Panel title="Rate card" subtitle="What this ISP is charged. Editable per tenant.">
          <RateCard tenant={t} onSaved={reload} />
        </Panel>

        <Panel title="Usage">
          <div className="grid grid-cols-2 gap-3">
            <Stat label="PPPoE billable" value={num(usage.pppoe_billable)} hint="Active only" />
            <Stat label="PPPoE total" value={num(usage.pppoe_total)} hint="Incl. suspended" />
            <Stat
              label="Routers"
              value={`${num(usage.routers_online)} / ${num(usage.routers_total)}`}
              hint="Online / total"
            />
            <Stat label="Staff" value={num(usage.staff)} />
          </div>
        </Panel>
      </div>

      <Panel
        title="Recent activity"
        subtitle="This ISP's slice of the audit trail — who did what, and when."
      >
        {data.recent_activity.length === 0 ? (
          <Empty message="Nothing recorded yet." />
        ) : (
          <Table head={['When', 'Action', 'Actor', 'Target']}>
            {data.recent_activity.map((a) => (
              <tr key={a.id}>
                <td
                  className={`${td} whitespace-nowrap tnum`}
                  style={{ ...tdStyle, color: 'var(--text-muted)' }}
                >
                  {dt(a.created_at)}
                </td>
                <td className={td} style={tdStyle}>
                  <Badge tone="neutral">{a.action}</Badge>
                </td>
                <td className={td} style={{ ...tdStyle, color: 'var(--text-secondary)' }}>
                  {a.actor_name || 'system'}
                </td>
                <td className={td} style={{ ...tdStyle, color: 'var(--text-muted)' }}>
                  {a.target_type ? `${a.target_type}#${a.target_id}` : '—'}
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Panel>

      {impersonating && (
        <ImpersonateDialog
          tenant={t}
          onClose={() => setImpersonating(false)}
          onStarted={() => {
            setImpersonating(false);
            reload();
          }}
        />
      )}
    </div>
  );
}

/* ---- rate card ----------------------------------------------------------- */

function RateCard({ tenant, onSaved }: { tenant: Tenant; onSaved: () => void }) {
  const [form, setForm] = useState({
    base_fee: tenant.base_fee,
    hotspot_commission_pct: tenant.hotspot_commission_pct,
    pppoe_user_fee: tenant.pppoe_user_fee,
    setup_fee: tenant.setup_fee,
  });
  const [saving, setSaving] = useState(false);

  const save = async () => {
    setSaving(true);
    try {
      await api.tenants.update(tenant.id, form);
      toast('good', 'Rates updated.');
      onSaved();
    } catch {
      toast('critical', 'Could not save rates.');
    } finally {
      setSaving(false);
    }
  };

  const field = (key: keyof typeof form, label: string, hint: string) => (
    <label className="block">
      <span className="text-[11px] uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
        {label}
      </span>
      <input
        value={form[key]}
        onChange={(e) => setForm({ ...form, [key]: e.target.value })}
        className="mt-1 tnum"
      />
      <span className="text-[10px] block mt-1" style={{ color: 'var(--text-muted)' }}>
        {hint}
      </span>
    </label>
  );

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 gap-3">
        {field('base_fee', 'Base fee (KSh/mo)', 'Charged after the free month')}
        {field('hotspot_commission_pct', 'Hotspot %', 'Withheld at source per sale')}
        {field('pppoe_user_fee', 'PPPoE flat (KSh)', '0 = use the platform tiers (40/35/30)')}
        {field('setup_fee', 'Setup fee (KSh)', 'Only billed if you bill it — opt-in')}
      </div>
      <Btn variant="primary" onClick={save} disabled={saving}>
        {saving ? 'Saving…' : 'Save rates'}
      </Btn>
    </div>
  );
}
