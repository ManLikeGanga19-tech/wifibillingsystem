import { useCallback, useEffect, useState, type ReactNode } from 'react';
import { AlertTriangle, Loader2, RefreshCw } from 'lucide-react';

/**
 * Primitives — matched to the ISP console's brutalist kit so the two consoles
 * read as one product: square borders, hairline #141414 rules, mono uppercase
 * labels, paper-white panels.
 */

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
    <section className={`bg-white border border-[#141414] ${className}`}>
      {(title || right) && (
        <header className="flex items-start justify-between gap-3 px-4 pt-4 pb-3">
          <div className="min-w-0">
            {title && (
              <h2 className="text-xs font-bold font-mono uppercase tracking-wide">{title}</h2>
            )}
            {subtitle && (
              <p className="text-[11px] font-mono text-[#141414]/60 mt-1 leading-relaxed">
                {subtitle}
              </p>
            )}
          </div>
          {right && <div className="shrink-0 flex gap-2">{right}</div>}
        </header>
      )}
      <div className={title ? 'px-4 pb-4' : 'p-4'}>{children}</div>
    </section>
  );
}

/* ---- stat tile ----------------------------------------------------------
   When the job is "one headline value", the right form is NOT a chart. */

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
    <div className="bg-white border border-[#141414] p-3.5">
      <p className="text-[10px] font-bold font-mono uppercase tracking-wider text-[#141414]/60">
        {label}
      </p>
      <p
        className={`${size === 'lg' ? 'text-2xl' : 'text-lg'} font-black font-mono mt-1.5 tnum`}
        style={accent ? { color: accent } : undefined}
      >
        {value}
      </p>
      {hint && (
        <p className="text-[10px] font-mono text-[#141414]/50 mt-1.5 leading-snug">{hint}</p>
      )}
    </div>
  );
}

/* ---- badge --------------------------------------------------------------- */

const BADGE: Record<string, string> = {
  green: 'text-[#228B22] border-[#228B22]/40 bg-[#228B22]/5',
  red: 'text-[#B22222] border-[#B22222]/40 bg-[#B22222]/5',
  amber: 'text-[#B26B00] border-[#B26B00]/40 bg-[#B26B00]/5',
  gray: 'text-[#141414]/70 border-[#141414]/30 bg-[#141414]/5',
  blue: 'text-[#2563EB] border-[#2563EB]/40 bg-[#2563EB]/5',
};

export type Tone = keyof typeof BADGE;

export function Badge({ tone = 'gray', children }: { tone?: Tone; children: ReactNode }) {
  return (
    <span
      className={`inline-block px-1.5 py-0.5 border text-[10px] font-bold font-mono uppercase whitespace-nowrap ${BADGE[tone]}`}
    >
      {children}
    </span>
  );
}

export const STATUS_TONE: Record<string, Tone> = {
  active: 'green',
  pending: 'amber',
  suspended: 'red',
  paid: 'green',
  requested: 'amber',
  rejected: 'red',
  success: 'green',
  failed: 'red',
  matched: 'green',
  unmatched: 'red',
  online: 'green',
  offline: 'red',
};

/* ---- buttons ------------------------------------------------------------- */

export function Btn({
  children,
  onClick,
  variant = 'outline',
  disabled,
  title,
  type = 'button',
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: 'dark' | 'outline' | 'green' | 'danger';
  disabled?: boolean;
  title?: string;
  type?: 'button' | 'submit';
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
      className={`inline-flex items-center gap-1.5 px-3 py-2 text-[11px] font-bold font-mono uppercase border transition cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed ${styles[variant]}`}
    >
      {children}
    </button>
  );
}

export function RefreshBtn({ onClick }: { onClick: () => void }) {
  return (
    <Btn variant="outline" onClick={onClick} title="Refresh">
      <RefreshCw className="h-3.5 w-3.5" /> Refresh
    </Btn>
  );
}

/* ---- view header --------------------------------------------------------- */

export function ViewHeader({
  icon,
  title,
  subtitle,
  children,
}: {
  icon: ReactNode;
  title: string;
  subtitle: string;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="flex items-start gap-2.5">
        <div className="bg-[#141414] text-[#E4E3E0] p-1.5 mt-0.5">{icon}</div>
        <div>
          <h1 className="font-bold font-mono uppercase tracking-tight">{title}</h1>
          <p className="text-xs font-mono text-[#141414]/70 mt-0.5">{subtitle}</p>
        </div>
      </div>
      {children && <div className="flex items-center gap-2 self-start">{children}</div>}
    </div>
  );
}

/* ---- table --------------------------------------------------------------- */

export function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse min-w-[680px]">
        <thead>
          <tr className="border-b border-[#141414]">
            {head.map((h) => (
              <th
                key={h}
                className="text-left text-[10px] font-bold font-mono uppercase tracking-wider text-[#141414]/60 py-2 px-3 whitespace-nowrap"
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

export const td = 'py-2.5 px-3 text-xs border-b border-[#141414]/10 align-middle';

/* ---- states -------------------------------------------------------------- */

export function Spinner() {
  return (
    <div className="flex justify-center py-20">
      <Loader2 className="h-7 w-7 animate-spin text-[#141414]/40" />
    </div>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="bg-white border border-[#141414] p-8 text-center space-y-3">
      <AlertTriangle className="h-7 w-7 mx-auto text-[#B22222]" />
      <p className="text-xs font-mono">{message}</p>
      <Btn onClick={onRetry}>Retry</Btn>
    </div>
  );
}

export function Empty({ message }: { message: string }) {
  return <p className="text-center text-xs font-mono text-[#141414]/50 py-10">{message}</p>;
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
          className={`border px-3 py-2 text-[11px] font-mono font-bold uppercase max-w-xs ${BADGE[t.tone]}`}
        >
          {t.msg}
        </div>
      ))}
    </div>
  );
}
