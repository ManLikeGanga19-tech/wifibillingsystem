import React, { useEffect, useState, type FormEvent } from 'react';
import { Users, Plus, Ban, RotateCcw, Zap, Printer, X, Loader2, Wifi, WifiOff, AlertTriangle, Key, Copy, Eye, EyeOff, Trash2, RefreshCw, Upload, Download, Pencil, Save, Search, MoreHorizontal, ArrowRight } from 'lucide-react';
import { api, ApiError, PppoeClient, PppoePlan, ApiRouter, AccessPoint, FibrePoint, PppoeUsageSummary, PppoeChurnSummary, CapacityWarning, PppoeImportRow, PppoeImportItem, PppoeCsvPreview, PppoeImportResult } from '../api/client';
import MapPicker from './MapPicker';
import DataTable, { type Column } from './DataTable';
import {
  Badge, Btn, Field, FilterChips, inputCls, Panel, toast, ViewHeader, fmtDateTime, fmtKsh,
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
    </Panel>
  );
}

/** Subscriber movement: this month's churn at a glance, plus a compact net-change trend.
 *  Answers "who didn't renew" and "what's my churn" — the questions a status column can't. */
function ChurnSummaryTile() {
  const [s, setS] = useState<PppoeChurnSummary | null>(null);
  useEffect(() => {
    api.pppoe.churnSummary(6).then(setS).catch(() => {});
  }, []);
  if (!s || s.months.length === 0) return null;
  const served = s.standing.active + s.standing.suspended + s.standing.cancelled;
  if (served === 0) return null; // nothing to say yet on a brand-new base

  const now = s.months[s.months.length - 1];
  const rate = now.churn_rate === null ? '—' : `${(now.churn_rate * 100).toFixed(1)}%`;
  const net = now.net >= 0 ? `+${now.net}` : String(now.net);

  return (
    <Panel title="Fixed-line — churn (this month)">
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <Stat label="Churn rate" value={rate} alert={now.churn_rate !== null && now.churn_rate >= 0.1} />
        <Stat label="New" value={String(now.new + now.reactivated)} />
        <Stat label="Churned" value={String(now.churned)} alert={now.churned > 0} />
        <Stat label="Net" value={net} />
      </div>
      <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-[#141414]/50">
        <span className="uppercase tracking-wide text-[#141414]/40">Net / month</span>
        {s.months.map((m) => (
          <span key={m.month} className="font-mono">
            {m.month.slice(5)}{' '}
            <b className={m.net < 0 ? 'text-[#B22222]' : m.net > 0 ? 'text-[#228B22]' : ''}>
              {m.net >= 0 ? `+${m.net}` : m.net}
            </b>
          </span>
        ))}
        {s.standing.cancelled > 0 && (
          <span className="ml-auto">{s.standing.cancelled} cancelled total</span>
        )}
      </div>
    </Panel>
  );
}

/** When this client is next billed. The server projects it from their billing day until the
 *  first invoice exists, so this is never blank — a blank date read as "billing isn't set
 *  up". A projected date is shown lighter, with the real one taking over once invoiced. */
function NextDueCell({ client }: { client: PppoeClient }) {
  const date = client.next_billing_date ?? client.next_due_date;
  if (!date) return <span className="text-[#141414]/30">—</span>;
  const projected = client.next_due_is_projected;
  return (
    <span
      className={projected ? 'text-[#141414]/45' : ''}
      title={projected ? 'Projected from their billing day — no invoice issued yet' : 'From their current invoice'}
    >
      {date}
      {projected && <span className="block text-[10px] uppercase tracking-wide">expected</span>}
    </span>
  );
}

/** The per-row tools, behind a menu. Keeping only the status action inline stops the row
 *  turning into a wall of buttons once an ISP has a few hundred clients. */
function RowMenu({
  onEdit, onCredentials, onSheet,
}: {
  onEdit: () => void;
  onCredentials: () => void;
  onSheet: () => void;
}) {
  const [open, setOpen] = useState(false);

  // Close on any outside click or Escape, so the menu can never get stuck open.
  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && setOpen(false);
    window.addEventListener('click', close);
    window.addEventListener('keydown', onKey);
    return () => {
      window.removeEventListener('click', close);
      window.removeEventListener('keydown', onKey);
    };
  }, [open]);

  const pick = (fn: () => void) => (e: React.MouseEvent) => {
    e.stopPropagation();
    setOpen(false);
    fn();
  };

  return (
    <div className="relative inline-block">
      <Btn
        variant="outline"
        onClick={(e?: React.MouseEvent) => { e?.stopPropagation(); setOpen((v) => !v); }}
        title="More actions"
      >
        <MoreHorizontal className="h-3.5 w-3.5" />
      </Btn>
      {open && (
        <div
          className="absolute right-0 top-full mt-1 z-30 min-w-[11rem] bg-white border border-[#141414] shadow-lg"
          onClick={(e) => e.stopPropagation()}
        >
          <MenuItem icon={<Pencil className="h-3.5 w-3.5" />} label="Edit details" onClick={pick(onEdit)} />
          <MenuItem icon={<Key className="h-3.5 w-3.5" />} label="Credentials" onClick={pick(onCredentials)} />
          <MenuItem icon={<Printer className="h-3.5 w-3.5" />} label="Account sheet" onClick={pick(onSheet)} />
        </div>
      )}
    </div>
  );
}

