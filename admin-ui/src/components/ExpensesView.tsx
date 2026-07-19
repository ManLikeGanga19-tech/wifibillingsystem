import { useEffect, useMemo, useState, type FormEvent } from 'react';
import { Wallet, Plus, Building2 } from 'lucide-react';
import { api, ApiExpense, PlatformFees } from '../api/client';
import {
  Badge, Btn, Field, inputCls, Panel, RefreshBtn, TableShell, tdCls, toast, useList, ViewHeader, fmtKsh,
} from './ui';

const CATEGORIES = ['bandwidth', 'power', 'rent', 'salaries', 'equipment', 'transport', 'other'] as const;

export default function ExpensesView() {
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    date: new Date().toISOString().slice(0, 10),
    category: 'other' as ApiExpense['category'],
    description: '',
    amount: '',
  });
  const { rows, count, error, reload } = useList(() => api.expenses.list());

  // Auto side: what the ISP paid WIFI.OS (Danamo) this month, pulled live from billing.
  const [platform, setPlatform] = useState<PlatformFees | null>(null);
  useEffect(() => {
    api.expenses.platformFees().then(setPlatform).catch(() => setPlatform(null));
  }, []);

  const monthTotal = useMemo(() => {
    if (!rows) return 0;
    const monthStart = new Date().toISOString().slice(0, 7);
    return rows.filter((e) => e.date.startsWith(monthStart)).reduce((a, e) => a + Number(e.amount), 0);
  }, [rows]);

  const platformTotal = platform ? Number(platform.total) : 0;
  const platformLines = (platform?.lines ?? []).filter((l) => Number(l.amount) > 0);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.expenses.create({ ...form, amount: form.amount });
      toast('success', 'Expense recorded.');
      setForm({ ...form, description: '', amount: '' });
      setShowForm(false);
      reload();
    } catch {
      toast('error', 'Failed to record expense.');
    }
  };

  return (
    <div className="space-y-5 text-[#141414]">
      <ViewHeader
        icon={<Wallet className="h-4.5 w-4.5" />}
        title="Expenses"
        subtitle="Track running costs per site so you know your real profit, not just revenue."
      >
        <Btn onClick={() => setShowForm(!showForm)}>
          <Plus className="h-3.5 w-3.5" /> Record Expense
        </Btn>
        <RefreshBtn onClick={reload} />
      </ViewHeader>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="bg-white border border-[#141414] p-3.5">
          <p className="text-[11px] font-mono uppercase text-[#141414]/60">Total This Month</p>
          <p className="text-xl font-black font-mono mt-1 text-[#B22222]">
            {fmtKsh(monthTotal + platformTotal)}
          </p>
          <p className="text-[10px] font-mono text-[#141414]/45 mt-0.5">
            incl. {fmtKsh(platformTotal)} WIFI.OS fees
          </p>
        </div>
        <div className="bg-white border border-[#141414] p-3.5">
          <p className="text-[11px] font-mono uppercase text-[#141414]/60">Recorded By You</p>
          <p className="text-xl font-black font-mono mt-1">{fmtKsh(monthTotal)}</p>
        </div>
        <div className="bg-white border border-[#141414] p-3.5">
          <p className="text-[11px] font-mono uppercase text-[#141414]/60">WIFI.OS Fees</p>
          <p className="text-xl font-black font-mono mt-1">{fmtKsh(platformTotal)}</p>
          <p className="text-[10px] font-mono text-[#141414]/45 mt-0.5">auto</p>
        </div>
        <div className="bg-white border border-[#141414] p-3.5">
          <p className="text-[11px] font-mono uppercase text-[#141414]/60">Entries</p>
          <p className="text-xl font-black font-mono mt-1">{count}</p>
        </div>
      </div>

      {/* Auto: what the ISP paid WIFI.OS this month — computed from billing, not editable. */}
      <Panel title="WIFI.OS platform fees · this month">
        <p className="text-xs text-[#141414]/60 -mt-1 mb-3 flex items-start gap-1.5">
          <Building2 className="h-3.5 w-3.5 mt-0.5 shrink-0" />
          <span>
            What you paid WIFI.OS this month — calculated automatically from your billing, so your
            real profit already accounts for it. You don't record these yourself.
          </span>
        </p>
        {platformLines.length === 0 ? (
          <p className="text-xs text-[#141414]/45">No platform fees charged yet this month.</p>
        ) : (
          <div className="border border-[#141414]/15">
            {platformLines.map((l) => (
              <div
                key={l.key}
                className="flex items-center justify-between border-b border-[#141414]/5 px-3 py-1.5 text-xs last:border-0"
              >
                <span>{l.label}</span>
                <span className="font-mono">{fmtKsh(Number(l.amount))}</span>
              </div>
            ))}
            <div className="flex items-center justify-between bg-[#f4f4f2] px-3 py-2 text-xs font-bold">
              <span>Total to WIFI.OS</span>
              <span className="font-mono">{fmtKsh(platformTotal)}</span>
            </div>
          </div>
        )}
      </Panel>

      {showForm && (
        <Panel title="Record expense">
          <form onSubmit={create} className="grid grid-cols-1 md:grid-cols-5 gap-3 items-end">
            <Field label="Date">
              <input type="date" required value={form.date} onChange={(e) => setForm({ ...form, date: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Category">
              <select value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value as ApiExpense['category'] })} className={inputCls}>
                {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
            </Field>
            <Field label="Description">
              <input required value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} className={inputCls} placeholder="e.g. Fuel for generator" />
            </Field>
            <Field label="Amount (KSh)">
              <input type="number" min="1" step="0.01" required value={form.amount} onChange={(e) => setForm({ ...form, amount: e.target.value })} className={inputCls} />
            </Field>
            <Btn type="submit" variant="green">Save</Btn>
          </form>
        </Panel>
      )}

      <TableShell
        headers={['Date', 'Category', 'Description', 'Site', 'Amount']}
        loading={rows === null}
        error={error}
        empty="No expenses recorded yet."
      >
        {(rows ?? []).map((e) => (
          <tr key={e.id} className="hover:bg-[#f0efec]/40 transition">
            <td className={`${tdCls} font-mono whitespace-nowrap`}>{e.date}</td>
            <td className={tdCls}><Badge color="gray">{e.category}</Badge></td>
            <td className={tdCls}>{e.description}</td>
            <td className={tdCls}>{e.router_name || '—'}</td>
            <td className={`${tdCls} font-mono font-bold text-right whitespace-nowrap`}>{fmtKsh(e.amount)}</td>
          </tr>
        ))}
      </TableShell>
    </div>
  );
}
