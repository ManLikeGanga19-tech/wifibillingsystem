import { useState, type FormEvent } from 'react';
import { Router as RouterIcon, Plus, Plug } from 'lucide-react';
import { api, ApiRouter } from '../api/client';
import {
  Badge, Btn, Field, inputCls, Panel, RefreshBtn, TableShell, tdCls, toast, useList, ViewHeader, fmtDateTime,
} from './ui';

export default function RoutersView() {
  const [showForm, setShowForm] = useState(false);
  const [testing, setTesting] = useState<number | null>(null);
  const [form, setForm] = useState({
    name: '',
    management_host: '',
    api_port: '443',
    username: 'admin',
    password: '',
    provisioning_backend: 'mikrotik_rest' as ApiRouter['provisioning_backend'],
  });
  const { rows, error, reload } = useList(() => api.routers.list());

  const create = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.routers.create({ ...form, api_port: Number(form.api_port) } as Partial<ApiRouter> & { password: string });
      toast('success', `Router "${form.name}" registered.`);
      setShowForm(false);
      setForm({ ...form, name: '', management_host: '', password: '' });
      reload();
    } catch {
      toast('error', 'Failed to register router.');
    }
  };

  const test = async (router: ApiRouter) => {
    setTesting(router.id);
    try {
      const r = await api.routers.testConnection(router.id);
      if (r.ok) toast('success', `${router.name} is reachable.`);
      else toast('error', `${router.name} did not respond${r.detail ? `: ${r.detail}` : '.'}`);
    } catch (e) {
      toast('error', e instanceof Error ? e.message : 'Connection test failed.');
    } finally {
      setTesting(null);
      reload();
    }
  };

  return (
    <div className="space-y-5 text-[#141414]">
      <ViewHeader
        icon={<RouterIcon className="h-4.5 w-4.5" />}
        title="MikroTik Routers"
        subtitle="One entry per site. The server reaches each router over its WireGuard tunnel IP and provisions hotspot users via the RouterOS v7 REST API."
      >
        <Btn onClick={() => setShowForm(!showForm)}>
          <Plus className="h-3.5 w-3.5" /> Add Router
        </Btn>
        <RefreshBtn onClick={reload} />
      </ViewHeader>

      {showForm && (
        <Panel title="Register router">
          <form onSubmit={create} className="grid grid-cols-1 md:grid-cols-6 gap-3 items-end">
            <Field label="Site name" className="md:col-span-2">
              <input required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} className={inputCls} placeholder="e.g. Kibera Site A" />
            </Field>
            <Field label="Management IP (WireGuard)">
              <input required value={form.management_host} onChange={(e) => setForm({ ...form, management_host: e.target.value })} className={inputCls} placeholder="10.10.0.2" />
            </Field>
            <Field label="API port">
              <input type="number" required value={form.api_port} onChange={(e) => setForm({ ...form, api_port: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Username">
              <input required value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Password">
              <input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} className={inputCls} />
            </Field>
            <Field label="Backend" className="md:col-span-2">
              <select
                value={form.provisioning_backend}
                onChange={(e) => setForm({ ...form, provisioning_backend: e.target.value as ApiRouter['provisioning_backend'] })}
                className={inputCls}
              >
                <option value="mikrotik_rest">MikroTik RouterOS v7 REST</option>
                <option value="dummy">Dummy (testing without hardware)</option>
              </select>
            </Field>
            <Btn type="submit" variant="green">Register</Btn>
          </form>
        </Panel>
      )}

      <TableShell
        headers={['Site', 'Management IP', 'Backend', 'Status', 'Last seen', '']}
        loading={rows === null}
        error={error}
        empty="No routers yet — add your first site to start provisioning."
      >
        {(rows ?? []).map((r) => (
          <tr key={r.id} className="hover:bg-[#f0efec]/40 transition">
            <td className={`${tdCls} font-bold`}>{r.name}</td>
            <td className={`${tdCls} font-mono`}>{r.management_host}:{r.api_port}</td>
            <td className={tdCls}><Badge color={r.provisioning_backend === 'dummy' ? 'gray' : 'blue'}>{r.provisioning_backend === 'dummy' ? 'dummy' : 'mikrotik'}</Badge></td>
            <td className={tdCls}>
              <Badge color={r.status === 'online' ? 'green' : r.status === 'offline' ? 'red' : 'gray'}>{r.status}</Badge>
            </td>
            <td className={`${tdCls} font-mono whitespace-nowrap`}>{fmtDateTime(r.last_seen_at)}</td>
            <td className={tdCls}>
              <Btn variant="outline" onClick={() => test(r)} disabled={testing === r.id}>
                <Plug className="h-3.5 w-3.5" />
                {testing === r.id ? 'Testing…' : 'Test connection'}
              </Btn>
            </td>
          </tr>
        ))}
      </TableShell>
    </div>
  );
}
