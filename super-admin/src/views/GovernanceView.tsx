import { useState } from 'react';
import { Eye, ShieldCheck } from 'lucide-react';
import { api, dt, type AuditRow, type Grant } from '../api/client';
import {
  Badge,
  Btn,
  Empty,
  ErrorBox,
  Panel,
  RefreshBtn,
  Spinner,
  Table,
  td,
  toast,
  useLoad,
} from '../components/ui';

/**
 * Governance.
 *
 * The audit log was always written — every approval, payout, provision and
 * callback — and was never once readable. This is that trail, plus the record of
 * every time platform staff walked into an ISP's console.
 *
 * Neither list has a write path. The trail cannot be edited from here, by design.
 */
export default function GovernanceView() {
  const [tab, setTab] = useState<'audit' | 'access'>('audit');
  return (
    <div className="space-y-5">
      <div className="flex items-center gap-1.5">
        <Btn variant={tab === 'audit' ? 'dark' : 'outline'} onClick={() => setTab('audit')}>
          <ShieldCheck className="h-3.5 w-3.5" /> Audit trail
        </Btn>
        <Btn variant={tab === 'access' ? 'dark' : 'outline'} onClick={() => setTab('access')}>
          <Eye className="h-3.5 w-3.5" /> ISP console access
        </Btn>
      </div>
      {tab === 'audit' ? <AuditTrail /> : <AccessHistory />}
    </div>
  );
}

/* ---- audit trail --------------------------------------------------------- */

function AuditTrail() {
  const [action, setAction] = useState('');
  const [tenant, setTenant] = useState('');
  const list = useLoad(() => api.audit.list({ action, tenant }), [action, tenant]);
  const actions = useLoad(() => api.audit.actions(), []);

  if (list.error) return <ErrorBox message={list.error} onRetry={list.reload} />;

  return (
    <Panel
      title="Audit trail"
      subtitle="Every state change in the system, across every ISP. Append-only — there is no write path."
      right={<RefreshBtn onClick={list.reload} />}
    >
      <div className="flex flex-wrap gap-2 mb-4">
        <select
          value={action}
          onChange={(e) => setAction(e.target.value)}
          className="max-w-[15rem]"
        >
          <option value="">All actions</option>
          {(actions.data ?? []).map((a) => (
            <option key={a} value={a}>
              {a}
            </option>
          ))}
        </select>
        <input
          placeholder="Filter by ISP slug…"
          value={tenant}
          onChange={(e) => setTenant(e.target.value)}
          className="max-w-[13rem]"
        />
      </div>

      {!list.data ? (
        <Spinner />
      ) : list.data.results.length === 0 ? (
        <Empty message="Nothing recorded for this filter." />
      ) : (
        <Table head={['When', 'Action', 'Actor', 'ISP', 'Target', 'Detail', 'IP']}>
          {list.data.results.map((r) => (
            <AuditLine key={r.id} r={r} />
          ))}
        </Table>
      )}
    </Panel>
  );
}

/** Actions that move money or change access get flagged — those are the rows an
 * auditor actually cares about. */
const SENSITIVE = /payout|impersonation|setup_fee|approved|suspended|withdraw/i;

function AuditLine({ r }: { r: AuditRow }) {
  const detail = Object.entries(r.metadata ?? {})
    .map(([k, v]) => `${k}=${String(v)}`)
    .join(' · ');
  return (
    <tr className="hover:bg-[#f0efec] transition">
      <td
        className={`${td} whitespace-nowrap tnum`}
        style={{ color: 'var(--text-muted)' }}
      >
        {dt(r.created_at)}
      </td>
      <td className={td}>
        <Badge tone={SENSITIVE.test(r.action) ? 'amber' : 'gray'}>{r.action}</Badge>
      </td>
      <td className={td}>
        {r.actor_name || <span style={{ color: 'var(--text-muted)' }}>system</span>}
      </td>
      <td className={td} style={{ color: 'var(--text-secondary)' }}>
        {r.operator_slug || '—'}
      </td>
      <td className={td} style={{ color: 'var(--text-muted)' }}>
        {r.target_type ? `${r.target_type}#${r.target_id}` : '—'}
      </td>
      <td
        className={`${td} max-w-[22rem] truncate`}
        style={{ color: 'var(--text-secondary)' }}
        title={detail}
      >
        {detail || '—'}
      </td>
      <td className={`${td} tnum`} style={{ color: 'var(--text-muted)' }}>
        {r.ip_address ?? '—'}
      </td>
    </tr>
  );
}

/* ---- impersonation history ----------------------------------------------- */

function AccessHistory() {
  const { data, error, reload } = useLoad(() => api.impersonation.history(), []);

  const endAll = async () => {
    try {
      const { ended } = await api.impersonation.end();
      toast('green', ended ? `Closed ${ended} open session(s).` : 'No open sessions.');
      reload();
    } catch {
      toast('red', 'Could not close sessions.');
    }
  };

  if (error) return <ErrorBox message={error} onRetry={reload} />;

  const rows = data?.results ?? [];
  const liveCount = rows.filter((r) => r.is_live).length;

  return (
    <Panel
      title="ISP console access"
      subtitle="Every time platform staff entered an ISP's console — with the reason they gave. Access requires a grant; a header alone is refused."
      right={
        <div className="flex gap-2">
          {liveCount > 0 && (
            <Btn variant="danger" onClick={endAll}>
              End my {liveCount} open session{liveCount > 1 ? 's' : ''}
            </Btn>
          )}
          <RefreshBtn onClick={reload} />
        </div>
      }
    >
      {!data ? (
        <Spinner />
      ) : rows.length === 0 ? (
        <Empty message="No one has entered an ISP console yet." />
      ) : (
        <Table head={['Started', 'Staff', 'ISP', 'Reason', 'Expires', 'Ended', 'State']}>
          {rows.map((g) => (
            <GrantLine key={g.id} g={g} />
          ))}
        </Table>
      )}
    </Panel>
  );
}

function GrantLine({ g }: { g: Grant }) {
  return (
    <tr className="hover:bg-[#f0efec] transition">
      <td
        className={`${td} whitespace-nowrap tnum`}
        style={{ color: 'var(--text-muted)' }}
      >
        {dt(g.started_at)}
      </td>
      <td className={td}>
        {g.actor_name}
      </td>
      <td className={td} style={{ color: 'var(--text-secondary)' }}>
        {g.operator_name}
        <span className="block text-[11px]" style={{ color: 'var(--text-muted)' }}>
          {g.operator_slug}
        </span>
      </td>
      <td className={`${td} max-w-[20rem]`} title={g.reason}>
        {g.reason}
      </td>
      <td
        className={`${td} whitespace-nowrap tnum`}
        style={{ color: 'var(--text-muted)' }}
      >
        {dt(g.expires_at)}
      </td>
      <td
        className={`${td} whitespace-nowrap tnum`}
        style={{ color: 'var(--text-muted)' }}
      >
        {g.ended_at ? dt(g.ended_at) : '—'}
      </td>
      <td className={td}>
        {g.is_live ? <Badge tone="amber">live</Badge> : <Badge tone="gray">closed</Badge>}
      </td>
    </tr>
  );
}
