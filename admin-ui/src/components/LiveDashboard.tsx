import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  TrendingUp,
  RefreshCw,
  Loader2,
  Activity,
  Users,
  Ticket,
  AlertTriangle,
  Router as RouterIcon,
  Eye,
  EyeOff,
} from 'lucide-react';
import { api, DashboardStats } from '../api/client';

/* Chart palette (validated with the dataviz color checks):
 * single-series marks: #228B22 (green) · categorical pair: M-Pesa #228B22 / Voucher #2563EB
 * Ink #141414 is reserved for text, axes and grid — never a data series. */
const GREEN = '#228B22';
const BLUE = '#2563EB';
const INK = '#141414';

const ksh = (v: number | string) =>
  `KSh ${Number(v).toLocaleString('en-KE', { maximumFractionDigits: 0 })}`;

export default function LiveDashboard({ onNavigate }: { onNavigate: (tab: string) => void }) {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [error, setError] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  /** Privacy toggle for the commercially sensitive figures. In-memory ONLY — this
   *  system stores nothing in the browser, and a persisted "hidden" flag is exactly
   *  the kind of stale state that later makes a product look broken. */
  const [isPrivate, setPrivate] = useState(false);

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      setStats(await api.stats());
      setError('');
    } catch {
      setError('Could not load dashboard data. Is the API running?');
    } finally {
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    load();
    const t = window.setInterval(load, 30_000);
    return () => window.clearInterval(t);
  }, [load]);

  if (!stats && !error)
    return (
      <div className="flex justify-center py-24">
        <Loader2 className="h-8 w-8 animate-spin text-[#141414]/40" />
      </div>
    );

  if (error && !stats)
    return (
      <div className="bg-white border border-[#141414] p-8 text-center space-y-3">
        <AlertTriangle className="h-8 w-8 mx-auto text-[#B22222]" />
        <p className="text-sm font-mono">{error}</p>
        <button onClick={load} className="px-4 py-2 bg-[#141414] text-[#E4E3E0] text-xs font-bold font-mono uppercase cursor-pointer">
          Retry
        </button>
      </div>
    );

  const { kpis } = stats!;
  const monthDelta =
    Number(kpis.revenue_prev_month) > 0
      ? Math.round(
          (100 * (Number(kpis.revenue_month) - Number(kpis.revenue_prev_month))) /
            Number(kpis.revenue_prev_month)
        )
      : null;

  return (
    <div className="space-y-6 text-[#141414]">
      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="text-sm font-serif italic font-bold flex items-center gap-2 uppercase">
            <TrendingUp className="h-4.5 w-4.5" />
            <span>Business Overview</span>
          </h2>
          <p className="text-xs font-mono text-[#141414]/70 mt-0.5">
            Live revenue, sessions and network health. Auto-refreshes every 30 seconds.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {/* Hide the commercially sensitive figures — for demoing the console,
              screen-sharing with a supplier, or working in a public place.
              Deliberately NOT persisted (no browser storage anywhere), so it
              resets on reload and can never leave someone's numbers hidden by a
              setting they've forgotten about. */}
          <button
            onClick={() => setPrivate((p) => !p)}
            title={isPrivate ? 'Show revenue figures' : 'Hide revenue figures'}
            aria-pressed={isPrivate}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-bold font-mono border border-[#141414] hover:bg-[#141414] hover:text-white transition cursor-pointer uppercase"
          >
            {isPrivate ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
            {isPrivate ? 'Show' : 'Hide'}
          </button>
          <button
            onClick={load}
            className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-bold font-mono border border-[#141414] hover:bg-[#141414] hover:text-white transition cursor-pointer uppercase"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${refreshing ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      {/* KPI tiles */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Tile label="Revenue Today" value={ksh(kpis.revenue_today)} accent hidden={isPrivate} />
        <Tile
          label="Revenue This Month"
          value={ksh(kpis.revenue_month)}
          sub={monthDelta !== null ? `${monthDelta >= 0 ? '+' : ''}${monthDelta}% vs last month` : undefined}
          accent
          hidden={isPrivate}
        />
        <Tile label="Active Sessions" value={String(kpis.active_sessions)} sub={`${kpis.sessions_expiring_1h} expiring < 1h`} />
        <Tile
          label="Success Rate (7d)"
          value={kpis.success_rate_7d !== null ? `${kpis.success_rate_7d}%` : '—'}
          sub={`${kpis.failed_today} failed today`}
        />
        <Tile
          label="Total Clients"
          value={kpis.total_subscribers.toLocaleString()}
          sub={`+${kpis.new_subscribers_7d} this week`}
          hidden={isPrivate}
        />
        <Tile
          label="Avg Revenue / Client"
          value={kpis.arpu_month !== null ? ksh(kpis.arpu_month) : '—'}
          sub="this month"
          hidden={isPrivate}
        />
        <Tile label="Payments Today" value={String(kpis.transactions_today)} hidden={isPrivate} />
        <Tile label="Vouchers In Stock" value={kpis.unused_vouchers.toLocaleString()} sub={`${kpis.vouchers_redeemed_7d} redeemed (7d)`} />
      </div>

      {/* Charts row 1 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Panel title="Revenue — last 30 days" className="lg:col-span-2">
          <RevenueChart data={stats!.revenue_daily} />
        </Panel>
        <Panel title="How clients pay — last 30 days">
          <PaymentSplit split={stats!.payment_split} />
        </Panel>
      </div>

      {/* Charts row 2 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Panel title="Busiest hours — payments by hour (7d)" className="lg:col-span-2">
          <HourBars data={stats!.tx_by_hour} />
        </Panel>
        <Panel title="Top plans by revenue — this month">
          <PlanBars data={stats!.plan_breakdown} />
        </Panel>
      </div>

      {/* Routers */}
      <Panel title="Sites & routers">
        {stats!.routers.length === 0 ? (
          <p className="text-xs font-mono text-[#141414]/50 py-4 text-center">No routers configured yet.</p>
        ) : (
          <div className="divide-y divide-[#141414]/10">
            {stats!.routers.map((r) => (
              <div key={r.id} className="flex items-center justify-between py-2.5">
                <div className="flex items-center gap-2.5">
                  <RouterIcon className="h-4 w-4 opacity-60" />
                  <span className="text-sm font-bold">{r.name}</span>
                </div>
                <div className="flex items-center gap-4 font-mono text-xs">
                  <span className="flex items-center gap-1.5">
                    <Activity className="h-3.5 w-3.5 opacity-50" />
                    {r.active_sessions} active
                  </span>
                  <span
                    className={`flex items-center gap-1.5 font-bold uppercase ${
                      r.status === 'online' ? 'text-[#228B22]' : r.status === 'offline' ? 'text-[#B22222]' : 'text-[#141414]/50'
                    }`}
                  >
                    <span
                      className={`w-2 h-2 rounded-full ${
                        r.status === 'online' ? 'bg-[#228B22]' : r.status === 'offline' ? 'bg-[#B22222]' : 'bg-[#141414]/30'
                      }`}
                    />
                    {r.status}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <div className="flex gap-3 flex-wrap">
        <QuickLink label="View payments" onClick={() => onNavigate('payments')} icon={<Activity className="h-3.5 w-3.5" />} />
        <QuickLink label="Manage packages" onClick={() => onNavigate('packages')} icon={<TrendingUp className="h-3.5 w-3.5" />} />
        <QuickLink label="Vouchers" onClick={() => onNavigate('vouchers')} icon={<Ticket className="h-3.5 w-3.5" />} />
        <QuickLink label="Message clients" onClick={() => onNavigate('campaigns')} icon={<Users className="h-3.5 w-3.5" />} />
      </div>
    </div>
  );
}

// ---- building blocks -------------------------------------------------------

/** `hidden` masks the figure AND its sub-line — a "+12% vs last month" next to a
 *  row of dots would leak the very thing we're hiding. The layout must not shift,
 *  or the mask becomes a tell. */
function Tile({
  label,
  value,
  sub,
  accent,
  hidden,
}: {
  label: string;
  value: string;
  sub?: string;
  accent?: boolean;
  hidden?: boolean;
}) {
  const MASK = '••••••';
  return (
    <div className="bg-white border border-[#141414] p-3.5">
      <p className="text-[11px] font-mono uppercase text-[#141414]/60">{label}</p>
      <p
        className={`text-xl font-black font-mono mt-1 leading-none ${
          hidden ? 'text-[#141414]/30 select-none' : accent ? 'text-[#228B22]' : ''
        }`}
        aria-label={hidden ? `${label} hidden` : undefined}
      >
        {hidden ? MASK : value}
      </p>
      {sub && (
        <p className="text-[11px] font-mono text-[#141414]/50 mt-1.5">
          {hidden ? ' ' : sub}
        </p>
      )}
    </div>
  );
}

function Panel({ title, children, className = '' }: { title: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-white border border-[#141414] p-4 ${className}`}>
      <h3 className="text-xs font-bold font-mono uppercase tracking-wide mb-3">{title}</h3>
      {children}
    </div>
  );
}

function QuickLink({ label, onClick, icon }: { label: string; onClick: () => void; icon: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className="inline-flex items-center gap-1.5 px-3 py-2 text-xs font-bold font-mono border border-[#141414] bg-white hover:bg-[#141414] hover:text-white transition cursor-pointer uppercase"
    >
      {icon}
      {label}
    </button>
  );
}

function EmptyChart({ hint }: { hint: string }) {
  return <p className="text-xs font-mono text-[#141414]/50 py-10 text-center">{hint}</p>;
}

// ---- Revenue line/area (single series, green) ------------------------------

function RevenueChart({ data }: { data: DashboardStats['revenue_daily'] }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 600;
  const H = 180;
  const PAD = { l: 46, r: 14, t: 12, b: 22 };

  const points = useMemo(() => data.map((d) => ({ ...d, revenue: Number(d.revenue) })), [data]);
  if (points.length === 0) return <EmptyChart hint="No paid transactions yet — revenue will appear here." />;

  const max = Math.max(...points.map((p) => p.revenue), 1);
  const x = (i: number) => (points.length === 1 ? W / 2 : PAD.l + (i * (W - PAD.l - PAD.r)) / (points.length - 1));
  const y = (v: number) => PAD.t + (1 - v / max) * (H - PAD.t - PAD.b);

  const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i)},${y(p.revenue)}`).join(' ');
  const area = `${path} L${x(points.length - 1)},${H - PAD.b} L${x(0)},${H - PAD.b} Z`;
  const gridVals = [max, max / 2];
  const hovered = hover !== null ? points[hover] : null;

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="w-full"
        onMouseLeave={() => setHover(null)}
        onMouseMove={(e) => {
          const rect = e.currentTarget.getBoundingClientRect();
          const px = ((e.clientX - rect.left) / rect.width) * W;
          let best = 0;
          points.forEach((_, i) => {
            if (Math.abs(x(i) - px) < Math.abs(x(best) - px)) best = i;
          });
          setHover(best);
        }}
      >
        {gridVals.map((v) => (
          <g key={v}>
            <line x1={PAD.l} x2={W - PAD.r} y1={y(v)} y2={y(v)} stroke={INK} strokeOpacity={0.1} />
            <text x={PAD.l - 6} y={y(v) + 3} textAnchor="end" fontSize={9} fill={INK} fillOpacity={0.5} fontFamily="monospace">
              {Number(v) >= 1000 ? `${Math.round(v / 1000)}k` : Math.round(v)}
            </text>
          </g>
        ))}
        <line x1={PAD.l} x2={W - PAD.r} y1={H - PAD.b} y2={H - PAD.b} stroke={INK} strokeOpacity={0.25} />
        {points.length > 1 && <path d={area} fill={GREEN} fillOpacity={0.08} />}
        {points.length > 1 && <path d={path} fill="none" stroke={GREEN} strokeWidth={2} />}
        {points.map((p, i) => (
          <circle
            key={p.day}
            cx={x(i)}
            cy={y(p.revenue)}
            r={hover === i ? 4.5 : points.length <= 2 ? 4 : 2}
            fill={GREEN}
            stroke="#fff"
            strokeWidth={hover === i ? 2 : 0}
          />
        ))}
        {points.map(
          (p, i) =>
            (i === 0 || i === points.length - 1 || points.length <= 7) && (
              <text key={`t-${p.day}`} x={x(i)} y={H - 8} textAnchor="middle" fontSize={9} fill={INK} fillOpacity={0.55} fontFamily="monospace">
                {p.day.slice(5)}
              </text>
            )
        )}
      </svg>
      {hovered && (
        <div
          className="absolute -top-1 bg-[#141414] text-[#E4E3E0] font-mono text-[11px] px-2 py-1 pointer-events-none whitespace-nowrap"
          style={{ left: `${(x(hover!) / W) * 100}%`, transform: 'translateX(-50%)' }}
        >
          {hovered.day} · {ksh(hovered.revenue)} · {hovered.transactions} payment{hovered.transactions !== 1 ? 's' : ''}
        </div>
      )}
    </div>
  );
}

// ---- Payments-by-hour bars (single series, green) ---------------------------

function HourBars({ data }: { data: DashboardStats['tx_by_hour'] }) {
  const [hover, setHover] = useState<number | null>(null);
  const W = 600;
  const H = 160;
  const PAD = { l: 26, r: 8, t: 10, b: 20 };
  const max = Math.max(...data.map((d) => d.count), 1);
  const total = data.reduce((a, d) => a + d.count, 0);
  if (total === 0) return <EmptyChart hint="No payments in the last 7 days yet." />;

  const bw = (W - PAD.l - PAD.r) / 24;
  const peak = data.reduce((best, d) => (d.count > best.count ? d : best), data[0]);

  return (
    <div className="relative">
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" onMouseLeave={() => setHover(null)}>
        <line x1={PAD.l} x2={W - PAD.r} y1={H - PAD.b} y2={H - PAD.b} stroke={INK} strokeOpacity={0.25} />
        {data.map((d, i) => {
          const h = (d.count / max) * (H - PAD.t - PAD.b);
          return (
            <g key={d.hour}>
              <rect
                x={PAD.l + i * bw + 1}
                y={H - PAD.b - h}
                width={bw - 2}
                height={Math.max(h, d.count > 0 ? 2 : 0)}
                rx={2}
                fill={GREEN}
                fillOpacity={hover === null || hover === i ? 1 : 0.35}
                onMouseEnter={() => setHover(i)}
              />
              {/* invisible fat hit target */}
              <rect x={PAD.l + i * bw} y={PAD.t} width={bw} height={H - PAD.t - PAD.b} fill="transparent" onMouseEnter={() => setHover(i)} />
            </g>
          );
        })}
        {[0, 6, 12, 18, 23].map((hr) => (
          <text key={hr} x={PAD.l + hr * bw + bw / 2} y={H - 6} textAnchor="middle" fontSize={9} fill={INK} fillOpacity={0.55} fontFamily="monospace">
            {String(hr).padStart(2, '0')}
          </text>
        ))}
        {peak.count > 0 && hover === null && (
          <text
            x={PAD.l + peak.hour * bw + bw / 2}
            y={H - PAD.b - (peak.count / max) * (H - PAD.t - PAD.b) - 5}
            textAnchor="middle"
            fontSize={10}
            fontWeight="bold"
            fill={INK}
            fontFamily="monospace"
          >
            {peak.count}
          </text>
        )}
      </svg>
      {hover !== null && (
        <div
          className="absolute top-0 bg-[#141414] text-[#E4E3E0] font-mono text-[11px] px-2 py-1 pointer-events-none whitespace-nowrap"
          style={{ left: `${((PAD.l + hover * bw) / W) * 100}%` }}
        >
          {String(hover).padStart(2, '0')}:00 — {data[hover].count} payment{data[hover].count !== 1 ? 's' : ''}
        </div>
      )}
      <p className="text-[11px] font-mono text-[#141414]/50 mt-1">Hour of day (EAT) — plan staffing and capacity around the peak.</p>
    </div>
  );
}

// ---- Top plans horizontal bars (magnitude, single hue) ----------------------

function PlanBars({ data }: { data: DashboardStats['plan_breakdown'] }) {
  if (data.length === 0) return <EmptyChart hint="No revenue this month yet." />;
  const max = Math.max(...data.map((d) => Number(d.revenue)), 1);
  return (
    <div className="space-y-2.5">
      {data.map((d) => (
        <div key={d.plan__name} title={`${d.plan__name}: ${ksh(d.revenue)} from ${d.count} payments`}>
          <div className="flex justify-between text-[11px] font-mono mb-0.5">
            <span className="truncate pr-2">{d.plan__name}</span>
            <span className="font-bold whitespace-nowrap">{ksh(d.revenue)}</span>
          </div>
          <div className="h-3 bg-[#141414]/8">
            <div className="h-full" style={{ width: `${(Number(d.revenue) / max) * 100}%`, background: GREEN, borderRadius: '0 2px 2px 0' }} />
          </div>
        </div>
      ))}
    </div>
  );
}

// ---- Payment source split (categorical pair: green / blue) ------------------

function PaymentSplit({ split }: { split: DashboardStats['payment_split'] }) {
  const total = split.mpesa + split.voucher;
  if (total === 0) return <EmptyChart hint="No sessions in the last 30 days yet." />;
  const mp = (split.mpesa / total) * 100;
  return (
    <div className="space-y-4">
      <div className="flex h-8" style={{ gap: 2 }}>
        {split.mpesa > 0 && <div style={{ width: `${mp}%`, background: GREEN, borderRadius: 2 }} title={`M-Pesa: ${split.mpesa}`} />}
        {split.voucher > 0 && <div style={{ width: `${100 - mp}%`, background: BLUE, borderRadius: 2 }} title={`Voucher: ${split.voucher}`} />}
      </div>
      <div className="space-y-2 font-mono text-xs">
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-2">
            <span className="w-3 h-3 shrink-0" style={{ background: GREEN }} />
            M-Pesa
          </span>
          <b>
            {split.mpesa.toLocaleString()} ({Math.round(mp)}%)
          </b>
        </div>
        <div className="flex items-center justify-between">
          <span className="flex items-center gap-2">
            <span className="w-3 h-3 shrink-0" style={{ background: BLUE }} />
            Voucher
          </span>
          <b>
            {split.voucher.toLocaleString()} ({Math.round(100 - mp)}%)
          </b>
        </div>
      </div>
      <p className="text-[11px] font-mono text-[#141414]/50">Sessions started, by payment source.</p>
    </div>
  );
}
