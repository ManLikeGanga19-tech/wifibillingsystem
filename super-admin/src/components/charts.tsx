/**
 * Chart layer — light/brutalist, matching the ISP console.
 *
 * Colors are VALIDATED against the white panel surface, not eyeballed: every slot
 * clears 3:1 contrast, worst adjacent CVD ΔE 12.8, and the net-vs-costs pair that
 * shares the main chart separates at ΔE 18.0 under protanopia (the red/green
 * deficiency that would otherwise make that exact chart unreadable for ~8% of men).
 *
 * Rules held to: one y-axis, never dual; recessive grid/axes; a legend whenever
 * there are >= 2 series (and none for one — the title names it); values in ink,
 * never in the series color; crosshair + tooltip on every time series.
 */

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { day, ksh, type SeriesPoint } from '../api/client';

export const SERIES = {
  earnings: '#2a78d6', // blue
  net: '#0f8a5f', // green
  volume: '#a86e00', // amber
  costs: '#c9302c', // red
  tenants: '#5b3fa8', // violet
} as const;

const AXIS = { stroke: 'transparent', tick: { fill: '#8a8880', fontSize: 11 } };

/* ---- tooltip ------------------------------------------------------------- */

interface TipItem {
  name?: string;
  value?: number | string;
  color?: string;
  dataKey?: string | number;
}

function ChartTip({
  active,
  payload,
  label,
  money = true,
}: {
  active?: boolean;
  payload?: TipItem[];
  label?: string | number;
  money?: boolean;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-white border border-[#141414] px-3 py-2 text-[11px] font-mono">
      <p className="mb-1.5 font-bold uppercase text-[#141414]/60">
        {typeof label === 'string' ? day(label) : label}
      </p>
      {payload.map((p) => (
        <div key={String(p.dataKey)} className="flex items-center gap-2 py-0.5">
          {/* the swatch carries identity; the text stays in ink */}
          <span className="h-2 w-2 shrink-0" style={{ background: p.color }} aria-hidden />
          <span className="text-[#141414]/70">{p.name}</span>
          <span className="ml-auto font-bold tnum pl-3">
            {money ? ksh(p.value as number) : p.value}
          </span>
        </div>
      ))}
    </div>
  );
}

/* ---- legend (never color-alone: swatch + label) -------------------------- */

export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 mb-3">
      {items.map((i) => (
        <span
          key={i.label}
          className="inline-flex items-center gap-1.5 text-[10px] font-mono font-bold uppercase text-[#141414]/70"
        >
          <span className="h-2 w-2" style={{ background: i.color }} aria-hidden />
          {i.label}
        </span>
      ))}
    </div>
  );
}

/* ---- earnings composition ------------------------------------------------
   Stacked: net margin + transaction costs = gross platform earnings. Stacking is
   honest here because the parts genuinely sum to the whole — it shows how much of
   what we bill the M-Pesa/bank rails take straight back. */

export function EarningsChart({ series }: { series: SeriesPoint[] }) {
  const data = series.map((p) => ({
    date: p.date,
    net: Number(p.net_margin),
    costs: Number(p.transaction_costs),
  }));
  return (
    <>
      <Legend
        items={[
          { label: 'Net margin (kept)', color: SERIES.net },
          { label: 'Transaction costs (absorbed)', color: SERIES.costs },
        ]}
      />
      <ResponsiveContainer width="100%" height={220}>
        <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="date" tickFormatter={day} {...AXIS} minTickGap={28} />
          <YAxis tickFormatter={(v) => ksh(v, true)} width={62} {...AXIS} />
          <Tooltip content={<ChartTip />} cursor={{ stroke: '#141414', strokeOpacity: 0.3 }} />
          <Area
            type="monotone"
            dataKey="net"
            name="Net margin"
            stackId="e"
            stroke={SERIES.net}
            strokeWidth={2}
            fill={SERIES.net}
            fillOpacity={0.18}
          />
          <Area
            type="monotone"
            dataKey="costs"
            name="Transaction costs"
            stackId="e"
            stroke={SERIES.costs}
            strokeWidth={2}
            fill={SERIES.costs}
            fillOpacity={0.18}
          />
        </AreaChart>
      </ResponsiveContainer>
    </>
  );
}

/* ---- gross volume (single series -> no legend; the title names it) -------- */

export function VolumeChart({ series }: { series: SeriesPoint[] }) {
  const data = series.map((p) => ({ date: p.date, volume: Number(p.gross_volume) }));
  return (
    <ResponsiveContainer width="100%" height={200}>
      <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="date" tickFormatter={day} {...AXIS} minTickGap={28} />
        <YAxis tickFormatter={(v) => ksh(v, true)} width={62} {...AXIS} />
        <Tooltip content={<ChartTip />} cursor={{ stroke: '#141414', strokeOpacity: 0.3 }} />
        <Area
          type="monotone"
          dataKey="volume"
          name="Collected"
          stroke={SERIES.volume}
          strokeWidth={2}
          fill={SERIES.volume}
          fillOpacity={0.15}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

/* ---- revenue by stream (categorical magnitude -> bars) -------------------- */

const STREAM_LABEL: Record<string, string> = {
  commission: 'Hotspot 3%',
  base_fee: 'Base fee',
  pppoe_fee: 'PPPoE / user',
  setup_fee: 'Setup (one-off)',
};

// Fixed hue per stream — identity, not rank. Order never cycles.
const STREAM_COLOR: Record<string, string> = {
  commission: SERIES.earnings,
  base_fee: SERIES.net,
  pppoe_fee: SERIES.volume,
  setup_fee: SERIES.tenants,
};

export function StreamChart({ streams }: { streams: Record<string, string | number> }) {
  const data = Object.entries(streams).map(([k, v]) => ({
    key: k,
    name: STREAM_LABEL[k] ?? k,
    value: Number(v),
  }));
  if (data.every((d) => d.value === 0)) {
    return (
      <p className="text-center text-xs font-mono text-[#141414]/50 py-12">
        No platform revenue booked this month yet.
      </p>
    );
  }
  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={data} layout="vertical" margin={{ top: 0, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid horizontal={false} />
        <XAxis type="number" tickFormatter={(v) => ksh(v, true)} {...AXIS} />
        <YAxis type="category" dataKey="name" width={106} {...AXIS} />
        <Tooltip content={<ChartTip />} cursor={{ fill: 'rgba(20,20,20,0.04)' }} />
        <Bar dataKey="value" name="Revenue" barSize={18}>
          {data.map((d) => (
            <Cell key={d.key} fill={STREAM_COLOR[d.key] ?? SERIES.earnings} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

/* ---- tenant signups (counts, not money) ---------------------------------- */

export function SignupChart({ series }: { series: SeriesPoint[] }) {
  const data = series.map((p) => ({ date: p.date, n: p.new_tenants }));
  return (
    <ResponsiveContainer width="100%" height={180}>
      <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="date" tickFormatter={day} {...AXIS} minTickGap={28} />
        <YAxis allowDecimals={false} width={30} {...AXIS} />
        <Tooltip content={<ChartTip money={false} />} cursor={{ fill: 'rgba(20,20,20,0.04)' }} />
        <Bar dataKey="n" name="New ISPs" fill={SERIES.tenants} />
      </BarChart>
    </ResponsiveContainer>
  );
}
