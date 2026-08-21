import { useState } from 'react';
import {
  ArrowLeft, Ban, Check, Copy, Download, Eye, LogOut, Plus, Receipt, RotateCcw,
  Sparkles, SmartphoneNfc, Wallet,
} from 'lucide-react';
import { api, dt, ksh, num, type ProvisionResult, type Tenant } from '../api/client';
import {
  Badge,
  Btn,
  Empty,
  ErrorBox,
  Pager,
  Panel,
  RefreshBtn,
  Spinner,
  Stat,
  STATUS_TONE,
  Table,
  td,
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
  const [page, setPage] = useState(1);
  const { data, error, reload } = useLoad(() => api.tenants.list(page), [page]);
  // Declared before the early returns — hooks cannot live behind a conditional.
  const [resetting, setResetting] = useState<Tenant | null>(null);
  const [creating, setCreating] = useState(false);
  const [creds, setCreds] = useState<ProvisionResult | null>(null);
  const [demoBusy, setDemoBusy] = useState(false);

  const createDemo = async () => {
    if (demoBusy) return;
    setDemoBusy(true);
    try {
      const r = await api.tenants.createDemo();
      setCreds(r);
      reload();
    } catch {
      toast('red', 'Could not create the demo tenant.');
    } finally {
      setDemoBusy(false);
    }
  };

  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return <Spinner />;

  const act = async (fn: Promise<unknown>, msg: string) => {
    try {
      await fn;
      toast('green', msg);
      reload();
    } catch {
      toast('red', 'Action failed.');
    }
  };

  return (
    <Panel
      title="ISP tenants"
      subtitle="Every ISP on the platform. Click one to open its full profile."
      right={
        <div className="flex flex-wrap gap-2">
          <Btn onClick={createDemo} disabled={demoBusy} title="Stand up (or refresh) the read-only demo tenant">
            <Sparkles className="h-3.5 w-3.5" /> {demoBusy ? 'Creating…' : 'Create demo'}
          </Btn>
          <Btn variant="dark" onClick={() => setCreating(true)} title="Onboard an ISP by hand, skipping the signup wizard">
            <Plus className="h-3.5 w-3.5" /> New ISP
          </Btn>
          <RefreshBtn onClick={reload} />
        </div>
      }
    >
      {data.results.length === 0 ? (
        <Empty message="No ISPs yet." />
      ) : (
        <Table head={['ISP', 'Owner', 'Status', 'Rates', 'Routers', 'Joined', '']}>
          {data.results.map((t) => (
            <tr
              key={t.id}
              className="hover:bg-[#f0efec] cursor-pointer transition"
              onClick={() => onOpen(t.id)}
            >
              <td className={td}>
                <span className="font-medium text-[#141414]">{t.name}</span>
                <span className="block text-[11px]" style={{ color: 'var(--text-muted)' }}>
                  {t.slug}
                </span>
              </td>
              <td className={td} style={{ color: 'var(--text-secondary)' }}>
                {t.owner_name || '—'}
                <span className="block text-[11px] tnum" style={{ color: 'var(--text-muted)' }}>
                  {t.contact_phone}
                </span>
              </td>
              <td className={td}>
                <div className="flex flex-wrap gap-1">
                  <Badge tone={STATUS_TONE[t.status] ?? 'gray'}>{t.status}</Badge>
                  {inTrial(t.trial_ends_at) && <Badge tone="blue">trial</Badge>}
                </div>
              </td>
              <td
                className={`${td} text-[11px] tnum whitespace-nowrap`}
                style={{ color: 'var(--text-secondary)' }}
              >
                {rateSummary(t)}
              </td>
              <td className={`${td} tnum`} style={{ color: 'var(--text-secondary)' }}>
                {num(t.router_count)}
              </td>
              <td
                className={`${td} whitespace-nowrap tnum`}
                style={{ color: 'var(--text-muted)' }}
              >
                {dt(t.created_at)}
              </td>
              <td className={td} onClick={(e) => e.stopPropagation()}>
                <div className="flex gap-1.5">
                  {t.status === 'pending' && (
                    <Btn
                      variant="dark"
                      onClick={() => act(api.tenants.approve(t.id), `${t.name} approved.`)}
                    >
                      <Check className="h-3.5 w-3.5" /> Approve
                    </Btn>
                  )}
                  {t.status === 'active' && (
                    <Btn
                      variant="danger"
                      onClick={() => {
                        // A full lockout is the last resort — require a typed reason. It is
                        // recorded and shown to the ISP, so a non-payer is told to settle
                        // rather than left guessing at "contact support".
                        const reason = window.prompt(
                          `Suspend ${t.name}? This fully locks their console (they cannot ` +
                            `self-cure). Enter a reason the ISP will see:`
                        );
                        if (reason && reason.trim()) {
                          act(api.tenants.suspend(t.id, reason.trim()), `${t.name} suspended.`);
                        }
                      }}
                    >
                      <Ban className="h-3.5 w-3.5" /> Suspend
                    </Btn>
                  )}
                  {t.status === 'suspended' && (
                    <Btn
                      variant="dark"
                      onClick={() => act(api.tenants.restore(t.id), `${t.name} restored.`)}
                    >
                      <Check className="h-3.5 w-3.5" /> Restore
                    </Btn>
                  )}
                  {/* THE LOST PHONE. The only way back for an ISP owner who cannot
                      produce a code — and the reason it is safe to offer at all is that
                      money cannot move on an impersonated session, so clearing a device
                      here does not let US spend anything. */}
                  <Btn onClick={() => setResetting(t)}>
                    <SmartphoneNfc className="h-3.5 w-3.5" /> Reset 2FA
                  </Btn>
                </div>
              </td>
            </tr>
          ))}
        </Table>
      )}
      <Pager page={page} count={data.count} onPage={setPage} />

      {resetting && (
        <ResetMfaDialog
          tenant={resetting}
          onClose={() => setResetting(null)}
          onDone={() => {
            setResetting(null);
            reload();
          }}
        />
      )}

      {creating && (
        <CreateIspDialog
          onClose={() => setCreating(false)}
          onCreated={(r) => {
            setCreating(false);
            setCreds(r);
            reload();
          }}
        />
      )}

      {creds && <CredentialsDialog result={creds} onClose={() => setCreds(null)} />}
    </Panel>
  );
}

