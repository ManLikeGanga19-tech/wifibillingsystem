import { useEffect, useState } from 'react';
import { KeyRound, ShieldCheck, Zap, Check, Loader2, Sparkles, FileWarning } from 'lucide-react';
import {
  api, ApiError, type PlatformAISettings, type PlatformAISettingsInput, type DocsGaps,
} from '../api/client';
import {
  Panel, Btn, ViewHeader, Spinner, ErrorBox, Stat, Table, td, useLoad, Badge, toast,
} from '../components/ui';

/**
 * The docs-gaps report — cross-tenant, anonymised. What tenants ask the assistant and, crucially,
 * where it had NO grounded answer (by the doc each question was nearest to). That's the ranked
 * list of docs to write or improve next. No question text, no tenant identity — only page slugs
 * and counts.
 */
function DocsGapsReport() {
  const [days, setDays] = useState(30);
  const { data, error, reload } = useLoad<DocsGaps>(() => api.docsGaps(days), [days]);

  if (error) return <ErrorBox message={error} onRetry={reload} />;
  if (!data) return <Spinner />;

  const rate = data.grounded_rate != null ? `${Math.round(data.grounded_rate * 100)}%` : '—';
  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="flex items-center gap-2 font-mono text-sm font-bold uppercase tracking-wide">
          <FileWarning className="h-4 w-4" /> Docs gaps
        </h3>
        <select
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
          className="border border-[#141414]/25 bg-white px-2 py-1 text-xs"
        >
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
        </select>
      </div>

      <div className="grid gap-3 sm:grid-cols-3">
        <Stat label="Questions asked" value={String(data.total_questions)} />
        <Stat label="Answered from docs" value={rate} />
        <Stat label="Unanswered" value={String(data.unanswered)} />
      </div>

      {data.total_questions === 0 ? (
        <p className="border border-[#141414]/10 bg-[#f4f4f2] p-3 text-xs text-[#141414]/50">
          No assistant questions yet in this window. Once tenants start asking, the gaps show here.
        </p>
      ) : (
        <div className="grid gap-4 lg:grid-cols-2">
          <div>
            <p className="mb-1 text-[11px] font-mono uppercase text-[#141414]/50">
              Write / improve these next (unanswered, by nearest doc)
            </p>
            <Table head={['Doc page', 'Unanswered']}>
              {data.gaps.length === 0 ? (
                <tr><td className={td} colSpan={2}>No gaps — every question found an answer.</td></tr>
              ) : data.gaps.map((g) => (
                <tr key={g.topic}>
                  <td className={td}><span className="font-mono">{g.topic}</span></td>
                  <td className={td}><Badge tone="red">{g.count}</Badge></td>
                </tr>
              ))}
            </Table>
          </div>

          <div>
            <p className="mb-1 text-[11px] font-mono uppercase text-[#141414]/50">Most asked about</p>
            <Table head={['Doc page', 'Asked', 'Answered']}>
              {data.top_topics.map((t) => (
                <tr key={t.topic}>
                  <td className={td}><span className="font-mono">{t.topic}</span></td>
                  <td className={td}>{t.count}</td>
                  <td className={td}>{t.answered}</td>
                </tr>
              ))}
            </Table>
          </div>
        </div>
      )}

      {data.thumbs_down.length > 0 && (
        <div>
          <p className="mb-1 text-[11px] font-mono uppercase text-[#141414]/50">
            Rated unhelpful (👎) — answers to improve
          </p>
          <Table head={['Doc page', '👎']}>
            {data.thumbs_down.map((t) => (
              <tr key={t.topic}>
                <td className={td}><span className="font-mono">{t.topic}</span></td>
                <td className={td}>{t.count}</td>
              </tr>
            ))}
          </Table>
        </div>
      )}
    </div>
  );
}

/**
 * The cross-tenant AI key. This is the SHARED key every free and Pro tenant rides when they
 * haven't brought their own — Danamo pays this bill, so it's rate-limited platform-wide to bound
 * the cost of a simultaneous spike across all ISPs. Owner-only; the key is stored encrypted and
 * never shown in full after saving.
 */
