/**
 * Chart layer.
 *
 * Colors come from the VALIDATED categorical palette (see index.css) — worst
 * adjacent CVD ΔE 35.9 on this surface, every slot >= 3:1 contrast. Hues are
 * assigned to entities in fixed order and never cycled: a filter that drops a
 * series must not repaint the survivors.
 *
 * Rules held to here: one y-axis only (never dual); recessive grid/axes; a
 * legend whenever there are >= 2 series (and none when there is one — the title
 * names it); values in text tokens, never in the series color; crosshair +
 * tooltip on every time series.
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
  earnings: '#3987e5', // slot 1 blue
  net: '#199e70', // slot 2 aqua
  volume: '#c98500', // slot 3 yellow
  costs: '#e66767', // slot 4 red
  tenants: '#9085e9', // slot 5 violet
} as const;

const AXIS = { stroke: 'transparent', tick: { fill: '#64748b', fontSize: 11 } };

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
    <div
      className="rounded-lg border px-3 py-2 text-xs shadow-xl"
      style={{
        background: 'var(--surface-2)',
        borderColor: 'var(--hairline-strong)',
        color: 'var(--text-primary)',
      }}
    >
      <p className="mb-1.5 font-medium" style={{ color: 'var(--text-secondary)' }}>
        {typeof label === 'string' ? day(label) : label}
      </p>
      {payload.map((p) => (
        <div key={String(p.dataKey)} className="flex items-center gap-2 py-0.5">
          {/* the chip carries identity; the text stays in ink tokens */}
          <span
            className="h-2 w-2 rounded-sm shrink-0"
            style={{ background: p.color }}
            aria-hidden
          />
          <span style={{ color: 'var(--text-secondary)' }}>{p.name}</span>
          <span className="ml-auto tnum font-medium">
            {money ? ksh(p.value as number) : p.value}
          </span>
        </div>
      ))}
    </div>
  );
}

/* ---- legend (never color-alone: chip + label) ---------------------------- */

export function Legend({ items }: { items: { label: string; color: string }[] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 mb-3">
      {items.map((i) => (
        <span
          key={i.label}
          className="inline-flex items-center gap-1.5 text-[11px]"
          style={{ color: 'var(--text-secondary)' }}
        >
          <span className="h-2 w-2 rounded-sm" style={{ background: i.color }} aria-hidden />
          {i.label}
        </span>
      ))}
    </div>
  );
}

/* ---- earnings composition ------------------------------------------------
   Stacked: net margin + transaction costs = gross platform earnings. Stacking is
   honest here because the parts genuinely sum to the whole — it shows how much
   of what we earn the M-Pesa/bank rails take back. */

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
          <YAxis tickFormatter={(v) => ksh(v, true)} width={64} {...AXIS} />
          <Tooltip content={<ChartTip />} cursor={{ stroke: 'var(--hairline-strong)' }} />
          <Area
            type="monotone"
            dataKey="net"
            name="Net margin"
            stackId="e"
            stroke={SERIES.net}
            strokeWidth={2}
            fill={SERIES.net}
            fillOpacity={0.22}
          />
          <Area
            type="monotone"
            dataKey="costs"
            name="Transaction costs"
            stackId="e"
            stroke={SERIES.costs}
            strokeWidth={2}
            fill={SERIES.costs}
            fillOpacity={0.22}
          />
        </AreaChart>
      </ResponsiveContainer>
    </>
  );
}

/* ---- gross volume (single series -> no legend; the title names it) ------- */

export function VolumeChart({ series }: { series: SeriesPoint[] }) {
  const data = series.map((p) => ({ date: p.date, volume: Number(p.gross_volume) }));
  return (
    <ResponsiveContainer width="100%" height={200}>
      <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="date" tickFormatter={day} {...AXIS} minTickGap={28} />
        <YAxis tickFormatter={(v) => ksh(v, true)} width={64} {...AXIS} />
        <Tooltip content={<ChartTip />} cursor={{ stroke: 'var(--hairline-strong)' }} />
        <Area
          type="monotone"
          dataKey="volume"
          name="Collected"
          stroke={SERIES.volume}
          strokeWidth={2}
          fill={SERIES.volume}
          fillOpacity={0.18}
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

/* ---- revenue by stream (categorical magnitude -> bars, one per stream) ---- */

const STREAM_LABEL: Record<string, string> = {
  commission: 'Hotspot 3%',
  base_fee: 'Base fee',
  pppoe_fee: 'PPPoE per-user',
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
  const empty = data.every((d) => d.value === 0);
  if (empty) {
    return (
      <p className="text-center text-xs py-12" style={{ color: 'var(--text-muted)' }}>
        No platform revenue booked this month yet.
      </p>
    );
  }
  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={data} layout="vertical" margin={{ top: 0, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid horizontal={false} />
        <XAxis type="number" tickFormatter={(v) => ksh(v, true)} {...AXIS} />
        <YAxis type="category" dataKey="name" width={104} {...AXIS} />
        <Tooltip content={<ChartTip />} cursor={{ fill: 'rgba(255,255,255,0.03)' }} />
        {/* 4px rounded data-end, anchored to the baseline */}
        <Bar dataKey="value" name="Revenue" radius={[0, 4, 4, 0]} barSize={18}>
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
    <ResponsiveContainer width="100%" height={160}>
      <BarChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 0 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="date" tickFormatter={day} {...AXIS} minTickGap={28} />
        <YAxis allowDecimals={false} width={32} {...AXIS} />
        <Tooltip
          content={<ChartTip money={false} />}
          cursor={{ fill: 'rgba(255,255,255,0.03)' }}
        />
        <Bar dataKey="n" name="New ISPs" fill={SERIES.tenants} radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}