/**
 * Hand-onboard an ISP — the manual path when someone signs up over the phone or in person,
 * so they never touch the marketing wizard. We create the operator and its owner login; the
 * ISP lands PENDING (can configure, cannot take money until settlement is verified).
 */
function CreateIspDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (r: ProvisionResult) => void;
}) {
  const [form, setForm] = useState({ name: '', slug: '', owner_name: '', owner_phone: '' });
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const set = (k: keyof typeof form, v: string) => setForm({ ...form, [k]: v });

  const submit = async () => {
    if (busy || !form.name.trim() || !form.owner_phone.trim()) return;
    setBusy(true);
    setErr('');
    try {
      const r = await api.tenants.provision({
        name: form.name.trim(),
        slug: form.slug.trim(),
        owner_name: form.owner_name.trim() || form.name.trim(),
        owner_phone: form.owner_phone.trim(),
      });
      onCreated(r);
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Could not create the ISP.');
    } finally {
      setBusy(false);
    }
  };

  const field = (k: keyof typeof form, label: string, placeholder: string) => (
    <label className="block">
      <span className="text-[11px] uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
        {label}
      </span>
      <input
        value={form[k]}
        onChange={(e) => set(k, e.target.value)}
        placeholder={placeholder}
        className="mt-1 w-full"
      />
    </label>
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div
        className="w-full max-w-lg border p-5"
        style={{ background: 'var(--surface-1)', borderColor: 'var(--hairline-strong)' }}
      >
        <p className="text-sm font-bold">Onboard an ISP by hand</p>
        <p className="mt-1 text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          Creates the ISP and its owner login. You'll get a temporary password to pass on —
          they change it after signing in. They land pending until settlement is verified.
        </p>

        <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-3">
          {field('name', 'Company name', 'Sunrise Networks')}
          {field('slug', 'Subdomain (optional)', 'sunrise')}
          {field('owner_name', 'Owner name', 'Jane Owner')}
          {field('owner_phone', 'Owner phone', '0712 345 678')}
        </div>
        <p className="mt-2 text-[10px]" style={{ color: 'var(--text-muted)' }}>
          Leave the subdomain blank to derive it from the company name. Their console will be
          at <span className="tnum">{(form.slug.trim() || 'name') + '.wifios.co.ke'}</span>.
        </p>

        {err && <p className="mt-3 text-xs" style={{ color: 'var(--danger, #B22222)' }}>{err}</p>}

        <div className="mt-4 flex justify-end gap-2">
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn variant="dark" onClick={submit} disabled={busy || !form.name.trim() || !form.owner_phone.trim()}>
            {busy ? 'Creating…' : 'Create ISP'}
          </Btn>
        </div>
      </div>
    </div>
  );
}

