import { AlertTriangle, Lock } from 'lucide-react';
import { BillingState } from '../api/client';

/**
 * The past-due banner — what makes the auto-suspension ladder VISIBLE. Without it, a
 * refused sale or a read-only console just looks broken; with it, the ISP knows exactly
 * what they owe and that one payment fixes it.
 *
 * Pinned above every screen while they owe. It never appears for an ISP in good standing
 * (level `current`), so it costs a healthy tenant nothing.
 */
export default function PastDueBanner({
  billing,
  onPay,
}: {
  billing: BillingState;
  onPay: () => void;
}) {
  if (billing.level === 'current') return null;

  const owed = Number(billing.owed).toLocaleString();

  // Three voices for three rungs: a nudge, a "sales are off", a "console is locked".
  const config = {
    warned: {
      icon: <AlertTriangle className="h-4 w-4" />,
      tone: 'border-[#141414]/25 bg-[#f4f3f0] text-[#141414]',
      title: `You owe KSh ${owed}`,
      body: `Top up before new sales are paused (at KSh ${Number(billing.restrict_at).toLocaleString()}).`,
    },
    restricted: {
      icon: <AlertTriangle className="h-4 w-4" />,
      tone: 'border-[#B22222]/50 bg-[#B22222]/5 text-[#B22222]',
      title: `New sales are paused — you owe KSh ${owed}`,
      body: 'Existing customers are unaffected. Pay your balance to start selling again.',
    },
    locked: {
      icon: <Lock className="h-4 w-4" />,
      tone: 'border-[#B22222] bg-[#B22222]/10 text-[#B22222]',
      title: `Your console is read-only — you owe KSh ${owed}`,
      body: 'You can still view everything and pay. Settle up to restore full access.',
    },
  }[billing.level];

  return (
    <div className={`flex flex-wrap items-center gap-3 border p-3.5 ${config.tone}`}>
      <span className="shrink-0">{config.icon}</span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-bold">{config.title}</p>
        <p className="text-xs leading-relaxed opacity-80">{config.body}</p>
      </div>
      <button
        onClick={onPay}
        className="shrink-0 bg-[#141414] px-4 py-2 font-mono text-xs font-bold uppercase text-[#E4E3E0] hover:opacity-90"
      >
        Pay now
      </button>
    </div>
  );
}
