import { useState } from 'react';
import { Search } from 'lucide-react';
import { api, dt, ksh, type SearchResults } from '../api/client';
import { Badge, Btn, Empty, Panel, Spinner, STATUS_TONE, Table, td, tdStyle } from '../components/ui';

/**
 * Cross-tenant search.
 *
 * The support tool that makes impersonation rare: find a payment, a phone, an
 * account number, a router — across EVERY ISP — without opening anyone's console.
 * Every hit names the tenant it belongs to, so you always know whose data you are
 * looking at.
 */
export default function SearchView() {
  const [q, setQ] = useState('');
  const [data, setData] = useState<SearchResults | null>(null);
  const [busy, setBusy] = useState(false);

  const run = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (q.trim().length < 3) return;
    setBusy(true);
    try {
      setData(await api.search(q.trim()));
    } finally {
      setBusy(false);
    }
  };

  const r = data?.results;

  return (
    <div className="space-y-5">
      <Panel
        title="Find anything, across every ISP"
        subtitle="M-Pesa receipt · phone · account number · PPPoE username · router · ISP name"
      >
        <form onSubmit={run} className="flex gap-2">
          <input
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="e.g. QWE123XYZ, 254712345678, HOME10432…"
          />
          <Btn variant="primary" type="submit" disabled={busy || q.trim().length < 3}>
            <Search className="h-3.5 w-3.5" />
            {busy ? 'Searching…' : 'Search'}
          </Btn>
        </form>
        {q.trim().length > 0 && q.trim().length < 3 && (
          <p className="text-[11px] mt-2" style={{ color: 'var(--text-muted)' }}>
            Enter at least 3 characters.
          </p>
        )}
      </Panel>

      {busy && <Spinner />}

      {data && !busy && (
        <>
          <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
            {data.total} result{data.total === 1 ? '' : 's'} for “{data.q}”
          </p>
          {data.total === 0 && <Empty message="Nothing found anywhere on the platform." />}

          {!!r?.transactions?.length && (
            <Panel title="Hotspot payments">
              <Table head={['ISP', 'Phone', 'Amount', 'Receipt', 'Status', 'When']}>
                {r.transactions.map((t) => (
                  <tr key={t.id}>
                    <Tenant slug={t.tenant} />
                    <td className={`${td} tnum`} style={tdStyle}>
                      {t.phone}
                    </td>
                    <td className={`${td} tnum`} style={tdStyle}>
                      {ksh(t.amount)}
                    </td>
                    <td className={`${td} tnum`} style={tdStyle}>
                      {t.mpesa_receipt || '—'}
                    </td>
                    <td className={td} style={tdStyle}>
                      <Badge tone={STATUS_TONE[t.status] ?? 'neutral'}>{t.status}</Badge>
                    </td>
                    <Muted>{dt(t.created_at)}</Muted>
                  </tr>
                ))}
              </Table>
            </Panel>
          )}

          {!!r?.c2b_payments?.length && (
            <Panel
              title="Broadband payments (C2B)"
              subtitle="Unmatched rows are money that arrived with an account number we don't recognise."
            >
              <Table head={['ISP', 'TransID', 'Account ref', 'Payer', 'Amount', 'Status', 'When']}>
                {r.c2b_payments.map((p) => (
                  <tr key={p.id}>
                    <Tenant slug={p.tenant} />
                    <td className={`${td} tnum`} style={tdStyle}>
                      {p.trans_id}
                    </td>
                    <td className={`${td} tnum`} style={tdStyle}>
                      {p.bill_ref}
                    </td>
                    <td className={`${td} tnum`} style={tdStyle}>
                      {p.msisdn}
                    </td>
                    <td className={`${td} tnum`} style={tdStyle}>
                      {ksh(p.amount)}
                    </td>
                    <td className={td} style={tdStyle}>
                      <Badge tone={STATUS_TONE[p.status] ?? 'neutral'}>{p.status}</Badge>
                    </td>
                    <Muted>{dt(p.received_at)}</Muted>
                  </tr>
                ))}
              </Table>
            </Panel>
          )}

          {!!r?.pppoe_clients?.length && (
            <Panel title="Broadband clients">
              <Table head={['ISP', 'Account', 'Name', 'Phone', 'Plan', 'Status']}>
                {r.pppoe_clients.map((c) => (
                  <tr key={c.id}>
                    <Tenant slug={c.tenant} />
                    <td className={`${td} tnum`} style={tdStyle}>
                      {c.account_number}
                    </td>
                    <td className={td} style={tdStyle}>
                      {c.full_name}
                    </td>
                    <td className={`${td} tnum`} style={tdStyle}>
                      {c.phone || '—'}
                    </td>
                    <Muted>{c.plan}</Muted>
                    <td className={td} style={tdStyle}>
                      <Badge tone={STATUS_TONE[c.status] ?? 'neutral'}>{c.status}</Badge>
                    </td>
                  </tr>
                ))}
              </Table>
            </Panel>
          )}

          {!!r?.subscribers?.length && (
            <Panel title="Hotspot customers">
              <Table head={['ISP', 'Phone', 'Name']}>
                {r.subscribers.map((s) => (
                  <tr key={s.id}>
                    <Tenant slug={s.tenant} />
                    <td className={`${td} tnum`} style={tdStyle}>
                      {s.phone}
                    </td>
                    <td className={td} style={tdStyle}>
                      {s.name || '—'}
                    </td>
                  </tr>
                ))}
              </Table>
            </Panel>
          )}

          {!!r?.routers?.length && (
            <Panel title="Routers">
              <Table head={['ISP', 'Name', 'Host', 'Status']}>
                {r.routers.map((x) => (
                  <tr key={x.id}>
                    <Tenant slug={x.tenant} />
                    <td className={td} style={tdStyle}>
                      {x.name}
                    </td>
                    <td className={`${td} tnum`} style={tdStyle}>
                      {x.host}
                    </td>
                    <td className={td} style={tdStyle}>
                      <Badge tone={STATUS_TONE[x.status] ?? 'neutral'}>{x.status}</Badge>
                    </td>
                  </tr>
                ))}
              </Table>
            </Panel>
          )}

          {!!r?.tenants?.length && (
            <Panel title="ISPs">
              <Table head={['Name', 'Slug', 'Status']}>
                {r.tenants.map((t) => (
                  <tr key={t.id}>
                    <td className={td} style={tdStyle}>
                      {t.name}
                    </td>
                    <td className={`${td} tnum`} style={tdStyle}>
                      {t.slug}
                    </td>
                    <td className={td} style={tdStyle}>
                      <Badge tone={STATUS_TONE[t.status] ?? 'neutral'}>{t.status}</Badge>
                    </td>
                  </tr>
                ))}
              </Table>
            </Panel>
          )}
        </>
      )}
    </div>
  );
}

/** Every hit says whose data it is — you should never be unsure. */
function Tenant({ slug }: { slug: string }) {
  return (
    <td className={td} style={tdStyle}>
      <Badge tone="accent">{slug || 'unmatched'}</Badge>
    </td>
  );
}

function Muted({ children }: { children: React.ReactNode }) {
  return (
    <td
      className={`${td} whitespace-nowrap tnum`}
      style={{ ...tdStyle, color: 'var(--text-muted)' }}
    >
      {children}
    </td>
  );
}