/**
 * The credentials, shown ONCE. There's no way to reveal the temporary password again (it's
 * hashed the moment it's set), so this dialog is the one chance to copy and send it.
 */
function CredentialsDialog({ result, onClose }: { result: ProvisionResult; onClose: () => void }) {
  const copy = (text: string, what: string) => {
    navigator.clipboard?.writeText(text).then(
      () => toast('green', `${what} copied.`),
      () => toast('red', 'Copy failed — select it by hand.'),
    );
  };

  const block = `${result.console_url}\nPhone: ${result.owner_phone}\nPassword: ${result.temp_password}`;

  const row = (label: string, value: string) => (
    <div className="flex items-center justify-between gap-3 border-b py-2" style={{ borderColor: 'var(--hairline-strong)' }}>
      <span className="text-[11px] uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>{label}</span>
      <span className="flex items-center gap-2">
        <span className="tnum text-sm">{value}</span>
        <button onClick={() => copy(value, label)} title={`Copy ${label}`} className="opacity-70 hover:opacity-100">
          <Copy className="h-3.5 w-3.5" />
        </button>
      </span>
    </div>
  );

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-md border p-5" style={{ background: 'var(--surface-1)', borderColor: 'var(--hairline-strong)' }}>
        <p className="text-sm font-bold">{result.name || result.slug} is ready</p>
        <p className="mt-1 text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          Send these to the owner. The password is shown <b>once</b> — it can't be retrieved
          later, only reset.
        </p>

        <div className="mt-3">
          {row('Console', result.console_url)}
          {row('Phone', result.owner_phone)}
          {row('Password', result.temp_password)}
        </div>

        <div className="mt-4 flex justify-between gap-2">
          <Btn onClick={() => copy(block, 'Login details')}>
            <Copy className="h-3.5 w-3.5" /> Copy all
          </Btn>
          <Btn variant="dark" onClick={onClose}>Done</Btn>
        </div>
      </div>
    </div>
  );
}

/**
 * Switching off somebody else's second factor. Never quiet, never casual:
 * a reason is mandatory (it is audited, and we will be asked about it), the ISP owner
 * is emailed, and their withdrawals freeze for 24 hours so a fraudulent reset cannot be
 * cashed in before the real owner reads that email.
 */
