import { useState, type FormEvent } from 'react';
import { Ticket, Plus, Printer } from 'lucide-react';
import { api, ApiVoucher, ApiPlan } from '../api/client';
import {
  Badge, Btn, Field, FilterChips, inputCls, Panel, RefreshBtn, TableShell, tdCls, toast, useList, ViewHeader, fmtDateTime,
} from './ui';

const FILTERS = ['unused', 'all', 'redeemed', 'expired', 'void'] as const;
const STATUS_COLOR: Record<ApiVoucher['status'], 'green' | 'gray' | 'amber' | 'blue' | 'red'> = {
  unused: 'green',
  redeemed: 'blue',
  expired: 'gray',
  void: 'red',
};

export default function VouchersView({ plans }: { plans: ApiPlan[] }) {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('unused');
  const [showForm, setShowForm] = useState(false);
  const [planId, setPlanId] = useState<number | ''>('');
  const [countInput, setCountInput] = useState('20');
  const [prefix, setPrefix] = useState('');
  const [busy, setBusy] = useState(false);
  const { rows, count, error, reload } = useList(
    () => api.vouchers.list(filter === 'all' ? '' : `?status=${filter}`),
    [filter]
  );

  const generate = async (e: FormEvent) => {
    e.preventDefault();
    if (!planId || busy) return;
    setBusy(true);
    try {
      const created = await api.vouchers.generate({
        plan_id: Number(planId),
        count: Number(countInput),
        prefix: prefix.trim().toUpperCase(),
      });
      toast('success', `${created.length} vouchers generated.`);
      setShowForm(false);
      reload();
      printBatch(created, plans.find((p) => p.id === Number(planId))?.name ?? '');
    } catch {
      toast('error', 'Failed to generate vouchers.');
    } finally {
      setBusy(false);
    }
  };

  const printBatch = (batch: ApiVoucher[], planName: string) => {
    const cards = batch
      .map(
        (v) => `<div class="card"><div class="brand">WIFI ACCESS</div><div class="plan">${planName || v.plan_name}</div><div class="code">${v.code}</div><div class="hint">Enter this code on the WiFi login page</div></div>`
      )
      .join('');
    const win = window.open('', '_blank', 'width=800,height=600');
    if (!win) {
      toast('warning', 'Pop-up blocked — allow pop-ups to print voucher cards.');
      return;
    }
    win.document.write(`<!doctype html><html><head><title>Voucher cards</title><style>
      body{font-family:monospace;display:flex;flex-wrap:wrap;gap:8px;padding:12px}
      .card{border:1.5px solid #141414;padding:10px 14px;width:200px;text-align:center;page-break-inside:avoid}
      .brand{font-size:10px;letter-spacing:2px;opacity:.6}
      .plan{font-size:12px;font-weight:bold;margin-top:4px}
      .code{font-size:20px;font-weight:900;letter-spacing:3px;margin:8px 0;border:1px dashed #141414;padding:6px}
      .hint{font-size:9px;opacity:.6}
    </style></head><body>${cards}<script>window.print()</${'script'}></body></html>`);
    win.document.close();
  };

  return (
    <div className="space-y-5 text-[#141414]">
      <ViewHeader
        icon={<Ticket className="h-4.5 w-4.5" />}
        title="Vouchers"
        subtitle="Printed scratch-card style codes sold by attendants and shops. Single-use, generated in batches."
      >
        <Btn onClick={() => setShowForm(!showForm)}>
          <Plus className="h-3.5 w-3.5" /> Generate Batch
        </Btn>
        <RefreshBtn onClick={reload} />
      </ViewHeader>

      {showForm && (
        <Panel title="Generate voucher batch">
          <form onSubmit={generate} className="grid grid-cols-1 md:grid-cols-5 gap-3 items-end">
            <Field label="Plan" className="md:col-span-2">
              <select required value={planId} onChange={(e) => setPlanId(Number(e.target.value))} className={inputCls}>
                <option value="">Select a plan…</option>
                {plans.filter((p) => p.is_active).map((p) => (
                  <option key={p.id} value={p.id}>{p.name} — KSh {Number(p.price).toLocaleString()}</option>
                ))}
              </select>
            </Field>
            <Field label="How many (1–1000)">
              <input type="number" min="1" max="1000" required value={countInput} onChange={(e) => setCountInput(e.target.value)} className={inputCls} />
            </Field>
            <Field label="Prefix (optional)">
              <input maxLength={6} value={prefix} onChange={(e) => setPrefix(e.target.value.toUpperCase())} className={inputCls} placeholder="e.g. KIB" />
            </Field>
            <Btn type="submit" variant="green" disabled={busy}>
              <Printer className="h-3.5 w-3.5" />
              {busy ? 'Generating…' : 'Generate + Print'}
            </Btn>
          </form>
        </Panel>
      )}

      <FilterChips options={FILTERS} value={filter} onChange={setFilter} right={<span className="text-[11px] font-mono text-[#141414]/50">{count} vouchers</span>} />

      <TableShell
        headers={['Code', 'Plan', 'Status', 'Redeemed', 'Created']}
        loading={rows === null}
        error={error}
        empty="No vouchers in this list. Generate a batch to get started."
      >
        {(rows ?? []).map((v) => (
          <tr key={v.id} className="hover:bg-[#f0efec]/40 transition">
            <td className={`${tdCls} font-mono font-black tracking-widest`}>{v.code}</td>
            <td className={tdCls}>{v.plan_name}</td>
            <td className={tdCls}><Badge color={STATUS_COLOR[v.status]}>{v.status}</Badge></td>
            <td className={`${tdCls} font-mono whitespace-nowrap`}>{fmtDateTime(v.redeemed_at)}</td>
            <td className={`${tdCls} font-mono whitespace-nowrap`}>{fmtDateTime(v.created_at)}</td>
          </tr>
        ))}
      </TableShell>
    </div>
  );
}
