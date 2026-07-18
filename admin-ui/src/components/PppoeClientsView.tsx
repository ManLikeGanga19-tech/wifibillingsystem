import { useEffect, useState, type FormEvent } from 'react';
import { Users, Plus, Ban, RotateCcw, Zap, Printer, X, Loader2, Wifi, WifiOff, AlertTriangle } from 'lucide-react';
import { api, ApiError, PppoeClient, PppoePlan, ApiRouter, AccessPoint, PppoeUsageSummary, CapacityWarning } from '../api/client';
import {
  Badge, Btn, Field, FilterChips, inputCls, Panel, RefreshBtn, TableShell, tdCls, toast, useList, ViewHeader, fmtDateTime, fmtKsh,
} from './ui';

/** Live status dot, from the 5-minute metering poll. */
function LiveDot({ client }: { client: PppoeClient }) {
  if (client.status !== 'active') return <span className="text-[#141414]/30">—</span>;
  return client.is_online ? (
    <span className="flex items-center gap-1 text-[#228B22]" title={`Up ${client.session_uptime}`}>
      <Wifi className="h-3.5 w-3.5" />
      <span className="font-mono text-[11px]">{client.session_uptime || 'on'}</span>
    </span>
  ) : (
    <span className="flex items-center gap-1 text-[#141414]/40" title="Offline">
      <WifiOff className="h-3.5 w-3.5" /> <span className="font-mono text-[11px]">off</span>
    </span>
  );
}

/** This cycle's data usage, with a FUP bar when the plan is capped. */
function UsageCell({ client }: { client: PppoeClient }) {
  const u = client.usage;
  if (!u) return <span className="text-[#141414]/30">—</span>;
  const pct = u.percent_used;
  const over = pct !== null && pct >= 100;
  const near = pct !== null && pct >= 80;
  return (
    <div className="min-w-[110px]">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-mono text-xs">{u.gb_total} GB</span>
        {u.cap_gb ? (
          <span className={`font-mono text-[10px] ${over ? 'text-[#B22222]' : 'text-[#141414]/50'}`}>
            {pct}%
          </span>
        ) : (
          <span className="font-mono text-[10px] text-[#141414]/40">no cap</span>
        )}
      </div>
      {u.cap_gb ? (
        <div className="mt-1 h-1 w-full bg-[#141414]/10">
          <div
            className={`h-full ${over ? 'bg-[#B22222]' : near ? 'bg-[#E4A11B]' : 'bg-[#228B22]'}`}
            style={{ width: `${Math.min(pct ?? 0, 100)}%` }}
          />
        </div>
      ) : null}
    </div>
  );
}

