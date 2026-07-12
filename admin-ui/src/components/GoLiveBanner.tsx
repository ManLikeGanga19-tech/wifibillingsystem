import { CheckCircle2, Circle, Rocket } from 'lucide-react';
import { MeOperator } from '../api/client';
import SettlementSetup from './SettlementSetup';

/**
 * The honest explanation of the money gate.
 *
 * A pending ISP can build everything — routers, plans, branding, their whole
 * client list — but cannot take a shilling until we've verified who they are.
 * Without this banner every blocked action just looks like a broken product, so
 * this is not decoration: it is the difference between "deliberate" and "broken".
 *
 * It also has to sell the custody model, which is the hardest thing we ever ask an
 * ISP to accept: your customers pay US, not you. Say why, plainly, and say what
 * they get for it.
 */
export default function GoLiveBanner({
  operator,
  onWentLive,
}: {
  operator: MeOperator;
  onWentLive: () => void;
}) {
  if (operator.can_transact) return null;

  const blockers = operator.go_live_blockers ?? [];
  const suspended = operator.status === 'suspended';

  return (
    <div
      className={`border ${
        suspended ? 'border-[#B22222] bg-[#B22222]/5' : 'border-[#141414] bg-white'
      }`}
    >
      <div className="p-4 sm:p-5">
        <div className="flex items-start gap-3">
          <div
            className={`p-1.5 shrink-0 ${
              suspended ? 'bg-[#B22222] text-white' : 'bg-[#141414] text-[#E4E3E0]'
            }`}
          >
            <Rocket className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <h2 className="text-sm font-bold font-mono uppercase tracking-tight">
              {suspended ? 'Account suspended' : "You're set up — payments aren't on yet"}
            </h2>
            <p className="text-xs font-mono text-[#141414]/70 mt-1 leading-relaxed">
              {suspended ? (
                'Contact the platform administrator.'
              ) : (
                <>
                  Configure everything now — routers, plans, branding, clients. You just
                  can&apos;t <b>collect payments</b> or <b>withdraw</b> until we&apos;ve verified
                  your business.
                </>
              )}
            </p>
          </div>
        </div>

        {!suspended && blockers.length > 0 && (
          <ol className="mt-4 space-y-4 border-t border-[#141414]/10 pt-4">
            {blockers.map((b, i) => (
              <li key={b.key} className="flex items-start gap-2.5">
                {b.done ? (
                  <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5 text-[#228B22]" />
                ) : b.actionable ? (
                  <Circle className="h-4 w-4 shrink-0 mt-0.5 text-[#B26B00]" />
                ) : (
                  <Circle className="h-4 w-4 shrink-0 mt-0.5 text-[#141414]/20" />
                )}
                <div className="min-w-0 flex-1">
                  <p
                    className={`text-xs font-bold font-mono uppercase ${
                      b.done ? 'text-[#141414]/40 line-through' : ''
                    }`}
                  >
                    {i + 1}. {b.label}
                    {b.actionable && !b.done && (
                      <span className="ml-2 text-[10px] text-[#B26B00] no-underline">
                        ← your move
                      </span>
                    )}
                  </p>
                  {!b.done && (
                    <p className="text-[11px] font-mono text-[#141414]/60 mt-0.5 leading-relaxed">
                      {b.detail}
                    </p>
                  )}

                  {/* The form lives INSIDE the step it satisfies. Explaining a
                      blocker and then making someone hunt for where to fix it is
                      how a checklist becomes a chore. */}
                  {b.key === 'settlement_account' && (
                    <div className="mt-3 border border-[#141414]/15 bg-[#f0efec] p-3">
                      <SettlementSetup onVerified={onWentLive} />
                    </div>
                  )}
                </div>
              </li>
            ))}
          </ol>
        )}

        {!suspended && (
          // The custody model, said out loud. An ISP WILL ask "why does my
          // customers' money go to you?" — better they read the answer here than
          // invent a worse one.
          <p className="text-[11px] font-mono text-[#141414]/50 mt-4 border-t border-[#141414]/10 pt-3 leading-relaxed">
            <b>Why we hold the money:</b> one paybill means one M-Pesa integration and one
            reconciliation — and <b>we absorb every transaction cost</b>, which you would
            otherwise pay Safaricom yourself. Your customers pay WIFI.OS; we attribute every
            shilling to you in a ledger you can see, and settle it to your own account on
            request. Your first month is free.
          </p>
        )}
      </div>
    </div>
  );
}
