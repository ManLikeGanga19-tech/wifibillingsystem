/** Shared primitives for the live admin views — one place for the house style. */

import React, { useCallback, useEffect, useState } from 'react';
import { Loader2, AlertTriangle, RefreshCw, CheckCircle2, XCircle, Info } from 'lucide-react';

// ---- toast ------------------------------------------------------------

type ToastKind = 'success' | 'error' | 'info' | 'warning';
interface Toast {
  id: number;
  kind: ToastKind;
  message: string;
}

let toastListener: ((t: Toast) => void) | null = null;
let toastId = 0;

export function toast(kind: ToastKind, message: string) {
  toastListener?.({ id: ++toastId, kind, message });
}

export function ToastHost() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  useEffect(() => {
    toastListener = (t) => {
      setToasts((prev) => [...prev, t]);
      window.setTimeout(() => setToasts((prev) => prev.filter((x) => x.id !== t.id)), 4500);
    };
    return () => {
      toastListener = null;
    };
  }, []);
  const ICON = {
    success: <CheckCircle2 className="h-4 w-4 text-[#228B22]" />,
    error: <XCircle className="h-4 w-4 text-[#B22222]" />,
    warning: <AlertTriangle className="h-4 w-4 text-[#B26B00]" />,
    info: <Info className="h-4 w-4 text-[#141414]/60" />,
  };
  return (
    <div className="fixed bottom-10 right-4 z-50 space-y-2 max-w-sm">
      {toasts.map((t) => (
        <div key={t.id} className="bg-white border border-[#141414] shadow-lg px-3 py-2.5 flex items-start gap-2 text-xs font-mono">
          {ICON[t.kind]}
          <span className="leading-snug">{t.message}</span>
        </div>
      ))}
    </div>
  );
}

// ---- data fetching hook -------------------------------------------------

export function useList<T>(fetcher: () => Promise<{ results: T[]; count: number }>, deps: unknown[] = []) {
  const [rows, setRows] = useState<T[] | null>(null);
  const [count, setCount] = useState(0);
  const [error, setError] = useState('');
  const load = useCallback(async () => {
    try {
      const r = await fetcher();
      setRows(r.results);
      setCount(r.count);
      setError('');
    } catch {
      setError('Could not load data — check the API connection.');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  useEffect(() => {
    setRows(null);
    load();
  }, [load]);
  return { rows, count, error, reload: load };
}

// ---- layout pieces --------------------------------------------------------

export function ViewHeader({
  icon,
  title,
  subtitle,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
      <div>
        <h2 className="text-sm font-serif italic font-bold flex items-center gap-2 uppercase">
          {icon}
          <span>{title}</span>
        </h2>
        <p className="text-xs font-mono text-[#141414]/70 mt-0.5">{subtitle}</p>
      </div>
      {children && <div className="flex items-center gap-2 self-start">{children}</div>}
    </div>
  );
}

export function Btn({
  children,
  onClick,
  variant = 'dark',
  type = 'button',
  disabled,
  title,
}: {
  children: React.ReactNode;
  onClick?: () => void;
  variant?: 'dark' | 'outline' | 'green' | 'danger';
  type?: 'button' | 'submit';
  disabled?: boolean;
  title?: string;
}) {
  const styles = {
    dark: 'bg-[#141414] text-[#E4E3E0] border-[#141414] hover:bg-[#228B22]',
    outline: 'bg-white text-[#141414] border-[#141414] hover:bg-[#141414] hover:text-white',
    green: 'bg-[#228B22] text-white border-[#228B22] hover:opacity-85',
    danger: 'bg-white text-[#B22222] border-[#B22222]/50 hover:bg-[#B22222] hover:text-white',
  };
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`inline-flex items-center gap-1.5 px-3 py-2 text-xs font-bold font-mono uppercase border transition cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed ${styles[variant]}`}
    >
      {children}
    </button>
  );
}

export function RefreshBtn({ onClick, spinning }: { onClick: () => void; spinning?: boolean }) {
  return (
    <Btn variant="outline" onClick={onClick} title="Refresh">
      <RefreshCw className={`h-3.5 w-3.5 ${spinning ? 'animate-spin' : ''}`} />
      Refresh
    </Btn>
  );
}

const BADGE_STYLES: Record<string, string> = {
  green: 'text-[#228B22] border-[#228B22]/40 bg-[#228B22]/5',
  red: 'text-[#B22222] border-[#B22222]/40 bg-[#B22222]/5',
  amber: 'text-[#B26B00] border-[#B26B00]/40 bg-[#B26B00]/5',
  gray: 'text-[#141414]/70 border-[#141414]/30 bg-[#141414]/5',
  blue: 'text-[#2563EB] border-[#2563EB]/40 bg-[#2563EB]/5',
};

export function Badge({ color, children }: { color: keyof typeof BADGE_STYLES; children: React.ReactNode }) {
  return (
    <span className={`inline-block px-1.5 py-0.5 border text-[11px] font-bold font-mono uppercase whitespace-nowrap ${BADGE_STYLES[color]}`}>
      {children}
    </span>
  );
}

export function Field({ label, children, className = '' }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={`space-y-1 ${className}`}>
      <label className="text-xs font-bold font-mono uppercase text-[#141414]/60 block">{label}</label>
      {children}
    </div>
  );
}

