import { useState } from 'react';
import { Link2, AlertTriangle } from 'lucide-react';
import { api, dt, ksh, type UnmatchedPayment, type UnmatchedSuggestion } from '../api/client';
import { Btn, Empty, ErrorBox, Panel, RefreshBtn, Spinner, Table, td, toast, useLoad } from '../components/ui';

/**
 * The unmatched-payments queue. A PPPoE customer paid by paybill and mistyped their
 * account number, so the money landed attributed to nobody. Safaricom already took it,
 * so we can't refuse it — someone has to reunite it with its client, or the customer
 * paid and stayed cut off.
 *
 * The suggestion engine does the detective work (payer's phone, a near-miss account
 * number); a human confirms and clicks. Resolving credits the client and restores them.
 */
export default function UnmatchedPanel() {
  const { data, error, reload } = useLoad(() => api.unmatched.list(), []);
  const [busy, setBusy] = useState<number | null>(null);

  const resolve = async (p: UnmatchedPayment, s: UnmatchedSuggestion) => {
    if (
      !window.confirm(
        `Apply ${ksh(p.amount)} to ${s.account_number} (${s.full_name}, ${s.operator})?\n\n` +
          `They typed "${p.typed_account}". This credits the client and restores service.`
      )
    )
      return;
    setBusy(p.id);
    try {
      const r = await api.unmatched.resolve(p.id, s.client_id);
      toast('green', r.detail);
      reload();
    } catch {
      toast('red', 'Could not resolve that payment.');
    } finally {
      setBusy(null);
    }
  };

  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return <Spinner />;

  return (
    <Panel
      title="Unmatched payments"
      subtitle="Money that landed on a mistyped account number. Match it to the right client."
      right={<RefreshBtn onClick={reload} />}
    >
      {data.results.length === 0 ? (
        <Empty message="Nothing unmatched — every shilling is home." />
      ) : (
        <Table head={['Received', 'They typed', 'Amount', 'Paid from', 'Likely owner']}>
          {data.results.map((p) => (
            <tr key={p.id} className="align-top">
              <td className={`${td} whitespace-nowrap tnum`}>{dt(p.received_at)}</td>
              <td className={td}>
                <span className="font-mono font-bold">{p.typed_account || '—'}</span>
              </td>
              <td className={`${td} tnum font-bold`}>{ksh(p.amount)}</td>
              <td className={`${td} whitespace-nowrap`}>
                <div className="font-mono text-xs">{p.paid_from || '—'}</div>
                <div className="text-[11px]" style={{ color: 'var(--text-muted)' }}>{p.payer_name}</div>
              </td>
              <td className={td}>
                {p.suggestions.length === 0 ? (
                  <span className="inline-flex items-center gap-1 text-[11px]" style={{ color: 'var(--text-muted)' }}>
                    <AlertTriangle className="h-3.5 w-3.5" /> No confident match — check by hand
                  </span>
                ) : (
                  <div className="flex flex-col gap-1.5">
                    {p.suggestions.map((s) => (
                      <div key={s.client_id} className="flex items-center gap-2">
                        <Btn onClick={() => resolve(p, s)} disabled={busy === p.id}>
                          <Link2 className="h-3.5 w-3.5" />
                          {s.account_number}
                        </Btn>
                        <div className="text-[11px] leading-tight" style={{ color: 'var(--text-secondary)' }}>
                          <span className="font-bold">{s.full_name}</span> · {s.operator}
                          <br />
                          <span style={{ color: 'var(--text-muted)' }}>
                            {Math.round(s.confidence * 100)}% · {s.reason}
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </td>
            </tr>
          ))}
        </Table>
      )}
    </Panel>
  );
}
