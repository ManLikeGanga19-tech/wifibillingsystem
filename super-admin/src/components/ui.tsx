import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { AlertTriangle, Loader2, RefreshCw } from 'lucide-react';

/* ---- panels ------------------------------------------------------------- */

export function Panel({
  title,
  subtitle,
  right,
  children,
  className = '',
}: {
  title?: string;
  subtitle?: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel p-4 sm:p-5 ${className}`}>
      {(title || right) && (
        <header className="flex items-start justify-between gap-3 mb-4">
          <div className="min-w-0">
            {title && (
              <h2 className="text-[13px] font-semibold tracking-wide uppercase text-white">
                {title}
              </h2>
            )}
            {subtitle && (
              <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
                {subtitle}
              </p>
            )}
          </div>
          {right && <div className="shrink-0">{right}</div>}
        </header>
      )}
      {children}
    </section>
  );
}

/* ---- stat tile ----------------------------------------------------------
   A bare number with a label. Per the form heuristic: when the job is "one
   headline value", the right form is NOT a chart. */

export function Stat({
  label,
  value,
  hint,
  accent,
  size = 'md',
}: {
  label: string;
  value: string;
  hint?: string;
  accent?: string;
  size?: 'md' | 'lg';
}) {
  return (
    <div className="panel-flat p-4">
      <p className="text-[11px] uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
        {label}
      </p>
      <p
        className={`${size === 'lg' ? 'text-3xl' : 'text-xl'} font-semibold mt-1.5`}
        style={{ color: accent ?? 'var(--text-primary)' }}
      >
        {value}
      </p>
      {hint && (
        <p className="text-[11px] mt-1.5 leading-snug" style={{ color: 'var(--text-muted)' }}>
          {hint}
        </p>
      )}
    </div>
  );
}

/* ---- badge --------------------------------------------------------------- */

type Tone = 'good' | 'warning' | 'critical' | 'neutral' | 'accent';

const TONE: Record<Tone, { bg: string; fg: string }> = {
  good: { bg: 'rgba(12,163,12,0.14)', fg: '#3ecf3e' },
  warning: { bg: 'rgba(250,178,25,0.14)', fg: '#fab219' },
  critical: { bg: 'rgba(208,59,59,0.16)', fg: '#f07373' },
  neutral: { bg: 'rgba(255,255,255,0.06)', fg: 'var(--text-secondary)' },
  accent: { bg: 'var(--accent-dim)', fg: 'var(--accent)' },
};

export function Badge({ tone = 'neutral', children }: { tone?: Tone; children: ReactNode }) {
  const t = TONE[tone];
  return (
    <span
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium whitespace-nowrap"
      style={{ background: t.bg, color: t.fg }}
    >
      {children}
    </span>
  );
}

export const STATUS_TONE: Record<string, Tone> = {
  active: 'good',
  pending: 'warning',
  suspended: 'critical',
  paid: 'good',
  requested: 'warning',
  rejected: 'critical',
  success: 'good',
  failed: 'critical',
  matched: 'good',
  unmatched: 'critical',
  online: 'good',
  offline: 'critical',
};

/* ---- buttons ------------------------------------------------------------- */

export function Btn({
  children,
  onClick,
  variant = 'ghost',
  disabled,
  title,
  type = 'button',
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: 'primary' | 'ghost' | 'danger';
  disabled?: boolean;
  title?: string;
  type?: 'button' | 'submit';
}) {
  const styles: Record<string, string> = {
    primary: 'bg-[var(--accent)] text-[#04141a] hover:opacity-90 font-semibold',
    ghost:
      'bg-[var(--surface-3)] text-[var(--text-secondary)] hover:text-white border border-[var(--hairline)]',
    danger: 'bg-[rgba(208,59,59,0.16)] text-[#f07373] hover:bg-[rgba(208,59,59,0.26)]',
  };
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs transition cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed ${styles[variant]}`}
    >
      {children}
    </button>
  );
}

export function RefreshBtn({ onClick }: { onClick: () => void }) {
  return (
    <Btn onClick={onClick} title="Refresh">
      <RefreshCw className="h-3.5 w-3.5" /> Refresh
    </Btn>
  );
}

/* ---- table --------------------------------------------------------------- */

export function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto -mx-4 sm:-mx-5 px-4 sm:px-5">
      <table className="w-full text-xs border-collapse min-w-[640px]">
        <thead>
          <tr>
            {head.map((h) => (
              <th
                key={h}
                className="text-left font-medium uppercase tracking-wider text-[10px] pb-2 border-b whitespace-nowrap"
                style={{ color: 'var(--text-muted)', borderColor: 'var(--hairline)' }}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export const td = 'py-2.5 border-b align-middle';
export const tdStyle = { borderColor: 'var(--hairline)' };

/* ---- states -------------------------------------------------------------- */

export function Spinner() {
  return (
    <div className="flex justify-center py-20">
      <Loader2 className="h-7 w-7 animate-spin" style={{ color: 'var(--text-muted)' }} />
    </div>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="panel p-8 text-center space-y-3">
      <AlertTriangle className="h-7 w-7 mx-auto" style={{ color: 'var(--critical)' }} />
      <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
        {message}
      </p>
      <Btn onClick={onRetry}>Retry</Btn>
    </div>
  );
}

export function Empty({ message }: { message: string }) {
  return (
    <p className="text-center text-xs py-10" style={{ color: 'var(--text-muted)' }}>
      {message}
    </p>
  );
}

/* ---- data-loading hook --------------------------------------------------- */

export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const load = useCallback(async () => {
    try {
      setData(await fn());
      setError('');
    } catch {
      setError('Could not load this data.');
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    load();
  }, [load]);

  return { data, error, reload: load };
}

/* ---- toast --------------------------------------------------------------- */

type Toast = { id: number; tone: Tone; msg: string };
let push: ((t: Toast) => void) | null = null;
let seq = 0;

export function toast(tone: Tone, msg: string) {
  push?.({ id: ++seq, tone, msg });
}

export function ToastHost() {
  const [items, setItems] = useState<Toast[]>([]);
  useEffect(() => {
    push = (t) => {
      setItems((cur) => [...cur, t]);
      setTimeout(() => setItems((cur) => cur.filter((x) => x.id !== t.id)), 4000);
    };
    return () => {
      push = null;
    };
  }, []);
  return (
    <div className="fixed bottom-4 right-4 z-50 space-y-2">
      {items.map((t) => (
        <div
          key={t.id}
          className="panel px-3.5 py-2.5 text-xs shadow-lg max-w-xs"
          style={{ color: TONE[t.tone].fg }}
        >
          {t.msg}
        </div>
      ))}
    </div>
  );
}