export const inputCls =
  'w-full bg-white border border-[#141414] p-2 text-xs rounded-none outline-none focus:bg-[#f8f8f6]';

export function Panel({ title, children, className = '' }: { title?: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-white border border-[#141414] ${className}`}>
      {title && <h3 className="text-xs font-bold font-mono uppercase tracking-wide px-4 pt-4">{title}</h3>}
      <div className="p-4">{children}</div>
    </div>
  );
}

export function TableShell({
  headers,
  loading,
  error,
  empty,
  children,
}: {
  headers: string[];
  loading: boolean;
  error: string;
  empty: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-white border border-[#141414] overflow-x-auto">
      {error && (
        <p className="p-6 text-center text-xs font-mono text-[#B22222] flex items-center justify-center gap-2">
          <AlertTriangle className="h-4 w-4" /> {error}
        </p>
      )}
      {!error && loading && (
        <div className="flex justify-center py-14">
          <Loader2 className="h-6 w-6 animate-spin text-[#141414]/40" />
        </div>
      )}
      {!error && !loading && React.Children.count(children) === 0 && (
        <p className="p-8 text-center text-xs font-mono text-[#141414]/50">{empty}</p>
      )}
      {!error && !loading && React.Children.count(children) > 0 && (
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-[#141414] font-mono text-[11px] uppercase text-[#141414]/60">
              {headers.map((h) => (
                <th key={h} className="py-2.5 px-3 whitespace-nowrap">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-[#141414]/10">{children}</tbody>
        </table>
      )}
    </div>
  );
}

export const tdCls = 'py-2.5 px-3 text-xs';

export function FilterChips<T extends string>({
  options,
  value,
  onChange,
  right,
}: {
  options: readonly T[];
  value: T;
  onChange: (v: T) => void;
  right?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap gap-1.5 items-center">
      {options.map((f) => (
        <button
          key={f}
          onClick={() => onChange(f)}
          className={`px-3 py-1.5 border text-xs font-bold font-mono uppercase transition cursor-pointer ${
            value === f ? 'bg-[#141414] text-[#E4E3E0] border-[#141414]' : 'bg-white border-[#141414]/40 hover:border-[#141414]'
          }`}
        >
          {f.replace('_', ' ')}
        </button>
      ))}
      {right && <span className="ml-auto">{right}</span>}
    </div>
  );
}

export function fmtDateTime(iso: string | null): string {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-KE', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
}

export function fmtKsh(v: string | number | null): string {
  if (v === null) return '—';
  return `KSh ${Number(v).toLocaleString('en-KE', { maximumFractionDigits: 0 })}`;
}
