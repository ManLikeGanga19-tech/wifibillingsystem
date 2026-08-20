import { useEffect, useState } from 'react';
import { Loader2, Check, Sparkles, KeyRound, ShieldCheck, Zap, MessageSquare } from 'lucide-react';
import { api, ApiError, AISettings, type AIUsage } from '../../api/client';
import { Btn, Field, inputCls, Panel, toast } from '../ui';

// The three ways to run the assistant, shown as a comparison so an ISP can see what they get.
const TIERS = [
  { id: 'free', name: 'Free', model: 'Claude Haiku',
    perks: ['Docs Q&A', 'Your live numbers (read-only)', '100 questions / month'] },
  { id: 'pro', name: 'Pro', model: 'Claude Sonnet',
    perks: ['Everything in Free', 'Propose-and-confirm actions', 'Assistant memory', 'Unlimited'] },
  { id: 'byo', name: 'Your own key', model: 'Your provider',
    perks: ['Everything in Pro', 'Billed to your account', 'Unlimited'] },
] as const;

/**
 * Settings > AI Assistant — choose the provider that powers the dashboard assistant, and
 * optionally supply your own API key. Blank key = the platform default; your key = your account,
 * your bill. The key is stored encrypted and never shown in full after saving.
 */
const PROVIDERS = [
  { id: 'claude', label: 'Claude (Anthropic)', sub: 'claude.ai — Haiku (free) / Sonnet (Pro & BYO)' },
  { id: 'openai', label: 'OpenAI', sub: 'openai.com — GPT-4o mini (free) / GPT-4o (Pro & BYO)' },
] as const;

