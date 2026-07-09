import { useState, type FormEvent } from 'react';
import { Mail, Send } from 'lucide-react';
import { api } from '../api/client';
import { Badge, Btn, Field, inputCls, Panel, RefreshBtn, TableShell, tdCls, toast, useList, ViewHeader, fmtDateTime } from './ui';

const AUDIENCES = [
  { value: 'all', label: 'All clients with an email' },
  { value: 'active', label: 'Active clients' },
  { value: 'expired', label: 'Expired clients' },
] as const;

export default function EmailsView() {
  const [subject, setSubject] = useState('');
  const [body, setBody] = useState('');
  const [audience, setAudience] = useState<'all' | 'active' | 'expired'>('all');
  const [busy, setBusy] = useState(false);
  const { rows, error, reload } = useList(() => api.messages.list('?channel=email'));

  const send = async (e: FormEvent) => {
    e.preventDefault();
    if (busy) return;
    setBusy(true);
    try {
      await api.campaigns.create({
        name: subject || 'Email broadcast',
        channel: 'email',
        audience,
        subject,
        body,
      });
      toast('success', 'Email broadcast queued — deliveries appear below.');
      setSubject('');
      setBody('');
      window.setTimeout(reload, 1500);
    } catch {
      toast('error', 'Failed to queue the email broadcast.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5 text-[#141414]">
      <ViewHeader
        icon={<Mail className="h-4.5 w-4.5" />}
        title="Emails"
        subtitle="Email broadcasts to clients who have an email on file. Individual deliveries are logged below."
      >
        <RefreshBtn onClick={reload} />
      </ViewHeader>

      <Panel title="Compose email broadcast">
        <form onSubmit={send} className="space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <Field label="Subject" className="md:col-span-2">
              <input required value={subject} onChange={(e) => setSubject(e.target.value)} className={inputCls} placeholder="e.g. New plans this month" />
            </Field>
            <Field label="Send to">
              <select value={audience} onChange={(e) => setAudience(e.target.value as typeof audience)} className={inputCls}>
                {AUDIENCES.map((a) => <option key={a.value} value={a.value}>{a.label}</option>)}
              </select>
            </Field>
          </div>
          <Field label="Message">
            <textarea required rows={5} maxLength={2000} value={body} onChange={(e) => setBody(e.target.value)} className={inputCls} />
          </Field>
          <Btn type="submit" variant="green" disabled={busy}>
            <Send className="h-3.5 w-3.5" />
            {busy ? 'Queuing…' : 'Send broadcast'}
          </Btn>
        </form>
      </Panel>

      <TableShell
        headers={['To', 'Subject', 'Status', 'Sent']}
        loading={rows === null}
        error={error}
        empty="No emails sent yet. Note: clients only get an email address if you add one to their profile."
      >
        {(rows ?? []).map((m) => (
          <tr key={m.id} className="hover:bg-[#f0efec]/40 transition">
            <td className={`${tdCls} font-mono font-bold`}>{m.to_email}</td>
            <td className={tdCls}>
              <span className="font-bold block">{m.subject || '—'}</span>
              <span className="text-[#141414]/70 block max-w-[24rem] truncate">{m.body}</span>
            </td>
            <td className={tdCls}>
              <Badge color={m.status === 'sent' ? 'green' : m.status === 'failed' ? 'red' : 'gray'}>{m.status}</Badge>
              {m.error && <span className="block text-[11px] text-[#B22222] font-mono mt-0.5">{m.error}</span>}
            </td>
            <td className={`${tdCls} font-mono whitespace-nowrap`}>{fmtDateTime(m.sent_at ?? m.created_at)}</td>
          </tr>
        ))}
      </TableShell>
    </div>
  );
}
