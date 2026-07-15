import { useEffect, useState } from 'react';
import { ChevronDown, ChevronRight, FileText } from 'lucide-react';
import { api, PlatformInvoice } from '../../api/client';
import { Panel, toast } from '../ui';

/**
 * Monthly statements — the ISP's formal record of every fee WIFI.OS charged them. A
 * statement, not a bill to pay again: the fees were charged as they happened, and paying
 * is the same top-up. Each line shows what was DUE; the aggregator commission we already
 * took is shown too, marked so, because nothing goes unnoticed.
 */
export default function Statements() {
  const [invoices, setInvoices] = useState<PlatformInvoice[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    api.account
      .invoices()
      .then((r) => setInvoices(r.invoices))
      .catch(() => toast('error', 'Could not load your statements.'));
  }, []);

  if (!invoices) return null;

  return (
    <Panel title="Monthly statements">
      {invoices.length === 0 ? (
        <p className="flex items-center gap-2 py-2 text-xs text-[#141414]/50">
          <FileText className="h-3.5 w-3.5" /> No statements yet — your first arrives at the
          start of next month.
        </p>
      ) : (
        <div className="divide-y divide-[#141414]/10">
          {invoices.map((inv) => {
            const isOpen = open === inv.period;
            return (
              <div key={inv.period}>
                <button
                  onClick={() => setOpen(isOpen ? null : inv.period)}
                  className="flex w-full items-center gap-2 py-2.5 text-left"
                >
                  {isOpen ? (
                    <ChevronDown className="h-3.5 w-3.5 shrink-0" />
                  ) : (
                    <ChevronRight className="h-3.5 w-3.5 shrink-0" />
                  )}
                  <span className="font-mono text-sm font-bold">{inv.period}</span>
                  <span className="flex-1" />
                  <span className="font-mono text-sm">KSh {Number(inv.total).toLocaleString()}</span>
                  <span
                    className={`shrink-0 border px-1.5 py-0.5 font-mono text-[10px] uppercase ${
                      inv.status === 'paid'
                        ? 'border-[#228B22]/40 text-[#228B22]'
                        : 'border-[#B22222]/40 text-[#B22222]'
                    }`}
                  >
                    {inv.status}
                  </span>
                </button>

                {isOpen && (
                  <div className="pb-3 pl-5.5 pr-1">
                    {inv.lines
                      .filter((l) => Number(l.amount) > 0)
                      .map((l) => (
                        <div
                          key={l.label}
                          className="flex items-baseline justify-between gap-3 py-1 text-xs"
                        >
                          <span className={l.due ? 'text-[#141414]/70' : 'text-[#141414]/40'}>
                            {l.label}
                          </span>
                          <span
                            className={`font-mono ${l.due ? '' : 'text-[#141414]/40 line-through'}`}
                          >
                            KSh {Number(l.amount).toLocaleString()}
                          </span>
                        </div>
                      ))}
                    <div className="mt-1 flex items-baseline justify-between border-t border-[#141414]/10 pt-1.5 text-xs font-bold">
                      <span>Total charged</span>
                      <span className="font-mono">KSh {Number(inv.total).toLocaleString()}</span>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </Panel>
  );
}
