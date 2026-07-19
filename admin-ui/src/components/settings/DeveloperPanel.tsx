import { useEffect, useState } from 'react';
import { Loader2, KeyRound, Webhook as WebhookIcon, Copy, Check, Trash2, Plus } from 'lucide-react';
import {
  api,
  ApiError,
  ApiToken,
  NewApiToken,
  Webhook,
  WebhookEvent,
} from '../../api/client';
import { Btn, Field, inputCls, Panel, toast } from '../ui';

const fmt = (s: string | null) =>
  s ? new Date(s).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : 'never';

function CopyBox({ label, value }: { label: string; value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="border border-[#228B22]/40 bg-[#F0F7F0] p-3">
      <p className="text-[11px] font-bold uppercase text-[#141414]/60">{label}</p>
      <div className="mt-1.5 flex items-center gap-2">
        <code className="flex-1 truncate border border-[#141414]/15 bg-white px-2 py-1.5 font-mono text-xs">
          {value}
        </code>
        <button
          onClick={() => {
            navigator.clipboard?.writeText(value);
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          }}
          className="flex items-center gap-1 border border-[#141414] bg-[#141414] px-2.5 py-1.5 text-[10px] font-bold uppercase text-[#E4E3E0] hover:bg-[#228B22]"
        >
          {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <p className="mt-1.5 text-[11px] text-[#B26B00]">
        Copy this now — for your security it is never shown again.
      </p>
    </div>
  );
}

export default function DeveloperPanel() {
  const [tokens, setTokens] = useState<ApiToken[] | null>(null);
  const [webhooks, setWebhooks] = useState<Webhook[] | null>(null);
  const [events, setEvents] = useState<WebhookEvent[]>([]);

  // API token form
  const [tokenName, setTokenName] = useState('');
  const [creatingToken, setCreatingToken] = useState(false);
  const [newToken, setNewToken] = useState<NewApiToken | null>(null);

  // Webhook form
  const [label, setLabel] = useState('');
  const [url, setUrl] = useState('');
  const [secret, setSecret] = useState('');
  const [picked, setPicked] = useState<string[]>([]);
  const [creatingHook, setCreatingHook] = useState(false);
  const [newSecret, setNewSecret] = useState<string | null>(null);

  useEffect(() => {
    api.developer.tokens.list().then(setTokens).catch(() => toast('error', 'Could not load tokens.'));
    api.developer.webhooks.list().then(setWebhooks).catch(() => toast('error', 'Could not load webhooks.'));
    api.developer.events().then(setEvents).catch(() => {});
  }, []);

  const createToken = async () => {
    if (!tokenName.trim() || creatingToken) return;
    setCreatingToken(true);
    try {
      const created = await api.developer.tokens.create(tokenName.trim());
      setNewToken(created);
      setTokenName('');
      setTokens((t) => [{ ...created }, ...(t ?? [])]);
      toast('success', 'Token created.');
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'Could not create the token.');
    } finally {
      setCreatingToken(false);
    }
  };

  const revokeToken = async (t: ApiToken) => {
    try {
      await api.developer.tokens.revoke(t.id);
      setTokens((list) => (list ?? []).filter((x) => x.id !== t.id));
      if (newToken?.id === t.id) setNewToken(null);
      toast('success', 'Token revoked.');
    } catch {
      toast('error', 'Could not revoke the token.');
    }
  };

  const togglePick = (key: string) =>
    setPicked((p) => (p.includes(key) ? p.filter((k) => k !== key) : [...p, key]));

  const createHook = async () => {
    if (!label.trim() || !url.trim() || creatingHook) return;
    if (picked.length === 0) {
      toast('error', 'Choose at least one event to forward.');
      return;
    }
    setCreatingHook(true);
    try {
      const created = await api.developer.webhooks.create({
        label: label.trim(),
        url: url.trim(),
        ...(secret.trim() ? { secret: secret.trim() } : {}),
        events: picked,
      });
      setNewSecret(created.secret);
      setWebhooks((w) => [created, ...(w ?? [])]);
      setLabel('');
      setUrl('');
      setSecret('');
      setPicked([]);
      toast('success', 'Webhook added.');
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'Could not add the webhook.');
    } finally {
      setCreatingHook(false);
    }
  };

  const removeHook = async (h: Webhook) => {
    try {
      await api.developer.webhooks.remove(h.id);
      setWebhooks((list) => (list ?? []).filter((x) => x.id !== h.id));
      toast('success', 'Webhook removed.');
    } catch {
      toast('error', 'Could not remove the webhook.');
    }
  };

  if (!tokens || !webhooks) {
    return (
      <div className="flex items-center gap-2 p-6 text-sm text-[#141414]/50">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading…
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h2 className="text-lg font-bold font-mono uppercase tracking-wide">Developer</h2>
        <p className="text-sm text-[#141414]/60 mt-1">
          API tokens for programmatic access, and webhooks for outbound event delivery.
        </p>
      </div>

      {/* ---- API tokens ---------------------------------------------------- */}
      <Panel title="API tokens">
        <p className="text-xs text-[#141414]/60 -mt-1 mb-3 flex items-center gap-1.5">
          <KeyRound className="h-3.5 w-3.5" />
          Personal access tokens for hitting our REST API. Treat them like passwords.
        </p>

        <div className="flex items-end gap-2">
          <Field label="Token name" className="flex-1">
            <input
              className={inputCls}
              value={tokenName}
              onChange={(e) => setTokenName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && createToken()}
              placeholder="e.g. mpesa-reconciler"
            />
          </Field>
          <Btn variant="green" onClick={createToken} disabled={creatingToken || !tokenName.trim()}>
            {creatingToken ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
            Create token
          </Btn>
        </div>

        {newToken && (
          <div className="mt-3">
            <CopyBox label={`New token · ${newToken.name}`} value={newToken.token} />
          </div>
        )}

        <div className="mt-4 border border-[#141414]/15">
          <div className="grid grid-cols-[1fr_auto_auto_auto] gap-3 border-b border-[#141414]/10 px-3 py-1.5 text-[10px] font-mono uppercase text-[#141414]/40">
            <span>Name</span>
            <span>Created</span>
            <span>Last used</span>
            <span />
          </div>
          {tokens.length === 0 ? (
            <p className="px-3 py-3 text-xs text-[#141414]/45">No tokens yet.</p>
          ) : (
            tokens.map((t) => (
              <div
                key={t.id}
                className="grid grid-cols-[1fr_auto_auto_auto] items-center gap-3 border-b border-[#141414]/5 px-3 py-2 text-xs last:border-0"
              >
                <span>
                  <span className="font-bold">{t.name}</span>
                  <span className="ml-2 font-mono text-[#141414]/40">{t.prefix}…</span>
                </span>
                <span className="text-[#141414]/60">{fmt(t.created_at)}</span>
                <span className="text-[#141414]/60">{fmt(t.last_used_at)}</span>
                <button
                  onClick={() => revokeToken(t)}
                  className="text-[11px] font-bold uppercase text-[#B22222] hover:underline"
                >
                  Revoke
                </button>
              </div>
            ))
          )}
        </div>
      </Panel>

      {/* ---- Webhooks ------------------------------------------------------ */}
      <Panel title="Webhooks">
        <p className="text-xs text-[#141414]/60 -mt-1 mb-3 flex items-center gap-1.5">
          <WebhookIcon className="h-3.5 w-3.5" />
          Forward platform events to your own endpoint. We sign every payload with the secret you
          provide.
        </p>

        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Label">
            <input
              className={inputCls}
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder="e.g. Slack notifications"
            />
          </Field>
          <Field label="URL">
            <input
              className={inputCls}
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://example.com/webhooks/wifios"
            />
          </Field>
        </div>
        <Field label="Signing secret" className="mt-3">
          <input
            className={inputCls}
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            placeholder="Auto-generated if blank."
          />
        </Field>

        <div className="mt-3">
          <p className="mb-1.5 font-mono text-[11px] font-bold uppercase text-[#141414]/50">Events</p>
          <div className="grid gap-1.5 sm:grid-cols-2">
            {events.map((ev) => (
              <label key={ev.key} className="flex items-center gap-2 text-xs cursor-pointer">
                <input
                  type="checkbox"
                  checked={picked.includes(ev.key)}
                  onChange={() => togglePick(ev.key)}
                  className="accent-[#228B22] h-3.5 w-3.5"
                />
                <span className="font-mono">{ev.key}</span>
              </label>
            ))}
          </div>
        </div>

        {newSecret && (
          <div className="mt-3">
            <CopyBox label="Signing secret" value={newSecret} />
          </div>
        )}

        <div className="mt-4 flex justify-end">
          <Btn variant="green" onClick={createHook} disabled={creatingHook || !label.trim() || !url.trim()}>
            {creatingHook ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Plus className="h-3.5 w-3.5" />}
            Add webhook
          </Btn>
        </div>

        <div className="mt-4 space-y-2">
          {webhooks.length === 0 ? (
            <p className="text-xs text-[#141414]/45">No webhooks configured.</p>
          ) : (
            webhooks.map((h) => (
              <div key={h.id} className="border border-[#141414]/15 bg-white p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="text-sm font-bold">{h.label}</p>
                    <p className="truncate font-mono text-[11px] text-[#141414]/55">{h.url}</p>
                  </div>
                  <button
                    onClick={() => removeHook(h)}
                    title="Remove"
                    className="shrink-0 text-[#141414]/40 hover:text-[#B22222]"
                  >
                    <Trash2 className="h-4 w-4" />
                  </button>
                </div>
                <div className="mt-2 flex flex-wrap gap-1">
                  {h.events.map((e) => (
                    <span
                      key={e}
                      className="border border-[#141414]/20 bg-[#f0efec] px-1.5 py-0.5 font-mono text-[10px]"
                    >
                      {e}
                    </span>
                  ))}
                </div>
                <p className="mt-2 text-[10px] font-mono text-[#141414]/40">
                  secret {h.secret_preview} · last delivery{' '}
                  {h.last_status ? `${fmt(h.last_delivered_at)} (HTTP ${h.last_status})` : 'never'}
                  {h.last_error ? ` · ${h.last_error}` : ''}
                </p>
              </div>
            ))
          )}
        </div>
      </Panel>
    </div>
  );
}
