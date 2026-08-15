import { useState } from 'react';
import { Megaphone, Trash2 } from 'lucide-react';
import { api, dt, type Broadcast, type BroadcastDraft } from '../api/client';
import {
  Badge, Btn, Empty, ErrorBox, Panel, RefreshBtn, Spinner, Table, td, toast, useLoad,
} from '../components/ui';

const LEVEL_TONE: Record<Broadcast['level'], 'gray' | 'amber' | 'red'> = {
  info: 'gray',
  warning: 'amber',
  critical: 'red',
};

/**
 * Broadcasts — Danamo speaking to every ISP console at once (maintenance, price changes,
 * outages). Composing one is the owner's call and speaks in the platform's name, so it's
 * audited. Each ISP user sees it as a banner until they dismiss it (or it expires).
 */
export default function BroadcastsView() {
  const { data, error, reload } = useLoad(() => api.broadcasts.list(), []);
  const rows: Broadcast[] = Array.isArray(data) ? data : (data?.results ?? []);

  const act = async (p: Promise<unknown>, msg: string) => {
    try {
      await p;
      toast('green', msg);
      reload();
    } catch (e) {
      toast('red', e instanceof Error ? e.message : 'Something went wrong.');
    }
  };

  return (
    <div className="space-y-5">
      <h1 className="text-lg font-semibold flex items-center gap-2">
        <Megaphone className="h-5 w-5" /> Broadcasts
      </h1>

      <Compose onSent={reload} />

      {error ? (
        <ErrorBox message={error} onRetry={reload} />
      ) : !data ? (
        <Spinner />
      ) : (
        <Panel
          title="All broadcasts"
          subtitle="Live ones show in every ISP console right now. Retire one to stop showing it."
          right={<RefreshBtn onClick={reload} />}
        >
          {rows.length === 0 ? (
            <Empty message="No broadcasts yet." />
          ) : (
            <Table head={['Message', 'Level', 'State', 'Created', '']}>
              {rows.map((b) => (
                <tr key={b.id}>
                  <td className={td}>
                    <span className="font-medium">{b.title}</span>
                    <span className="block text-[11px] max-w-md truncate" style={{ color: 'var(--text-muted)' }}>
                      {b.body}
                    </span>
                  </td>
                  <td className={td}><Badge tone={LEVEL_TONE[b.level]}>{b.level}</Badge></td>
                  <td className={td}>
                    {b.is_live
                      ? <Badge tone="green">live</Badge>
                      : <Badge tone="gray">{b.is_active ? 'scheduled/expired' : 'retired'}</Badge>}
                    {!b.dismissable && <Badge tone="amber">pinned</Badge>}
                  </td>
                  <td className={`${td} whitespace-nowrap`} style={{ color: 'var(--text-muted)' }}>
                    {dt(b.created_at)}
                  </td>
                  <td className={`${td} text-right whitespace-nowrap`}>
                    {b.is_active && (
                      <Btn onClick={() => act(api.broadcasts.update(b.id, { is_active: false }), 'Retired.')}>
                        Retire
                      </Btn>
                    )}
                    <button
                      onClick={() => act(api.broadcasts.remove(b.id), 'Deleted.')}
                      title="Delete"
                      className="ml-2 p-1.5 align-middle cursor-pointer"
                      style={{ color: 'var(--critical)' }}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </Panel>
      )}
    </div>
  );
}

const EMPTY: BroadcastDraft = { title: '', body: '', level: 'info', dismissable: true };

function Compose({ onSent }: { onSent: () => void }) {
  const [form, setForm] = useState<BroadcastDraft>(EMPTY);
  const [busy, setBusy] = useState(false);

  const send = async () => {
    if (!form.title.trim() || !form.body.trim()) return;
    setBusy(true);
    try {
      await api.broadcasts.create({ ...form, title: form.title.trim(), body: form.body.trim() });
      toast('green', 'Broadcast sent to every ISP console.');
      setForm(EMPTY);
      onSent();
    } catch (e) {
      toast('red', e instanceof Error ? e.message : 'Could not send the broadcast.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel title="Compose" subtitle="This appears as a banner in every ISP console. Owner-only, audited.">
      <div className="space-y-3">
        <input
          value={form.title}
          onChange={(e) => setForm({ ...form, title: e.target.value })}
          placeholder="Headline — e.g. Scheduled maintenance Sunday 02:00–04:00"
          className="w-full"
        />
        <textarea
          rows={3}
          value={form.body}
          onChange={(e) => setForm({ ...form, body: e.target.value })}
          placeholder="The details ISPs need to read…"
          className="w-full"
        />
        <div className="flex flex-wrap items-center gap-3">
          <div className="flex items-center gap-1.5">
            {(['info', 'warning', 'critical'] as const).map((l) => (
              <button
                key={l}
                onClick={() => setForm({ ...form, level: l })}
                className={`px-2.5 py-1 text-xs font-mono uppercase border cursor-pointer ${
                  form.level === l ? 'bg-[#141414] text-white border-[#141414]' : 'border-[#141414]/40'
                }`}
              >
                {l}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-1.5 text-xs cursor-pointer" style={{ color: 'var(--text-secondary)' }}>
            <input
              type="checkbox"
              checked={form.dismissable}
              onChange={(e) => setForm({ ...form, dismissable: e.target.checked })}
            />
            Dismissable
            <span style={{ color: 'var(--text-muted)' }}>(uncheck to pin a critical notice)</span>
          </label>
          <div className="flex-1" />
          <Btn variant="dark" onClick={send} disabled={busy || !form.title.trim() || !form.body.trim()}>
            <Megaphone className="h-3.5 w-3.5" /> {busy ? 'Sending…' : 'Send to all ISPs'}
          </Btn>
        </div>
      </div>
    </Panel>
  );
}