export default function AIKeyView() {
  const [s, setS] = useState<PlatformAISettings | null>(null);
  const [err, setErr] = useState('');
  const [provider, setProvider] = useState<'claude' | 'openai'>('claude');
  const [enabled, setEnabled] = useState(true);
  const [rate, setRate] = useState(60);
  const [key, setKey] = useState('');
  const [busy, setBusy] = useState(false);

  const load = () => {
    api.aiSettings
      .get()
      .then((v) => {
        setS(v);
        setProvider(v.provider);
        setEnabled(v.enabled);
        setRate(v.rate_limit_per_min);
      })
      .catch((e) => setErr(e instanceof ApiError ? e.message : 'Could not load AI key settings.'));
  };
  useEffect(load, []);

  const save = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const body: Partial<PlatformAISettingsInput> = {
        provider,
        enabled,
        rate_limit_per_min: rate,
      };
      if (key.trim()) body.api_key = key.trim();
      const saved = await api.aiSettings.update(body);
      setS(saved);
      setKey('');
      toast('green', 'Platform AI key saved.');
    } catch (e) {
      toast('red', e instanceof ApiError ? e.message : 'Could not save.');
    } finally {
      setBusy(false);
    }
  };

  const clearKey = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const saved = await api.aiSettings.update({ api_key: '' });
      setS(saved);
      setKey('');
      toast('green', 'Key cleared — using the environment fallback if set.');
    } catch {
      toast('red', 'Could not clear the key.');
    } finally {
      setBusy(false);
    }
  };

  if (err) return <ErrorBox message={err} onRetry={() => { setErr(''); load(); }} />;
  if (!s) return <Spinner />;

  const inputCls =
    'w-full border border-[#141414]/25 bg-white px-2.5 py-2 text-sm focus:border-[#141414] focus:outline-none';

  return (
    <div className="space-y-5 max-w-4xl">
      <ViewHeader
        icon={<Sparkles className="h-5 w-5" />}
        title="AI Assistant"
        subtitle="Docs gaps across all ISPs, and the shared cross-tenant key."
      />

      <Panel title="Docs-gaps report">
        <DocsGapsReport />
      </Panel>

      <Panel title="Shared key">
        <p className="mb-3 flex items-start gap-1.5 text-xs text-[#141414]/60">
          <KeyRound className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            The platform's own provider key. Tenants who bring their own key aren't affected by
            this — they call their own account. Stored encrypted; never shown in full after saving.
          </span>
        </p>

        {s.has_key ? (
          <div className="mb-3 flex items-center justify-between border border-[#228B22]/40 bg-[#F0F7F0] px-3 py-2 text-xs">
            <span className="flex items-center gap-2">
              <ShieldCheck className="h-3.5 w-3.5 text-[#228B22]" />
              Key set — <span className="font-mono">{s.key_preview}</span>
            </span>
            <button onClick={clearKey} disabled={busy} className="font-bold uppercase text-[#B22222] hover:underline">
              Clear
            </button>
          </div>
        ) : (
          <div className="mb-3 border border-[#B26B00]/30 bg-[#FFF8EC] px-3 py-2 text-xs text-[#7a4a00]">
            {s.env_fallback_available
              ? 'No key stored here — an environment key is being used as the fallback.'
              : 'No key set and no environment fallback — the free/Pro assistant is off until you add one.'}
          </div>
        )}

        <label className="block text-[11px] font-mono uppercase text-[#141414]/50 mb-1">
          {s.has_key ? 'Replace key' : 'Provider key'}
        </label>
        <input
          type="password"
          autoComplete="off"
          className={inputCls}
          value={key}
          onChange={(e) => setKey(e.target.value)}
          placeholder="sk-ant-… or sk-…"
        />
      </Panel>

      <Panel title="Provider & limits">
        <div className="space-y-4">
          <div>
            <label className="block text-[11px] font-mono uppercase text-[#141414]/50 mb-1">Provider</label>
            <select className={inputCls} value={provider} onChange={(e) => setProvider(e.target.value as 'claude' | 'openai')}>
              <option value="claude">Claude (Anthropic)</option>
              <option value="openai">OpenAI</option>
            </select>
          </div>

          <div>
            <label className="flex items-center gap-1.5 text-[11px] font-mono uppercase text-[#141414]/50 mb-1">
              <Zap className="h-3 w-3" /> Platform-wide rate limit (requests / minute)
            </label>
            <input
              type="number"
              min={0}
              className={inputCls}
              value={rate}
              onChange={(e) => setRate(Math.max(0, Number(e.target.value) || 0))}
            />
            <p className="mt-1 text-[11px] text-[#141414]/45">
              One counter across ALL tenants on the shared key — the guard against a global spike.
              Set <b>0</b> to disable this cap (the per-tenant monthly budget still applies).
            </p>
          </div>

          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} className="h-4 w-4 accent-[#141414]" />
            Use this stored key (uncheck to fall back to the environment key)
          </label>
        </div>
      </Panel>

      <div className="flex justify-end">
        <Btn variant="green" onClick={save} disabled={busy}>
          {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
          Save
        </Btn>
      </div>
    </div>
  );
}