function ResetMfaDialog({
  tenant,
  onClose,
  onDone,
}: {
  tenant: Tenant;
  onClose: () => void;
  onDone: () => void;
}) {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (busy || reason.trim().length < 5) return;
    setBusy(true);
    try {
      const r = await api.tenants.resetMfa(tenant.slug, reason.trim());
      toast('green', r.detail);
      onDone();
    } catch {
      toast('red', 'Could not reset their authenticator.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div
        className="w-full max-w-md border p-5"
        style={{ background: 'var(--surface-1)', borderColor: 'var(--hairline-strong)' }}
      >
        <p className="text-sm font-bold">Reset 2FA for {tenant.name}</p>
        <p className="mt-2 text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          Verify who you are talking to FIRST — by a call to the number on file, not by
          email. This clears their authenticator so they can enrol a new phone. They will be
          emailed, their withdrawals freeze for 24 hours, and this is recorded against your
          name.
        </p>

        <label className="mt-4 block">
          <span className="text-[11px] uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
            Reason (audited)
          </span>
          <input
            autoFocus
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Lost phone — identity confirmed by call to 0712…"
            className="mt-1 w-full"
          />
        </label>

        <div className="mt-4 flex justify-end gap-2">
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn variant="danger" onClick={submit} disabled={busy || reason.trim().length < 5}>
            {busy ? 'Resetting…' : 'Reset their 2FA'}
          </Btn>
        </div>
      </div>
    </div>
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
  const [adjusting, setAdjusting] = useState(false);
  const [offboarding, setOffboarding] = useState(false);
  const [busy, setBusy] = useState(false);

  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return <Spinner />;
  const { tenant: t, finance, usage } = data;
  const ob = t.offboarding;

  const chargeSetup = async () => {
    try {
      const r = await api.tenants.chargeSetup(t.id);
      toast(r.charged ? 'good' : 'warning', r.detail);
      reload();
    } catch {
      toast('red', 'Could not bill the setup fee.');
    }
  };

  const abortOffboard = async () => {
    setBusy(true);
    try {
      await api.tenants.offboardAbort(t.id);
      toast('good', `${t.name} reinstated.`);
      reload();
    } catch {
      toast('red', 'Could not reinstate the tenant.');
    } finally {
      setBusy(false);
    }
  };

  const completeOffboard = async (force: boolean) => {
    if (!window.confirm(
      `This permanently tears every subscriber off the router and closes ${t.name}. ` +
      'It cannot be undone. Continue?')) return;
    setBusy(true);
    try {
      const r = await api.tenants.offboardComplete(t.id, force);
      const recovered = Number(r.fees_recovered);
      const net = Number(r.net_settlement);
      const residual = Number(r.residual_owed);
      const money = residual > 0
        ? `Unrecovered debt: ${ksh(r.residual_owed)} (flagged on Risk).`
        : recovered > 0
          ? `Recovered ${ksh(r.fees_recovered)} in fees; ${ksh(r.net_settlement)} to pay out.`
          : net > 0 ? `${ksh(r.net_settlement)} to pay out.` : 'Nothing outstanding.';
      toast(residual > 0 ? 'warning' : 'good',
        `Offboarding completed — ${r.subscribers_torn_down} subscribers removed. ${money}`);
      reload();
    } catch (e) {
      toast('red', e instanceof Error ? e.message : 'Could not complete offboarding.');
    } finally {
      setBusy(false);
    }
  };

  // The tenant leaves WITH their data: pull the JSON export and hand the browser a download.
  const exportData = async () => {
    try {
      const blob = await api.tenants.exportData(t.id);
      const url = URL.createObjectURL(
        new Blob([JSON.stringify(blob, null, 2)], { type: 'application/json' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = `${t.slug}-export.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast('red', 'Could not export the tenant data.');
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
          <Badge tone={STATUS_TONE[t.status] ?? 'gray'}>{t.status}</Badge>
          {data.in_trial && <Badge tone="blue">trial ends {t.trial_ends_at}</Badge>}
        </div>
        <div className="flex gap-2">
          <Btn onClick={() => setAdjusting(true)} title="Credit or debit this ISP's wallet (audited)">
            <Wallet className="h-3.5 w-3.5" /> Adjust wallet
          </Btn>
          <Btn onClick={chargeSetup} title="Only for ISPs who opted into assisted onboarding">
            <Receipt className="h-3.5 w-3.5" /> Bill setup fee
          </Btn>
          <Btn onClick={exportData} title="Download this ISP's data as JSON (owner-only)">
            <Download className="h-3.5 w-3.5" /> Export data
          </Btn>
          {/* The audited door. Everything above exists so this is rarely needed. */}
          <Btn variant="dark" onClick={() => setImpersonating(true)}>
            <Eye className="h-3.5 w-3.5" /> Enter their console
          </Btn>
          {/* Offboarding: only offered to a live tenant with none already in flight. */}
          {!ob && t.is_active && (
            <Btn variant="danger" onClick={() => setOffboarding(true)}
                 title="Begin removing this ISP from the platform">
              <LogOut className="h-3.5 w-3.5" /> Offboard
            </Btn>
          )}
        </div>
      </div>

      {ob && (
        <OffboardingBanner
          info={ob}
          busy={busy}
          onAbort={abortOffboard}
          onComplete={completeOffboard}
        />
      )}
      {!t.is_active && !ob && (
        <div className="panel p-3.5 text-xs flex items-center gap-2" style={{ color: 'var(--critical)' }}>
          <Ban className="h-4 w-4 shrink-0" />
          <span>This tenant has been <b>offboarded</b> — access is revoked and records are retained.</span>
        </div>
      )}

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
                  style={{ color: 'var(--text-muted)' }}
                >
                  {dt(a.created_at)}
                </td>
                <td className={td}>
                  <Badge tone="gray">{a.action}</Badge>
                </td>
                <td className={td} style={{ color: 'var(--text-secondary)' }}>
                  {a.actor_name || 'system'}
                </td>
                <td className={td} style={{ color: 'var(--text-muted)' }}>
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

      {adjusting && (
        <AdjustWalletDialog
          tenant={t}
          onClose={() => setAdjusting(false)}
          onDone={() => { setAdjusting(false); reload(); }}
        />
      )}

      {offboarding && (
        <OffboardingDialog
          tenant={t}
          onClose={() => setOffboarding(false)}
          onDone={() => { setOffboarding(false); reload(); }}
        />
      )}
    </div>
  );
}

/**
 * The grace-window banner: a tenant is frozen and scheduled to be torn down, but can still be
 * reinstated. Shows the money that has to settle either way (we owe them / they owe us) and
 * the two exits — undo, or complete now (which is irreversible).
 */
function OffboardingBanner({
  info,
  busy,
  onAbort,
  onComplete,
}: {
  info: NonNullable<Tenant['offboarding']>;
  busy: boolean;
  onAbort: () => void;
  onComplete: (force: boolean) => void;
}) {
  const owe = Number(info.snapshot_withdrawable);
  const owed = Number(info.snapshot_owed);
  return (
    <div className="panel p-4 space-y-3" style={{ borderColor: 'var(--critical)' }}>
      <div className="flex items-start gap-2" style={{ color: 'var(--critical)' }}>
        <LogOut className="h-4 w-4 shrink-0 mt-0.5" />
        <div className="text-xs leading-relaxed">
          <b>Offboarding scheduled.</b> The console is frozen. Reason: “{info.reason}”.{' '}
          {info.in_grace
            ? <>Grace window ends <b>{dt(info.grace_until)}</b> — until then this is fully reversible.</>
            : <>The grace window has passed; this can be completed now.</>}
          <div className="mt-1.5" style={{ color: 'var(--text-secondary)' }}>
            {owe > 0 && <>We owe them <b>{ksh(info.snapshot_withdrawable)}</b> to pay out. </>}
            {owed > 0 && <>They owe us <b>{ksh(info.snapshot_owed)}</b> to collect. </>}
            {owe <= 0 && owed <= 0 && <>Nothing outstanding either way.</>}
          </div>
          {owed > 0 && (
            <div className="mt-1 flex items-center gap-1.5" style={{ color: 'var(--critical)' }}>
              <Ban className="h-3.5 w-3.5 shrink-0" />
              <span>Client-data export is blocked until the arrears are settled.</span>
            </div>
          )}
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        <Btn onClick={onAbort} disabled={busy}>
          <RotateCcw className="h-3.5 w-3.5" /> Undo — reinstate
        </Btn>
        <Btn variant="danger" onClick={() => onComplete(!info.in_grace ? false : true)} disabled={busy}>
          <Ban className="h-3.5 w-3.5" /> {info.in_grace ? 'Complete now (force)' : 'Complete offboarding'}
        </Btn>
      </div>
    </div>
  );
}

/**
 * Start offboarding an ISP. This only FREEZES them and opens a grace window — nothing on the
 * network is torn down yet, and it can be undone. A reason is mandatory (it becomes the
 * record). Owner-only on the server.
 */
function OffboardingDialog({
  tenant,
  onClose,
  onDone,
}: {
  tenant: Tenant;
  onClose: () => void;
  onDone: () => void;
}) {
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const submit = async () => {
    if (!reason.trim()) return;
    setBusy(true);
    setErr('');
    try {
      await api.tenants.offboard(tenant.id, reason.trim());
      toast('good', `${tenant.name} is being offboarded (grace window opened).`);
      onDone();
    } catch (e) {
      setErr(e instanceof Error ? e.message : 'Could not start offboarding.');
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-md border p-5" style={{ background: 'var(--surface-1)', borderColor: 'var(--hairline-strong)' }}>
        <p className="text-sm font-bold">Offboard {tenant.name}</p>
        <p className="mt-1 text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          This <b>freezes</b> the ISP&apos;s console and starts a grace window. Nothing on the
          network is touched yet — you can reinstate them with one click. Only <b>completing</b>{' '}
          the offboarding later tears their subscribers off the router. This is audited.
        </p>
        <label className="mt-3 block">
          <span className="text-[11px] uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Reason (recorded)</span>
          <textarea rows={3} autoFocus value={reason} onChange={(e) => setReason(e.target.value)}
                    className="mt-1 w-full" placeholder="e.g. Business closed / migrated off / non-payment write-off" />
        </label>
        {err && <p className="mt-2 text-xs" style={{ color: 'var(--critical)' }}>{err}</p>}
        <div className="mt-4 flex justify-end gap-2">
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn variant="danger" onClick={submit} disabled={busy || !reason.trim()}>
            <LogOut className="h-3.5 w-3.5" /> {busy ? 'Starting…' : 'Begin offboarding'}
          </Btn>
        </div>
      </div>
    </div>
  );
}

/**
 * Credit (+) or debit (−) an ISP's wallet with a recorded reason. Not a cash movement — it
 * moves the ledger balance (what we owe them, what they can withdraw), so a reason is
 * mandatory and it's audited against your name. Owner-only on the server.
 */
function AdjustWalletDialog({
  tenant,
  onClose,
  onDone,
}: {
  tenant: Tenant;
  onClose: () => void;
  onDone: () => void;
}) {
  const [dir, setDir] = useState<'credit' | 'debit'>('credit');
  const [amount, setAmount] = useState('');
  const [reason, setReason] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    const n = Number(amount);
    if (busy || !n || reason.trim().length < 3) return;
    setBusy(true);
    try {
      const signed = dir === 'debit' ? -Math.abs(n) : Math.abs(n);
      const r = await api.tenants.adjust(tenant.id, String(signed), reason.trim());
      toast('green', r.detail);
      onDone();
    } catch {
      toast('red', 'Could not adjust the wallet.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-md border p-5" style={{ background: 'var(--surface-1)', borderColor: 'var(--hairline-strong)' }}>
        <p className="text-sm font-bold">Adjust {tenant.name}&apos;s wallet</p>
        <p className="mt-1 text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          A credit gives them money (goodwill, a fee waiver); a debit takes it (an error fix).
          This changes what we owe them. Recorded against your name.
        </p>

        <div className="mt-4 flex gap-1.5">
          {(['credit', 'debit'] as const).map((d) => (
            <button
              key={d}
              onClick={() => setDir(d)}
              className={`flex-1 py-1.5 text-xs font-bold font-mono uppercase border cursor-pointer ${
                dir === d ? 'bg-[#141414] text-white border-[#141414]' : 'border-[#141414]/40'
              }`}
            >
              {d}
            </button>
          ))}
        </div>

        <label className="mt-3 block">
          <span className="text-[11px] uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Amount (KSh)</span>
          <input type="number" min="0" step="0.01" value={amount} onChange={(e) => setAmount(e.target.value)}
                 className="mt-1 w-full tnum" placeholder="0.00" autoFocus />
        </label>
        <label className="mt-3 block">
          <span className="text-[11px] uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>Reason (audited)</span>
          <input value={reason} onChange={(e) => setReason(e.target.value)}
                 className="mt-1 w-full" placeholder="e.g. goodwill credit — outage on 12 Aug" />
        </label>

        <div className="mt-4 flex justify-end gap-2">
          <Btn onClick={onClose}>Cancel</Btn>
          <Btn variant="dark" onClick={submit} disabled={busy || !Number(amount) || reason.trim().length < 3}>
            {busy ? 'Saving…' : dir === 'credit' ? 'Credit wallet' : 'Debit wallet'}
          </Btn>
        </div>
      </div>
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
      toast('green', 'Rates updated.');
      onSaved();
    } catch {
      toast('red', 'Could not save rates.');
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
      <Btn variant="dark" onClick={save} disabled={saving}>
        {saving ? 'Saving…' : 'Save rates'}
      </Btn>
    </div>
  );
}