export default function AIAssistantPanel() {
  const [s, setS] = useState<AISettings | null>(null);
  const [usage, setUsage] = useState<AIUsage | null>(null);
  const [provider, setProvider] = useState<'claude' | 'openai'>('claude');
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.assistant
      .get()
      .then((v) => {
        setS(v);
        setProvider(v.provider);
      })
      .catch(() => toast('error', 'Could not load AI settings.'));
    api.assistant.usage().then(setUsage).catch(() => {});
  }, []);

  if (!s) {
    return (
      <div className="flex items-center gap-2 p-6 text-sm text-[#141414]/50">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading…
      </div>
    );
  }

  const save = async () => {
    if (busy) return;
    setBusy(true);
    try {
      // Only send the key when the operator actually typed one — an empty box leaves the stored
      // key untouched (use "Remove" to clear it back to the platform default).
      const payload: { provider: string; api_key?: string } = { provider };
      if (key.trim()) payload.api_key = key.trim();
      const saved = await api.assistant.update(payload);
      setS(saved);
      setKey('');
      toast('success', 'AI settings saved.');
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'Could not save. Check the key format.');
    } finally {
      setBusy(false);
    }
  };

  const removeKey = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const saved = await api.assistant.update({ api_key: '' });
      setS(saved);
      setKey('');
      toast('success', 'Your key was removed — using the platform default.');
    } catch {
      toast('error', 'Could not remove the key.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h2 className="text-lg font-bold font-mono uppercase tracking-wide">AI Assistant</h2>
        <p className="text-sm text-[#141414]/60 mt-1">
          Choose the AI provider that powers the assistant and optionally supply your own API key —
          the assistant will use your account instead of the platform default.
        </p>
      </div>

      {/* Plan & usage */}
      <Panel title="Your plan & usage">
        {usage && (
          <div className="-mt-1 mb-4">
            <div className="flex items-center justify-between">
              <span className="flex items-center gap-2 text-sm">
                <span className="font-mono uppercase text-[10px] text-[#141414]/40">Current tier</span>
                <span className="inline-flex items-center gap-1 border border-[#141414] px-2 py-0.5 text-xs font-bold uppercase">
                  {usage.unlimited && <Zap className="h-3 w-3 text-[#228B22]" />}
                  {usage.tier === 'byo' ? 'Your own key' : usage.tier === 'pro' ? 'Pro' : 'Free'}
                </span>
              </span>
              <span className="flex items-center gap-1.5 text-xs text-[#141414]/60">
                <MessageSquare className="h-3.5 w-3.5" />
                {usage.unlimited
                  ? 'Unlimited this month'
                  : `${usage.used} of ${usage.limit} questions used this month`}
              </span>
            </div>
            {!usage.unlimited && usage.limit != null && (
              <div className="mt-2 h-2 w-full bg-[#141414]/10">
                <div
                  className="h-full bg-[#228B22]"
                  style={{ width: `${Math.min(100, Math.round((usage.used / usage.limit) * 100))}%` }}
                />
              </div>
            )}
          </div>
        )}

        {/* Tier comparison */}
        <div className="grid gap-3 sm:grid-cols-3">
          {TIERS.map((t) => {
            const active = usage?.tier === t.id;
            return (
              <div
                key={t.id}
                className={`border p-3 ${active ? 'border-[#141414] bg-[#f0efec]' : 'border-[#141414]/20'}`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-bold">{t.name}</span>
                  {active && (
                    <span className="text-[9px] font-bold uppercase text-[#228B22]">Current</span>
                  )}
                </div>
                <div className="mb-2 font-mono text-[10px] uppercase text-[#141414]/40">{t.model}</div>
                <ul className="space-y-1">
                  {t.perks.map((p) => (
                    <li key={p} className="flex items-start gap-1.5 text-[11px] text-[#141414]/70">
                      <Check className="mt-0.5 h-3 w-3 shrink-0 text-[#228B22]" /> {p}
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </div>

        {usage && !usage.unlimited && (
          <p className="mt-3 flex items-start gap-1.5 border border-[#B26B00]/30 bg-[#FFF8EC] p-2.5 text-[11px] text-[#7a4a00]">
            <Zap className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>
              Want unlimited use, actions and memory? <b>Add your own API key below</b> to switch on
              unlimited right away, or contact us to enable <b>Pro</b> on your account.
            </span>
          </p>
        )}
      </Panel>

      {/* Provider */}
      <Panel title="Provider">
        <p className="text-xs text-[#141414]/60 -mt-1 mb-3 flex items-center gap-1.5">
          <Sparkles className="h-3.5 w-3.5" />
          Which large language model powers the AI Chat assistant for your ISP dashboard.
        </p>
        <div className="space-y-2.5">
          {PROVIDERS.map((p) => (
            <label
              key={p.id}
              className={`flex items-start gap-2.5 cursor-pointer border p-3 transition ${
                provider === p.id
                  ? 'border-[#141414] bg-[#f0efec]'
                  : 'border-[#141414]/20 hover:bg-[#f4f4f2]'
              }`}
            >
              <input
                type="radio"
                name="ai-provider"
                checked={provider === p.id}
                onChange={() => setProvider(p.id)}
                className="accent-[#141414] h-4 w-4 mt-0.5"
              />
              <span>
                <span className="block text-sm font-bold">{p.label}</span>
                <span className="block text-[11px] text-[#141414]/50">{p.sub}</span>
              </span>
            </label>
          ))}
        </div>
      </Panel>

      {/* API key */}
      <Panel title="API key (optional)">
        <p className="text-xs text-[#141414]/60 -mt-1 mb-3 flex items-start gap-1.5">
          <KeyRound className="h-3.5 w-3.5 mt-0.5 shrink-0" />
          <span>
            Leave blank to use the platform default. If you enter your own key, the AI Chat
            assistant will call the selected provider directly using your account — usage and costs
            are billed to you.
          </span>
        </p>

        {s.has_own_key && (
          <div className="mb-3 flex items-center justify-between border border-[#228B22]/40 bg-[#F0F7F0] px-3 py-2">
            <span className="flex items-center gap-2 text-xs">
              <ShieldCheck className="h-3.5 w-3.5 text-[#228B22]" />
              Your key is set — <span className="font-mono">{s.key_preview}</span>
            </span>
            <button
              onClick={removeKey}
              disabled={busy}
              className="text-[11px] font-bold uppercase text-[#B22222] hover:underline"
            >
              Remove
            </button>
          </div>
        )}

        <Field label={s.has_own_key ? 'Replace key' : 'Your key'}>
          <input
            type="password"
            autoComplete="off"
            className={inputCls}
            value={key}
            onChange={(e) => setKey(e.target.value)}
            placeholder="sk-… or sk-ant-…"
          />
          <p className="text-[11px] text-[#141414]/45 mt-1">
            Anthropic keys start with <span className="font-mono">sk-ant-</span>. OpenAI keys start
            with <span className="font-mono">sk-</span>. The key is stored encrypted and never shown
            in full after saving.
          </p>
        </Field>

        {!s.has_own_key && (
          <p className="text-[11px] mt-3 p-2 bg-[#f4f4f2] border border-[#141414]/10 text-[#141414]/60">
            {s.platform_default_available
              ? `Using the platform default (${s.platform_default_provider === 'openai' ? 'OpenAI' : 'Claude'}). Add your own key above to bill usage to your account instead.`
              : 'The platform default isn’t configured yet, so the assistant stays off until you add your own key above.'}
          </p>
        )}
      </Panel>

      <div className="flex justify-end">
        <Btn variant="green" onClick={save} disabled={busy}>
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
          Save changes
        </Btn>
      </div>
    </div>
  );
}