function MenuItem({ icon, label, onClick }: { icon: React.ReactNode; label: string; onClick: (e: React.MouseEvent) => void }) {
  return (
    <button
      onClick={onClick}
      className="w-full flex items-center gap-2 px-3 py-2 text-xs font-mono text-left hover:bg-[#f0efec] cursor-pointer"
    >
      {icon} {label}
    </button>
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

const FILTERS = ['all', 'active', 'pending_install', 'suspended', 'cancelled', 'disabled'] as const;
const STATUS_COLOR: Record<PppoeClient['status'], 'green' | 'amber' | 'red' | 'gray' | 'blue'> = {
  active: 'green',
  pending_install: 'blue',
  suspended: 'red',
  cancelled: 'gray',
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
  // Bumped to reload the DataTable after a create / status action.
  const [refresh, setRefresh] = useState(0);
  const reload = () => setRefresh((n) => n + 1);
  const [plans, setPlans] = useState<PppoePlan[]>([]);
  const [routers, setRouters] = useState<ApiRouter[]>([]);
  const [aps, setAps] = useState<AccessPoint[]>([]);
  // ODPs/splitters a fibre customer can hang off (for the "serving ODP" picker).
  const [fibrePoints, setFibrePoints] = useState<FibrePoint[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [sheetFor, setSheetFor] = useState<PppoeClient | null>(null);
  const [credsFor, setCredsFor] = useState<PppoeClient | null>(null);
  const [editFor, setEditFor] = useState<PppoeClient | null>(null);
  const [showImport, setShowImport] = useState(false);
  const [showExport, setShowExport] = useState(false);
  const [busy, setBusy] = useState(false);

  const exportCsv = (includeCredentials = false) => {
    const a = document.createElement('a');
    a.href = api.pppoe.clients.exportUrl(includeCredentials);
    a.download = '';
    document.body.appendChild(a);
    a.click();
    a.remove();
  };
  const blank = {
    full_name: '', phone: '', email: '', physical_address: '',
    plan: '', router: '', delivery_method: 'fibre', access_point: '', fibre_point: '', billing_day: '1',
    connection_type: 'pppoe', static_ip: '',
    pppoe_username: '', pppoe_password: '',
    gps_lat: null as number | null, gps_lng: null as number | null,
  };
  const [form, setForm] = useState(blank);

  useEffect(() => {
    api.pppoe.plans.list().then((r) => setPlans(r.results.filter((p) => p.is_active))).catch(() => {});
    api.routers.list().then((r) => setRouters(r.results)).catch(() => {});
    api.pppoe.accessPoints.list().then((r) => setAps(r.results)).catch(() => {});
    api.fibre.points.list()
      .then((r) => setFibrePoints(r.results.filter((p) => p.is_active && ['odp', 'splitter', 'cabinet'].includes(p.type))))
      .catch(() => {});
  }, []);

  // Auto-refresh so a client that just connected flips to "live" on its own. The backend
  // presence sweep updates the online flag within ~a minute; this reflects it without the
  // ISP hitting refresh. A silent re-fetch (reload doesn't blank the table).
  useEffect(() => {
    const id = window.setInterval(reload, 30_000);
    return () => window.clearInterval(id);
  }, [reload]);

  const isWireless = form.delivery_method.startsWith('wireless');
  const isFibre = form.delivery_method === 'fibre';
  const isStatic = form.connection_type === 'static';

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
        gps_lat: form.gps_lat != null ? String(form.gps_lat) : null,
        gps_lng: form.gps_lng != null ? String(form.gps_lng) : null,
        plan: Number(form.plan),
        router: Number(form.router),
        delivery_method: form.delivery_method as PppoeClient['delivery_method'],
        access_point: isWireless && form.access_point ? Number(form.access_point) : null,
        fibre_point: isFibre && form.fibre_point ? Number(form.fibre_point) : null,
        billing_day: Number(form.billing_day),
        connection_type: form.connection_type as PppoeClient['connection_type'],
        // Static clients enforce by IP (no login); PPPoE clients get a secret (blank = auto).
        static_ip: isStatic ? form.static_ip.trim() : null,
        pppoe_username: isStatic ? '' : form.pppoe_username.trim(),
        pppoe_password: isStatic ? '' : form.pppoe_password,
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

  const clientColumns: Column<PppoeClient>[] = [
    { header: 'Account', sortKey: 'account_number', render: (c) => <span className="font-mono font-bold">{c.account_number}</span> },
    {
      header: 'Name', sortKey: 'full_name',
      render: (c) => (
        <>
          <button onClick={() => setEditFor(c)} className="text-left hover:underline cursor-pointer" title="Edit this client">
            {c.full_name}
          </button>
          <span className="block text-[11px] font-mono text-[#141414]/50">
            {c.connection_type === 'static' ? `Static · ${c.static_ip ?? '—'}` : c.pppoe_username}
          </span>
        </>
      ),
    },
    { header: 'Plan', render: (c) => c.plan_name },
    { header: 'Live', render: (c) => <LiveDot client={c} /> },
    { header: 'Usage (cycle)', render: (c) => <UsageCell client={c} /> },
    { header: 'Status', sortKey: 'status', render: (c) => <Badge color={STATUS_COLOR[c.status]}>{c.status.replace('_', ' ')}</Badge> },
    {
      header: 'Balance', sortKey: 'balance', className: 'text-right',
      render: (c) => <span className={`font-mono ${Number(c.balance) < 0 ? 'text-[#B22222]' : ''}`}>{fmtKsh(c.balance)}</span>,
    },
    { header: 'Next billing', sortKey: 'next_due_date', render: (c) => <span className="font-mono whitespace-nowrap"><NextDueCell client={c} /></span> },
    {
      header: '', className: 'whitespace-nowrap',
      render: (c) => (
        <div className="flex items-center justify-end gap-1.5">
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
          <RowMenu onEdit={() => setEditFor(c)} onCredentials={() => setCredsFor(c)} onSheet={() => setSheetFor(c)} />
        </div>
      ),
    },
  ];

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
        <Btn variant="outline" onClick={() => setShowImport(true)} title="Adopt existing PPPoE users off a router">
          <Upload className="h-3.5 w-3.5" /> Import
        </Btn>
        <Btn variant="outline" onClick={() => setShowExport(true)} title="Download all clients as CSV">
          <Download className="h-3.5 w-3.5" /> Export
        </Btn>
      </ViewHeader>

      <UsageSummaryTile />
      <ChurnSummaryTile />

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
            <Field label="Connection type">
              <select value={form.connection_type} onChange={(e) => setForm({ ...form, connection_type: e.target.value })} className={inputCls}>
                <option value="pppoe">PPPoE (login)</option>
                <option value="static">Static IP</option>
              </select>
            </Field>
            {isStatic && (
              <Field label="Static IP">
                <input required value={form.static_ip} onChange={(e) => setForm({ ...form, static_ip: e.target.value })} className={inputCls} placeholder="e.g. 10.20.0.5" />
              </Field>
            )}
            {isWireless && (
              <Field label="Access point (sector)">
                <select value={form.access_point} onChange={(e) => setForm({ ...form, access_point: e.target.value })} className={inputCls}>
                  <option value="">Unassigned</option>
                  {aps.map((ap) => <option key={ap.id} value={ap.id}>{ap.tower_name} / {ap.name}</option>)}
                </select>
              </Field>
            )}
            {isFibre && (
              <Field label="Serving ODP (blast-radius)">
                <select value={form.fibre_point} onChange={(e) => setForm({ ...form, fibre_point: e.target.value })} className={inputCls}>
                  <option value="">Unassigned</option>
                  {fibrePoints.map((fp) => <option key={fp.id} value={fp.id}>{fp.label} · {fp.type_display}</option>)}
                </select>
              </Field>
            )}
            <Field label="Billing day (1-28)">
              <input type="number" min="1" max="28" value={form.billing_day} onChange={(e) => setForm({ ...form, billing_day: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Address" className="md:col-span-2">
              <input value={form.physical_address} onChange={(e) => setForm({ ...form, physical_address: e.target.value })} className={inputCls} />
            </Field>
            <div className="md:col-span-4">
              <label className="text-[11px] font-mono uppercase text-[#141414]/50 block mb-1">Home location (for the Map)</label>
              <MapPicker
                lat={form.gps_lat} lng={form.gps_lng}
                onChange={(la, ln) => setForm((f) => ({
                  ...f, gps_lat: Number.isFinite(la) ? la : null, gps_lng: Number.isFinite(ln) ? ln : null,
                }))}
              />
            </div>
            {!isStatic && (
              <>
                <Field label="PPPoE username (optional)">
                  <input value={form.pppoe_username} onChange={(e) => setForm({ ...form, pppoe_username: e.target.value })} className={inputCls} placeholder="Auto-generated if blank" />
                </Field>
                <Field label="PPPoE password (optional)">
                  <input value={form.pppoe_password} onChange={(e) => setForm({ ...form, pppoe_password: e.target.value })} className={inputCls} placeholder="Auto-generated if blank" />
                </Field>
              </>
            )}
            <Btn type="submit" variant="green" disabled={busy}>
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Zap className="h-3.5 w-3.5" />}
              Create & provision
            </Btn>
          </form>
        </Panel>
      )}

      <DataTable<PppoeClient>
        fetcher={(q) => api.pppoe.clients.list(q)}
        columns={clientColumns}
        rowKey={(c) => c.id}
        searchPlaceholder="Search name, account, phone or PPPoE user…"
        emptyMessage="No broadband clients yet."
        initialOrdering="-created_at"
        filters={{ status: filter === 'all' ? undefined : filter }}
        refreshSignal={refresh}
        toolbar={<FilterChips options={FILTERS} value={filter} onChange={setFilter} />}
      />

      {sheetFor && <AccountSheet client={sheetFor} onClose={() => setSheetFor(null)} />}
      {credsFor && (
        <CredentialsDialog
          client={credsFor}
          onClose={() => setCredsFor(null)}
          onChanged={reload}
        />
      )}
      {capWarn && (
        <CapacityWarningModal
          warning={capWarn}
          busy={busy}
          onCancel={() => setCapWarn(null)}
          onContinue={() => submit(true)}
        />
      )}
      {editFor && (
        <EditClientDialog
          fibrePoints={fibrePoints}
          client={editFor}
          plans={plans}
          routers={routers}
          aps={aps}
          onClose={() => setEditFor(null)}
          onSaved={reload}
          onOpenCredentials={(c) => { setEditFor(null); setCredsFor(c); }}
        />
      )}
      {showExport && (
        <ExportDialog
          onClose={() => setShowExport(false)}
          onExport={(withCreds) => { exportCsv(withCreds); setShowExport(false); }}
        />
      )}
      {showImport && (
        <ImportDialog
          routers={routers}
          plans={plans}
          onClose={() => setShowImport(false)}
          onDone={reload}
        />
      )}
    </div>
  );
}

/**
 * Edit a client. Everything here is editable EXCEPT the account number — that is the
 * customer's permanent M-Pesa payment reference, so it stays with them when they move house
 * (you just change the address). Changes that the router needs to know about — the plan, the
 * site/router — are pushed to the MikroTik by the server, so the console and the network
 * never disagree. The password lives in Credentials (it has to re-push), linked from here.
 */
function EditClientDialog({
  client, plans, routers, aps, fibrePoints, onClose, onSaved, onOpenCredentials,
}: {
  client: PppoeClient;
  plans: PppoePlan[];
  routers: ApiRouter[];
  aps: AccessPoint[];
  fibrePoints: FibrePoint[];
  onClose: () => void;
  onSaved: () => void;
  onOpenCredentials: (c: PppoeClient) => void;
}) {
  const [form, setForm] = useState({
    full_name: client.full_name ?? '',
    phone: client.phone ?? '',
    email: client.email ?? '',
    physical_address: client.physical_address ?? '',
    plan: String(client.plan),
    router: String(client.router),
    delivery_method: client.delivery_method,
    access_point: client.access_point ? String(client.access_point) : '',
    fibre_point: client.fibre_point ? String(client.fibre_point) : '',
    billing_day: String(client.billing_day),
    notes: client.notes ?? '',
    gps_lat: client.gps_lat ? Number(client.gps_lat) : (null as number | null),
    gps_lng: client.gps_lng ? Number(client.gps_lng) : (null as number | null),
  });
  const [busy, setBusy] = useState(false);
  const isWireless = form.delivery_method.startsWith('wireless');
  const isFibre = form.delivery_method === 'fibre';

  const planChanged = Number(form.plan) !== client.plan;
  const routerChanged = Number(form.router) !== client.router;

  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    try {
      await api.pppoe.clients.update(client.id, {
        full_name: form.full_name,
        phone: form.phone,
        email: form.email,
        physical_address: form.physical_address,
        plan: Number(form.plan),
        router: Number(form.router),
        delivery_method: form.delivery_method as PppoeClient['delivery_method'],
        access_point: isWireless && form.access_point ? Number(form.access_point) : null,
        fibre_point: isFibre && form.fibre_point ? Number(form.fibre_point) : null,
        billing_day: Number(form.billing_day),
        notes: form.notes,
        gps_lat: form.gps_lat != null ? String(form.gps_lat) : null,
        gps_lng: form.gps_lng != null ? String(form.gps_lng) : null,
      });
      toast(
        'success',
        planChanged || routerChanged
          ? 'Saved — and pushed to the router.'
          : `${form.full_name} updated.`,
      );
      onSaved();
      onClose();
    } catch (err) {
      toast('error', err instanceof Error ? err.message : 'Could not save those changes.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-[#141414]/50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white border border-[#141414] w-full max-w-2xl max-h-[88vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b border-[#141414]">
          <h3 className="font-bold font-mono uppercase text-sm flex items-center gap-2">
            <Pencil className="h-4 w-4" /> Edit client
          </h3>
          <button onClick={onClose} className="cursor-pointer"><X className="h-4 w-4" /></button>
        </div>
        <form onSubmit={save} className="p-5 space-y-4">
          <div className="flex items-baseline justify-between border border-[#141414]/15 bg-[#f0efec] px-3 py-2">
            <span className="font-mono text-[10px] uppercase tracking-wide text-[#141414]/50">Account number</span>
            <b className="font-mono">{client.account_number}</b>
          </div>
          <p className="text-[11px] text-[#141414]/55 leading-relaxed -mt-2">
            The account number never changes — it&apos;s how this customer&apos;s M-Pesa
            payments find them, so it moves with them if they relocate.
          </p>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <Field label="Full name">
              <input required value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Phone">
              <input value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} className={inputCls} placeholder="07XX…" />
            </Field>
            <Field label="Email">
              <input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Address">
              <input value={form.physical_address} onChange={(e) => setForm({ ...form, physical_address: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Plan">
              <select value={form.plan} onChange={(e) => setForm({ ...form, plan: e.target.value })} className={inputCls}>
                {plans.map((p) => <option key={p.id} value={p.id}>{p.name} — {fmtKsh(p.price)}/mo</option>)}
              </select>
            </Field>
            <Field label="Router / site">
              <select value={form.router} onChange={(e) => setForm({ ...form, router: e.target.value })} className={inputCls}>
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
            {isFibre && (
              <Field label="Serving ODP (blast-radius)">
                <select value={form.fibre_point} onChange={(e) => setForm({ ...form, fibre_point: e.target.value })} className={inputCls}>
                  <option value="">Unassigned</option>
                  {fibrePoints.map((fp) => <option key={fp.id} value={fp.id}>{fp.label} · {fp.type_display}</option>)}
                </select>
              </Field>
            )}
          </div>

          <BillingDayPicker
            value={Number(form.billing_day)}
            onChange={(d) => setForm({ ...form, billing_day: String(d) })}
          />

          <Field label="Notes">
            <textarea value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} className={`${inputCls} h-20`} />
          </Field>

          <div>
            <label className="text-[11px] font-mono uppercase text-[#141414]/50 block mb-1">Home location (for the Map)</label>
            <MapPicker
              lat={form.gps_lat} lng={form.gps_lng}
              onChange={(la, ln) => setForm((f) => ({
                ...f, gps_lat: Number.isFinite(la) ? la : null, gps_lng: Number.isFinite(ln) ? ln : null,
              }))}
            />
          </div>

          {(planChanged || routerChanged) && (
            <div className="border border-[#B26B00]/40 bg-[#FFF8EC] px-3 py-2 text-xs text-[#B26B00] leading-relaxed">
              {planChanged && <p>Changing the plan re-pushes the speed to the router and briefly reconnects this customer so the new rate applies immediately.</p>}
              {routerChanged && <p>Moving them to another site transfers their PPPoE account to that router.</p>}
            </div>
          )}

          <div className="flex items-center justify-between border-t border-[#141414]/10 pt-3">
            <Btn variant="outline" type="button" onClick={() => onOpenCredentials(client)}>
              <Key className="h-3.5 w-3.5" /> Change password
            </Btn>
            <div className="flex items-center gap-2">
              <Btn variant="outline" type="button" onClick={onClose} disabled={busy}><X className="h-3.5 w-3.5" /> Cancel</Btn>
              <Btn variant="green" type="submit" disabled={busy}>
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
                Save changes
              </Btn>
            </div>
          </div>
        </form>
      </div>
    </div>
  );
}

/** Billing day = which day of the month the ISP invoices this client. A month grid reads
 *  like a calendar but picks a RECURRING day; 29–31 don't exist in every month, so 28 is the
 *  ceiling (the server enforces the same). */
function BillingDayPicker({ value, onChange }: { value: number; onChange: (d: number) => void }) {
  return (
    <div>
      <label className="block font-mono text-[10px] uppercase tracking-wide text-[#141414]/50 mb-1.5">
        Billing day — invoiced on day {value} of every month
      </label>
      <div className="grid grid-cols-7 gap-1 max-w-sm">
        {Array.from({ length: 28 }, (_, i) => i + 1).map((d) => (
          <button
            key={d}
            type="button"
            onClick={() => onChange(d)}
            className={`h-8 font-mono text-xs border cursor-pointer transition ${
              d === value
                ? 'bg-[#141414] text-[#E4E3E0] border-[#141414] font-bold'
                : 'bg-white border-[#141414]/15 hover:border-[#141414]/50'
            }`}
          >
            {d}
          </button>
        ))}
      </div>
      <p className="text-[11px] text-[#141414]/45 mt-1.5">
        Months don&apos;t all have 29–31, so billing days run 1–28.
      </p>
    </div>
  );
}

/**
 * Export, with the credential decision made deliberately rather than by default.
 *
 * PPPoE passwords are plaintext of necessity (CHAP needs a retrievable secret), so putting
 * them in every export makes one click a bulk credential dump. They stay available — an ISP
 * must be able to leave with everything, or they'd have to re-provision every customer's
 * router by hand — it just becomes a choice, and the server records it.
 */
function ExportDialog({
  onClose, onExport,
}: {
  onClose: () => void;
  onExport: (includeCredentials: boolean) => void;
}) {
  const [withCreds, setWithCreds] = useState(false);
  return (
    <div className="fixed inset-0 z-50 bg-[#141414]/50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white border border-[#141414] w-full max-w-md" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b border-[#141414]">
          <h3 className="font-bold font-mono uppercase text-sm flex items-center gap-2">
            <Download className="h-4 w-4" /> Export clients
          </h3>
          <button onClick={onClose} className="cursor-pointer"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-5 space-y-4 text-sm">
          <p className="text-[11px] text-[#141414]/55 leading-relaxed">
            A CSV of every client — names, account numbers, plans, balances and billing days.
            Yours to keep, and the file you&apos;d take with you if you ever moved off WIFI.OS.
          </p>
          <label className="flex items-start gap-2.5 border border-[#141414]/15 p-3 cursor-pointer">
            <input
              type="checkbox"
              checked={withCreds}
              onChange={(e) => setWithCreds(e.target.checked)}
              className="mt-0.5"
            />
            <span>
              <b className="block text-xs">Include PPPoE passwords</b>
              <span className="block text-[11px] text-[#141414]/55 leading-relaxed mt-0.5">
                Needed to move your customers to another system without re-configuring every
                router. Treat the file like a password list — it&apos;s recorded in your audit
                log, and only you (not platform support) can download it.
              </span>
            </span>
          </label>
          <div className="flex items-center gap-2">
            <Btn variant="green" onClick={() => onExport(withCreds)}>
              <Download className="h-3.5 w-3.5" /> Download CSV
            </Btn>
            <Btn variant="outline" onClick={onClose}><X className="h-3.5 w-3.5" /> Cancel</Btn>
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * Adopt an ISP's pre-existing PPPoE users off a router into WIFI.OS. Preview first (what's
 * new / already managed / which plan each maps to), tweak name + plan per row, then import
 * the selected ones. DB-only on the server — a client's live session is never disturbed.
 */
function ImportDialog({
  routers, plans, onClose, onDone,
}: {
  routers: ApiRouter[];
  plans: PppoePlan[];
  onClose: () => void;
  onDone: () => void;
}) {
  // Two ways an ISP arrives with data: the router knows the CREDENTIALS of users already
  // dialling in; a CSV from their old billing system knows the PEOPLE. Both, not either.
  const [mode, setMode] = useState<'router' | 'csv'>('router');
  const [routerId, setRouterId] = useState<number | ''>(routers[0]?.id ?? '');
  const [rows, setRows] = useState<PppoeImportRow[] | null>(null);
  const [sel, setSel] = useState<Record<string, { include: boolean; full_name: string; plan: number | '' }>>({});
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ imported: number; skipped: number; failed: number } | null>(null);

  const preview = async () => {
    if (!routerId || busy) return;
    setBusy(true);
    setResult(null);
    try {
      const data = await api.pppoe.clients.importPreview(Number(routerId));
      setRows(data);
      const seed: typeof sel = {};
      for (const r of data) {
        seed[r.username] = {
          include: !r.already_managed,
          full_name: r.comment || r.username,
          plan: r.suggested_plan ?? '',
        };
      }
      setSel(seed);
    } catch (e) {
      toast('error', e instanceof Error ? e.message : 'Could not read the router.');
    } finally {
      setBusy(false);
    }
  };

  const run = async () => {
    if (!routerId || busy || !rows) return;
    const items: PppoeImportItem[] = rows
      .filter((r) => sel[r.username]?.include && sel[r.username]?.plan)
      .map((r) => ({
        username: r.username,
        full_name: sel[r.username].full_name,
        plan: Number(sel[r.username].plan),
      }));
    if (items.length === 0) {
      toast('warning', 'Pick at least one user and a plan for it.');
      return;
    }
    setBusy(true);
    try {
      const res = await api.pppoe.clients.importRun(Number(routerId), items);
      setResult({ imported: res.imported.length, skipped: res.skipped.length, failed: res.failed.length });
      toast('success', `Imported ${res.imported.length} client(s).`);
      onDone();
    } catch (e) {
      toast('error', e instanceof Error ? e.message : 'Import failed.');
    } finally {
      setBusy(false);
    }
  };

  const candidates = (rows ?? []).filter((r) => !r.already_managed).length;

  return (
    <div className="fixed inset-0 z-50 bg-[#141414]/50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white border border-[#141414] w-full max-w-2xl max-h-[88vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b border-[#141414]">
          <h3 className="font-bold font-mono uppercase text-sm flex items-center gap-2">
            <Upload className="h-4 w-4" /> Import clients
          </h3>
          <button onClick={onClose} className="cursor-pointer"><X className="h-4 w-4" /></button>
        </div>

        <div className="flex border-b border-[#141414]">
          {([['router', 'From the router'], ['csv', 'From a CSV file']] as const).map(([key, label]) => (
            <button
              key={key}
              onClick={() => setMode(key)}
              className={`flex-1 py-2.5 text-xs font-bold font-mono uppercase transition cursor-pointer ${
                mode === key ? 'bg-[#141414] text-[#E4E3E0]' : 'bg-white hover:bg-[#f0efec]'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {mode === 'csv' ? (
          <CsvImportPanel routers={routers} plans={plans} onClose={onClose} onDone={onDone} />
        ) : (
        <div className="p-5 space-y-4 text-sm">
          <p className="text-[11px] text-[#141414]/55 leading-relaxed">
            Reads the PPPoE accounts already on the router and adopts the ones you choose as
            managed clients — keeping their exact username/password. It never disturbs their
            live connection. Users WIFI.OS already manages are skipped.
          </p>

          <div className="flex items-end gap-2">
            <Field label="Router" className="flex-1">
              <select value={routerId} onChange={(e) => { setRouterId(Number(e.target.value)); setRows(null); }} className={inputCls}>
                {routers.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
              </select>
            </Field>
            <Btn onClick={preview} disabled={busy || !routerId}>
              {busy && rows === null ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
              Preview
            </Btn>
          </div>

          {rows && rows.length === 0 && (
            <p className="text-xs text-[#141414]/60">No PPPoE users found on this router.</p>
          )}

          {rows && rows.length > 0 && (
            <div className="border border-[#141414]/15">
              <div className="grid grid-cols-[auto_1fr_1fr_1fr] gap-2 px-3 py-2 bg-[#f0efec] font-mono text-[10px] uppercase tracking-wide text-[#141414]/50">
                <span></span><span>User</span><span>Name</span><span>Plan</span>
              </div>
              {rows.map((r) => {
                const s = sel[r.username];
                return (
                  <div key={r.username} className={`grid grid-cols-[auto_1fr_1fr_1fr] gap-2 px-3 py-2 items-center border-t border-[#141414]/10 ${r.already_managed ? 'opacity-50' : ''}`}>
                    <input
                      type="checkbox"
                      disabled={r.already_managed}
                      checked={!!s?.include}
                      onChange={(e) => setSel({ ...sel, [r.username]: { ...s, include: e.target.checked } })}
                    />
                    <span className="font-mono text-xs truncate" title={r.username}>
                      {r.username}
                      {r.already_managed && <span className="block text-[10px] text-[#141414]/50">already managed</span>}
                    </span>
                    {r.already_managed ? <span /> : (
                      <input
                        value={s?.full_name ?? ''}
                        onChange={(e) => setSel({ ...sel, [r.username]: { ...s, full_name: e.target.value } })}
                        className={`${inputCls} text-xs py-1`}
                      />
                    )}
                    {r.already_managed ? <span /> : (
                      <select
                        value={s?.plan ?? ''}
                        onChange={(e) => setSel({ ...sel, [r.username]: { ...s, plan: e.target.value ? Number(e.target.value) : '' } })}
                        className={`${inputCls} text-xs py-1`}
                      >
                        <option value="">Choose plan…</option>
                        {plans.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
                      </select>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {result && (
            <div className="text-xs font-mono border border-[#141414]/15 bg-[#faf9f7] p-2.5">
              Imported <b>{result.imported}</b> · skipped <b>{result.skipped}</b>
              {result.failed > 0 && <> · <span className="text-[#B22222]">failed {result.failed}</span></>}
            </div>
          )}

          {rows && rows.length > 0 && (
            <div className="flex items-center gap-2">
              <Btn variant="green" onClick={run} disabled={busy || candidates === 0}>
                {busy && rows !== null ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
                Import selected
              </Btn>
              <Btn variant="outline" onClick={onClose}><X className="h-3.5 w-3.5" /> Close</Btn>
            </div>
          )}
        </div>
        )}
      </div>
    </div>
  );
}

/**
 * Migrating in from another billing system. The ISP picks their exported file, we show
 * exactly what would happen to every row BEFORE anything is written, they map the plan names
 * their old system used onto their WIFI.OS plans, and only then does it import.
 *
 * Imported clients land as pending-install: we have no evidence these accounts are on a
 * router yet, and quietly marking them active would bill for customers who may not be
 * connected. The ISP presses Provision when they're ready.
 */
function CsvImportPanel({
  routers, plans, onClose, onDone,
}: {
  routers: ApiRouter[];
  plans: PppoePlan[];
  onClose: () => void;
  onDone: () => void;
}) {
  const [csv, setCsv] = useState('');
  const [fileName, setFileName] = useState('');
  const [routerId, setRouterId] = useState<number | ''>(routers[0]?.id ?? '');
  const [preview, setPreview] = useState<PppoeCsvPreview | null>(null);
  const [planMap, setPlanMap] = useState<Record<string, number | ''>>({});
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<PppoeImportResult | null>(null);

  const readFile = (file: File) => {
    const reader = new FileReader();
    reader.onload = () => {
      setCsv(String(reader.result ?? ''));
      setFileName(file.name);
      setPreview(null);
      setResult(null);
    };
    reader.readAsText(file);
  };

  const doPreview = async () => {
    if (!csv.trim() || busy) return;
    setBusy(true);
    try {
      const data = await api.pppoe.clients.importCsvPreview(csv);
      setPreview(data);
      // Pre-fill whatever we could match by name; the ISP fills in the rest.
      const seed: Record<string, number | ''> = {};
      for (const p of data.plans) seed[p.csv_plan] = p.plan ?? '';
      setPlanMap(seed);
    } catch (e) {
      toast('error', e instanceof Error ? e.message : 'Could not read that file.');
    } finally {
      setBusy(false);
    }
  };

  const unmapped = (preview?.plans ?? []).filter((p) => !planMap[p.csv_plan]);

  const run = async () => {
    if (!routerId || busy || !preview) return;
    if (unmapped.length) {
      toast('warning', `Choose a plan for "${unmapped[0].csv_plan}" first.`);
      return;
    }
    setBusy(true);
    try {
      const map: Record<string, number> = {};
      for (const [k, v] of Object.entries(planMap)) if (v) map[k] = Number(v);
      const res = await api.pppoe.clients.importCsv(csv, Number(routerId), map);
      setResult(res);
      toast('success', `Imported ${res.imported.length} client(s).`);
      onDone();
    } catch (e) {
      toast('error', e instanceof Error ? e.message : 'Import failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="p-5 space-y-4 text-sm">
      <p className="text-[11px] text-[#141414]/55 leading-relaxed">
        Bringing your customers over from another billing system? Upload its CSV export. We
        show you exactly what will happen before anything is saved. A file exported from
        WIFI.OS works as-is — that&apos;s also how you restore from a backup.
      </p>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <Field label="CSV file">
          <input
            type="file"
            accept=".csv,text/csv"
            onChange={(e) => e.target.files?.[0] && readFile(e.target.files[0])}
            className="w-full text-xs file:mr-2 file:border file:border-[#141414] file:bg-white file:px-2 file:py-1 file:text-xs file:font-mono file:cursor-pointer"
          />
        </Field>
        <Field label="Put these clients on">
          <select value={routerId} onChange={(e) => setRouterId(Number(e.target.value))} className={inputCls}>
            {routers.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
          </select>
        </Field>
      </div>

      {fileName && (
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-mono text-[#141414]/55 truncate flex-1">{fileName}</span>
          <Btn onClick={doPreview} disabled={busy || !csv.trim()}>
            {busy && !preview ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
            Preview
          </Btn>
        </div>
      )}

      {preview && (
        <>
          <div className="text-xs font-mono border border-[#141414]/15 bg-[#faf9f7] p-2.5">
            <b>{preview.importable}</b> ready to import
            {preview.blocked > 0 && (
              <> · <span className="text-[#B22222]"><b>{preview.blocked}</b> can&apos;t be</span></>
            )}
          </div>

          {preview.plans.length > 0 && (
            <div className="space-y-2">
              <p className="font-mono text-[10px] uppercase tracking-wide text-[#141414]/50">
                Match their plans to yours
              </p>
              {preview.plans.map((p) => (
                <div key={p.csv_plan} className="flex items-center gap-2">
                  <span className="flex-1 font-mono text-xs truncate">{p.csv_plan || '(no plan named)'}</span>
                  <ArrowRight className="h-3.5 w-3.5 text-[#141414]/30" />
                  <select
                    value={planMap[p.csv_plan] ?? ''}
                    onChange={(e) => setPlanMap({ ...planMap, [p.csv_plan]: e.target.value ? Number(e.target.value) : '' })}
                    className={`${inputCls} flex-1 text-xs py-1`}
                  >
                    <option value="">Choose plan…</option>
                    {plans.map((pl) => <option key={pl.id} value={pl.id}>{pl.name}</option>)}
                  </select>
                </div>
              ))}
            </div>
          )}

          <div className="border border-[#141414]/15 max-h-60 overflow-y-auto">
            <div className="grid grid-cols-[3rem_1fr_1fr_1fr] gap-2 px-3 py-2 bg-[#f0efec] font-mono text-[10px] uppercase tracking-wide text-[#141414]/50 sticky top-0">
              <span>Line</span><span>Name</span><span>Phone</span><span>Status</span>
            </div>
            {preview.rows.map((r) => (
              <div key={r.line} className={`grid grid-cols-[3rem_1fr_1fr_1fr] gap-2 px-3 py-1.5 items-center border-t border-[#141414]/10 text-xs ${r.importable ? '' : 'bg-[#B22222]/5'}`}>
                <span className="font-mono text-[#141414]/50">{r.line}</span>
                <span className="truncate">{r.full_name || <span className="text-[#141414]/40">—</span>}</span>
                <span className="font-mono truncate">{r.phone}</span>
                <span className={r.importable ? 'text-[#228B22]' : 'text-[#B22222]'}>
                  {r.importable ? 'ready' : r.problem}
                </span>
              </div>
            ))}
          </div>
        </>
      )}

      {result && (
        <div className="text-xs font-mono border border-[#141414]/15 bg-[#faf9f7] p-2.5 space-y-1">
          <div>
            Imported <b>{result.imported.length}</b> · skipped <b>{result.skipped.length}</b>
            {result.failed.length > 0 && <> · <span className="text-[#B22222]">failed {result.failed.length}</span></>}
          </div>
          {result.imported.length > 0 && (
            <p className="text-[11px] text-[#141414]/55 leading-relaxed">
              They&apos;re saved as <b>pending install</b>. Press Provision on each (or fix
              anything first) to push them to the router.
            </p>
          )}
        </div>
      )}

      <div className="flex items-center gap-2">
        {preview && preview.importable > 0 && (
          <Btn variant="green" onClick={run} disabled={busy || !routerId}>
            {busy && preview ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
            Import {preview.importable} client{preview.importable === 1 ? '' : 's'}
          </Btn>
        )}
        <Btn variant="outline" onClick={onClose}><X className="h-3.5 w-3.5" /> Close</Btn>
      </div>
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

/**
 * The ISP-only credentials panel: the username + password the customer's CPE dials with,
 * plus a hybrid reset (type your own, or generate) and delete. Deliberately separate from
 * the printable customer account sheet — the password must never go on the customer's copy.
 */
function CredentialsDialog({
  client, onClose, onChanged,
}: {
  client: PppoeClient;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [password, setPassword] = useState(client.pppoe_password);
  const [reveal, setReveal] = useState(false);
  const [newPwd, setNewPwd] = useState('');
  const [busy, setBusy] = useState(false);
  const [confirmDel, setConfirmDel] = useState(false);

  const copy = (text: string, what: string) =>
    navigator.clipboard?.writeText(text).then(
      () => toast('success', `${what} copied.`),
      () => toast('error', 'Could not copy.'),
    );

  const reset = async () => {
    if (busy) return;
    if (newPwd && (newPwd.length < 6 || /\s/.test(newPwd))) {
      toast('error', 'Password needs 6+ characters and no spaces.');
      return;
    }
    setBusy(true);
    try {
      const res = await api.pppoe.clients.resetPassword(client.id, newPwd || undefined);
      setPassword(res.pppoe_password);
      setNewPwd('');
      setReveal(true);
      toast('success', 'Password reset and pushed to the router.');
      onChanged();
    } catch (e) {
      toast('error', e instanceof Error ? e.message : 'Reset failed.');
    } finally {
      setBusy(false);
    }
  };

  const del = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await api.pppoe.clients.remove(client.id);
      toast('success', `${client.full_name} deleted.`);
      onChanged();
      onClose();
    } catch (e) {
      toast('error', e instanceof Error ? e.message : 'Delete failed.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-[#141414]/50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-white border border-[#141414] w-full max-w-md" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between p-4 border-b border-[#141414]">
          <h3 className="font-bold font-mono uppercase text-sm flex items-center gap-2">
            <Key className="h-4 w-4" /> PPPoE credentials
          </h3>
          <button onClick={onClose} className="cursor-pointer"><X className="h-4 w-4" /></button>
        </div>
        <div className="p-5 space-y-4 text-sm">
          <p className="text-[11px] text-[#141414]/55 leading-relaxed">
            What the customer&apos;s router (CPE) dials with — enter these in its
            {' '}<b>WAN → PPPoE</b> settings. Keep them private; don&apos;t print them on the
            customer account sheet.
          </p>

          <div>
            <label className="block font-mono text-[10px] uppercase tracking-wide text-[#141414]/50 mb-1">Username</label>
            <div className="flex items-center gap-2">
              <code className="flex-1 font-mono text-sm bg-[#f0efec] border border-[#141414]/15 px-2.5 py-1.5 break-all">{client.pppoe_username}</code>
              <Btn variant="outline" onClick={() => copy(client.pppoe_username, 'Username')} title="Copy"><Copy className="h-3.5 w-3.5" /></Btn>
            </div>
          </div>

          <div>
            <label className="block font-mono text-[10px] uppercase tracking-wide text-[#141414]/50 mb-1">Password</label>
            <div className="flex items-center gap-2">
              <code className="flex-1 font-mono text-sm bg-[#f0efec] border border-[#141414]/15 px-2.5 py-1.5 break-all">
                {reveal ? password : '•'.repeat(Math.max(password.length, 8))}
              </code>
              <Btn variant="outline" onClick={() => setReveal(!reveal)} title={reveal ? 'Hide' : 'Reveal'}>
                {reveal ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
              </Btn>
              <Btn variant="outline" onClick={() => copy(password, 'Password')} title="Copy"><Copy className="h-3.5 w-3.5" /></Btn>
            </div>
          </div>

          <div className="border-t border-[#141414]/10 pt-3 space-y-2">
            <label className="block font-mono text-[10px] uppercase tracking-wide text-[#141414]/50">Reset password</label>
            <div className="flex items-center gap-2">
              <input
                value={newPwd}
                onChange={(e) => setNewPwd(e.target.value)}
                placeholder="Type a new one, or leave blank to generate"
                className={`${inputCls} flex-1`}
              />
              <Btn variant="green" onClick={reset} disabled={busy}>
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                {newPwd ? 'Set' : 'Generate'}
              </Btn>
            </div>
            <p className="text-[11px] text-[#141414]/45">Pushed to the router immediately — update the CPE to match.</p>
          </div>

          <div className="border-t border-[#B22222]/20 pt-3">
            {confirmDel ? (
              <div className="space-y-2">
                <p className="text-xs text-[#B22222] leading-relaxed">
                  Delete <b>{client.full_name}</b>? This removes the user from the router and
                  can&apos;t be undone.
                </p>
                <div className="flex items-center gap-2">
                  <Btn variant="danger" onClick={del} disabled={busy}>
                    {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />} Yes, delete
                  </Btn>
                  <Btn variant="outline" onClick={() => setConfirmDel(false)} disabled={busy}><X className="h-3.5 w-3.5" /> Cancel</Btn>
                </div>
              </div>
            ) : (
              <Btn variant="danger" onClick={() => setConfirmDel(true)}>
                <Trash2 className="h-3.5 w-3.5" /> Delete client
              </Btn>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
