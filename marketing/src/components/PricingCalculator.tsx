import { useMemo, useState } from 'react';

/**
 * "What will this actually cost me?" — answered on the page, not in an email.
 *
 * WARNING TO THE NEXT PERSON: these tiers mirror `backend/apps/billing/pricing.py`,
 * which is the source of truth and is what an ISP is really billed. This is a
 * QUOTE, not an invoice, and it says so. If the tiers change there and not here, the
 * page lies — so if this drifts more than once, it becomes a public pricing endpoint
 * and this table gets deleted.
 */

const BASE_FEE = 500; // KES/month for the subdomain, waived in month one
const HOTSPOT_PCT = 3; // % of hotspot sales

/** Graduated like tax brackets: every ISP pays the lower rate on its first users. */
const TIERS: { upTo: number | null; rate: number }[] = [
  { upTo: 500, rate: 40 },
  { upTo: 2000, rate: 35 },
  { upTo: null, rate: 30 },
];

function pppoeFee(users: number): number {
  let remaining = Math.max(0, Math.floor(users));
  let lower = 0;
  let total = 0;
  for (const { upTo, rate } of TIERS) {
    if (remaining <= 0) break;
    const capacity = upTo === null ? remaining : Math.max(0, upTo - lower);
    const inBracket = Math.min(remaining, capacity);
    total += inBracket * rate;
    remaining -= inBracket;
    lower = upTo ?? lower;
  }
  return total;
}

const ksh = (n: number) =>
  `KES ${Math.round(n).toLocaleString('en-KE', { maximumFractionDigits: 0 })}`;

export default function PricingCalculator() {
  const [users, setUsers] = useState(150);
  const [hotspot, setHotspot] = useState(60000);

  const { pppoe, commission, total, blended } = useMemo(() => {
    const p = pppoeFee(users);
    const c = (hotspot * HOTSPOT_PCT) / 100;
    return {
      pppoe: p,
      commission: c,
      total: BASE_FEE + p + c,
      blended: users > 0 ? p / users : 0,
    };
  }, [users, hotspot]);

  return (
    <div className="border border-ink bg-card">
      <div className="border-b border-ink bg-ink px-5 py-3">
        <p className="font-mono text-[10px] font-bold uppercase tracking-widest text-paper/60">
          What you would pay
        </p>
      </div>

      <div className="grid gap-6 p-5 sm:p-7 md:grid-cols-2">
        <div className="space-y-6">
          <Slider
            label="Active PPPoE clients"
            hint="Only ACTIVE clients are billed. Suspended ones cost you nothing."
            value={users}
            min={0}
            max={5000}
            step={10}
            onChange={setUsers}
            format={(v) => v.toLocaleString('en-KE')}
          />
          <Slider
            label="Hotspot sales per month"
            hint="What your walk-in customers spend on bundles."
            value={hotspot}
            min={0}
            max={1000000}
            step={5000}
            onChange={setHotspot}
            format={(v) => ksh(v)}
          />
        </div>

        <div className="border border-ink bg-paper p-5">
          <Line label="Platform base fee" value={ksh(BASE_FEE)} sub="Flat, per month" />
          <Line
            label={`PPPoE (${users.toLocaleString('en-KE')} active)`}
            value={ksh(pppoe)}
            sub={users > 0 ? `${ksh(blended)} per client — blended` : 'Nothing to bill'}
          />
          <Line
            label={`Hotspot commission (${HOTSPOT_PCT}%)`}
            value={ksh(commission)}
            sub="Only when your customers actually pay"
          />

          <div className="mt-4 flex items-end justify-between border-t border-ink pt-4">
            <div>
              <p className="font-mono text-[10px] font-bold uppercase tracking-widest text-ink/50">
                Your monthly total
              </p>
              <p className="mt-0.5 font-mono text-[10px] text-ink/50">
                Month one is free — you pay this from month two.
              </p>
            </div>
            <p className="font-mono text-2xl font-black text-money">{ksh(total)}</p>
          </div>

          <p className="mt-4 border-t border-ink/15 pt-3 font-mono text-[10px] leading-relaxed text-ink/50">
            M-Pesa and bank transaction charges are on us, not added to this. Estimate
            only — your invoice is calculated on your real usage.
          </p>
        </div>
      </div>
    </div>
  );
}

function Slider({
  label,
  hint,
  value,
  min,
  max,
  step,
  onChange,
  format,
}: {
  label: string;
  hint: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (n: number) => void;
  format: (n: number) => string;
}) {
  return (
    <label className="block">
      <span className="flex items-baseline justify-between gap-3">
        <span className="font-mono text-[10px] font-bold uppercase tracking-wide text-ink/60">
          {label}
        </span>
        <span className="font-mono text-sm font-black">{format(value)}</span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-2 w-full accent-[#228B22]"
      />
      <span className="mt-1 block font-mono text-[10px] leading-relaxed text-ink/45">{hint}</span>
    </label>
  );
}

function Line({ label, value, sub }: { label: string; value: string; sub: string }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-ink/15 py-2.5 last:border-b-0">
      <div>
        <p className="font-mono text-[11px] font-bold uppercase">{label}</p>
        <p className="font-mono text-[10px] text-ink/50">{sub}</p>
      </div>
      <p className="shrink-0 font-mono text-sm font-bold">{value}</p>
    </div>
  );
}