/** The dashboard tile: live fixed-line health for the whole base. */
function UsageSummaryTile() {
  const [s, setS] = useState<PppoeUsageSummary | null>(null);
  useEffect(() => {
    api.pppoe.usageSummary().then(setS).catch(() => {});
  }, []);
  if (!s || s.clients_active === 0) return null;
  return (
    <Panel title="Fixed-line — live">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label="Online now" value={`${s.online_now} / ${s.clients_active}`} />
        <Stat label="Data this cycle" value={`${s.data_gb_this_cycle} GB`} />
        <Stat label="Over FUP" value={String(s.over_fup)} alert={s.over_fup > 0} />
        <Stat label="Clients" value={String(s.clients_total)} />
      </div>
      {s.top_consumers.length > 0 && (
        <div className="mt-4 border-t border-[#141414]/10 pt-3">
          <p className="mb-1.5 font-mono text-[10px] font-bold uppercase tracking-wide text-[#141414]/50">
            Top consumers this cycle
          </p>
          {s.top_consumers.slice(0, 5).map((c) => (
            <div key={c.account_number} className="flex items-baseline justify-between py-0.5 text-xs">
              <span className="truncate">
                <span className="font-mono text-[#141414]/60">{c.account_number}</span> {c.full_name}
              </span>
              <span className="font-mono">
                {c.gb_total} GB{c.percent_used !== null ? ` · ${c.percent_used}%` : ''}
              </span>
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

function Stat({ label, value, alert = false }: { label: string; value: string; alert?: boolean }) {
  return (
    <div>
      <p className="font-mono text-[10px] uppercase tracking-wide text-[#141414]/50">{label}</p>
      <p className={`font-mono text-xl font-black tabular-nums ${alert ? 'text-[#B22222]' : ''}`}>
        {value}
      </p>
    </div>
  );
}

const FILTERS = ['all', 'active', 'pending_install', 'suspended', 'disabled'] as const;
const STATUS_COLOR: Record<PppoeClient['status'], 'green' | 'amber' | 'red' | 'gray' | 'blue'> = {
  active: 'green',
  pending_install: 'blue',
  suspended: 'red',
  disabled: 'gray',
};
const DELIVERY = [
  { value: 'fibre', label: 'Fibre' },
  { value: 'ethernet', label: 'Ethernet' },
  { value: 'wireless_ptp', label: 'Wireless PTP' },
  { value: 'wireless_ptmp', label: 'Wireless PTMP' },
] as const;

export default function PppoeClientsView() {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('all');
  const { rows, count, error, reload } = useList(
    () => api.pppoe.clients.list(filter === 'all' ? '' : `?status=${filter}`),
    [filter]
  );
  const [plans, setPlans] = useState<PppoePlan[]>([]);
  const [routers, setRouters] = useState<ApiRouter[]>([]);
  const [aps, setAps] = useState<AccessPoint[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [sheetFor, setSheetFor] = useState<PppoeClient | null>(null);
  const [busy, setBusy] = useState(false);
  const blank = {
    full_name: '', phone: '', email: '', physical_address: '',
    plan: '', router: '', delivery_method: 'fibre', access_point: '', billing_day: '1',
  };
  const [form, setForm] = useState(blank);

  useEffect(() => {
    api.pppoe.plans.list().then((r) => setPlans(r.results.filter((p) => p.is_active))).catch(() => {});
    api.routers.list().then((r) => setRouters(r.results)).catch(() => {});
    api.pppoe.accessPoints.list().then((r) => setAps(r.results)).catch(() => {});
  }, []);

  const isWireless = form.delivery_method.startsWith('wireless');

  // When the chosen sector is full the server answers 409 with a warning; we surface it as
  // a card and let the ISP over-subscribe on purpose (force=true), which the server audits.
  const [capWarn, setCapWarn] = useState<CapacityWarning | null>(null);

  const submit = async (force: boolean) => {
    if (busy) return;
    setBusy(true);
    try {
      const client = await api.pppoe.clients.create({
        full_name: form.full_name,
        phone: form.phone,
        email: form.email,
        physical_address: form.physical_address,
        plan: Number(form.plan),
        router: Number(form.router),
        delivery_method: form.delivery_method as PppoeClient['delivery_method'],
        access_point: isWireless && form.access_point ? Number(form.access_point) : null,
        billing_day: Number(form.billing_day),
        ...(force ? { force: true } : {}),
      });
      setCapWarn(null);
      toast('success', `Client ${client.account_number} created. Provisioning to router…`);
      try {
        await api.pppoe.clients.provision(client.id);
        toast('success', 'Provisioned onto the router.');
      } catch {
        toast('warning', 'Client saved but router provisioning failed — use Provision to retry.');
      }
      setForm(blank);
      setShowForm(false);
      reload();
      setSheetFor(client);
    } catch (err) {
      if (
        err instanceof ApiError && err.status === 409 &&
        (err.body as CapacityWarning)?.code === 'sector_at_capacity'
      ) {
        setCapWarn(err.body as CapacityWarning); // show the over-capacity card
      } else {
        toast('error', err instanceof Error ? err.message : 'Failed to create client.');
      }
    } finally {
      setBusy(false);
    }
  };

  const create = (e: FormEvent) => {
    e.preventDefault();
    submit(false);
  };

  const act = async (c: PppoeClient, fn: () => Promise<unknown>, label: string) => {
    try {
      await fn();
      toast('success', `${c.full_name}: ${label}.`);
      reload();
    } catch (e) {
      toast('error', e instanceof Error ? e.message : `${label} failed.`);
    }
  };

  return (
    <div className="space-y-5 text-[#141414]">
      <ViewHeader
        icon={<Users className="h-4.5 w-4.5" />}
        title="Broadband Clients"
        subtitle="PPPoE accounts you set up for clients on fibre, ethernet or wireless (PTP/PTMP). Each gets an account number to pay via M-Pesa."
      >
        <Btn onClick={() => setShowForm(!showForm)}>
          <Plus className="h-3.5 w-3.5" /> New Client
        </Btn>
        <RefreshBtn onClick={reload} />
      </ViewHeader>

      <UsageSummaryTile />

      {showForm && (
        <Panel title="Set up a new client">
          <form onSubmit={create} className="grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
            <Field label="Full name">
              <input required value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Phone">
              <input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} className={inputCls} placeholder="07XX…" />
            </Field>
            <Field label="Plan">
              <select required value={form.plan} onChange={(e) => setForm({ ...form, plan: e.target.value })} className={inputCls}>
                <option value="">Select plan…</option>
                {plans.map((p) => <option key={p.id} value={p.id}>{p.name} — {fmtKsh(p.price)}/mo</option>)}
              </select>
            </Field>
            <Field label="Router / site">
              <select required value={form.router} onChange={(e) => setForm({ ...form, router: e.target.value })} className={inputCls}>
                <option value="">Select router…</option>
                {routers.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
              </select>
            </Field>
            <Field label="Delivery">
              <select value={form.delivery_method} onChange={(e) => setForm({ ...form, delivery_method: e.target.value })} className={inputCls}>
                {DELIVERY.map((d) => <option key={d.value} value={d.value}>{d.label}</option>)}
              </select>
            </Field>
            {isWireless && (
              <Field label="Access point (sector)">
                <select value={form.access_point} onChange={(e) => setForm({ ...form, access_point: e.target.value })} className={inputCls}>
                  <option value="">Unassigned</option>
                  {aps.map((ap) => <option key={ap.id} value={ap.id}>{ap.tower_name} / {ap.name}</option>)}
                </select>
              </Field>
            )}
            <Field label="Billing day (1-28)">
              <input type="number" min="1" max="28" value={form.billing_day} onChange={(e) => setForm({ ...form, billing_day: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Address" className="md:col-span-2">
              <input value={form.physical_address} onChange={(e) => setForm({ ...form, physical_address: e.target.value })} className={inputCls} />
            </Field>
            <Btn type="submit" variant="green" disabled={busy}>
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />}
              Create & provision
            </Btn>
          </form>
        </Panel>
      )}

      <FilterChips options={FILTERS} value={filter} onChange={setFilter} right={<span className="text-[11px] font-mono text-[#141414]/50">{count} clients</span>} />

      <TableShell
        headers={['Account', 'Name', 'Plan', 'Live', 'Usage (cycle)', 'Status', 'Balance', 'Next due', '']}
        loading={rows === null}
        error={error}
        empty="No broadband clients yet."
      >
        {(rows ?? []).map((c: PppoeClient) => (
          <tr key={c.id} className="hover:bg-[#f0efec]/40 transition">
            <td className={`${tdCls} font-mono font-bold`}>{c.account_number}</td>
            <td className={tdCls}>
              {c.full_name}
              <span className="block text-[11px] font-mono text-[#141414]/50">{c.pppoe_username}</span>
            </td>
            <td className={tdCls}>{c.plan_name}</td>
            <td className={tdCls}><LiveDot client={c} /></td>
            <td className={tdCls}><UsageCell client={c} /></td>
            <td className={tdCls}><Badge color={STATUS_COLOR[c.status]}>{c.status.replace('_', ' ')}</Badge></td>
            <td className={`${tdCls} font-mono text-right ${Number(c.balance) < 0 ? 'text-[#B22222]' : ''}`}>{fmtKsh(c.balance)}</td>
            <td className={`${tdCls} font-mono whitespace-nowrap`}>{c.next_due_date ?? '—'}</td>
            <td className={`${tdCls} whitespace-nowrap space-x-1.5`}>
              {c.status === 'pending_install' && (
                <Btn variant="green" onClick={() => act(c, () => api.pppoe.clients.provision(c.id), 'provisioned')}>
                  <Zap className="h-3.5 w-3.5" /> Provision
                </Btn>
              )}
              {c.status === 'active' && (
                <Btn variant="danger" onClick={() => act(c, () => api.pppoe.clients.suspend(c.id), 'suspended')}>
                  <Ban className="h-3.5 w-3.5" /> Suspend
                </Btn>
              )}
              {c.status === 'suspended' && (
                <Btn variant="green" onClick={() => act(c, () => api.pppoe.clients.restore(c.id), 'restored')}>
                  <RotateCcw className="h-3.5 w-3.5" /> Restore
                </Btn>
              )}
              <Btn variant="outline" onClick={() => setSheetFor(c)} title="Printable account sheet">
                <Printer className="h-3.5 w-3.5" /> Sheet
              </Btn>
            </td>
          </tr>
        ))}
      </TableShell>

      {sheetFor && <AccountSheet client={sheetFor} onClose={() => setSheetFor(null)} />}
      {capWarn && (
        <CapacityWarningModal
          warning={capWarn}
          busy={busy}
          onCancel={() => setCapWarn(null)}
          onContinue={() => submit(true)}
        />
      )}
    </div>
  );
}

/**
 * The over-subscription warning. The sector the ISP chose is already full; adding more
 * degrades service for everyone on it. This is their call, not ours — so we warn clearly,
 * let them continue anyway, and the server records that they did.
 */
function CapacityWarningModal({
  warning, busy, onCancel, onContinue,
}: {
  warning: CapacityWarning;
  busy: boolean;
  onCancel: () => void;
  onContinue: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 bg-[#141414]/60 flex items-center justify-center p-4" onClick={onCancel}>
      <div className="bg-white border border-[#B26B00] w-full max-w-md" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 px-4 py-3 border-b border-[#B26B00]/40 bg-[#FFF8EC]">
          <AlertTriangle className="h-4.5 w-4.5 text-[#B26B00]" />
          <h3 className="font-bold font-mono uppercase text-sm text-[#B26B00]">Sector at full capacity</h3>
        </div>
        <div className="p-5 space-y-3">
          <p className="text-sm text-[#141414]/80 leading-relaxed">
            <b>{warning.sector}</b> is carrying <b>{warning.count} of {warning.capacity}</b> clients —
            it&apos;s at capacity. Adding another over-subscribes the sector, which can cause
            congestion, slower speeds and packet loss for <b>everyone</b> on it.
          </p>
          <div className="text-xs font-mono text-[#141414]/55 border border-[#141414]/15 bg-[#faf9f7] p-2.5 space-y-0.5">
            <div>Tower: <b>{warning.tower}</b>{warning.tower_utilization != null && <> · {warning.tower_utilization}% across its sectors</>}</div>
            <div>Sector load: <b>{warning.count}/{warning.capacity}</b></div>
          </div>
          <p className="text-[11px] text-[#141414]/50 leading-relaxed">
            You can add them anyway — this is your call, and WIFI.OS will record that you
            proceeded past the capacity limit.
          </p>
          <div className="flex items-center gap-2 pt-1">
            <Btn variant="danger" onClick={onContinue} disabled={busy}>
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <AlertTriangle className="h-3.5 w-3.5" />}
              Continue anyway
            </Btn>
            <Btn variant="outline" onClick={onCancel} disabled={busy}>
              <X className="h-3.5 w-3.5" /> Cancel
            </Btn>
          </div>
        </div>
      </div>
    </div>
  );
}

function AccountSheet({ client, onClose }: { client: PppoeClient; onClose: () => void }) {
  const print = () => window.print();
  return (
    <div className="fixed inset-0 z-50 bg-[#141414]/50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white border border-[#141414] w-full max-w-sm" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b border-[#141414]">
          <h3 className="font-bold font-mono uppercase text-sm">Account Sheet</h3>
          <button onClick={onClose} className="cursor-pointer"><X className="h-4 w-4" /></button>
        </div>
        <div id="account-sheet" className="p-5 space-y-3 font-mono text-sm">
          <div className="text-center border-b border-[#141414]/20 pb-3">
            <p className="text-[11px] uppercase opacity-60">Your Internet Account</p>
            <p className="font-black text-2xl tracking-wider mt-1">{client.account_number}</p>
          </div>
          <Row label="Name" value={client.full_name} />
          <Row label="Plan" value={client.plan_name} />
          <div className="bg-[#f0efec] border border-[#141414]/20 p-3 mt-2">
            <p className="text-[11px] uppercase opacity-60 mb-1">How to pay (M-Pesa)</p>
            <p className="text-xs leading-relaxed">
              Go to <b>Lipa na M-Pesa → Pay Bill</b>. Enter the business number given by your
              provider, then use <b>account number {client.account_number}</b>. Pay your monthly
              amount before the due date to stay connected.
            </p>
          </div>
          <p className="text-[11px] opacity-50 text-center pt-2">Keep this number safe — it identifies your account.</p>
        </div>
        <div className="p-4 border-t border-[#141414] flex justify-end">
          <Btn variant="green" onClick={print}><Printer className="h-3.5 w-3.5" /> Print</Btn>
        </div>
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between">
      <span className="opacity-50">{label}</span>
      <b>{value}</b>
    </div>
  );
}
