import { useCallback, useEffect, useState } from 'react';
import {
  AlertTriangle,
  Check,
  ExternalLink,
  Globe,
  Loader2,
  RefreshCw,
  Router as RouterIcon,
  X,
} from 'lucide-react';
import { api, ApiError, DomainCheck, DomainState } from '../../api/client';
import { Btn, inputCls, Panel, toast } from '../ui';

/**
 * Domain — where an ISP's subscribers reach their captive portal.
 *
 * This is the most disruptive setting in the product, and the UI says so rather than
 * hiding it behind a text box. Changing the subdomain moves the address customers land
 * on AND invalidates the redirect written onto every router, so the page:
 *
 *   - checks availability as they type, before they can commit to a dead end;
 *   - tells them plainly what saving will do;
 *   - afterwards, shows PER ROUTER whether the new address actually landed. A router that
 *     is offline is still sending customers to the old address, and pretending otherwise
 *     is how an ISP finds out from an angry customer instead of from us.
 */
export default function DomainPanel() {
  const [state, setState] = useState<DomainState | null>(null);
  const [slug, setSlug] = useState('');
  const [check, setCheck] = useState<DomainCheck | null>(null);
  const [checking, setChecking] = useState(false);
  const [saving, setSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);

  const load = useCallback(() => {
    api.domain
      .get()
      .then((s) => {
        setState(s);
        setSlug((prev) => prev || s.slug);
      })
      .catch(() => toast('error', 'Could not load your domain.'));
  }, []);

  useEffect(load, [load]);

  // Availability, debounced. Asking on every keystroke would hammer the API and flicker
  // the answer; asking only on submit would let them type a dead name for 20 seconds.
  useEffect(() => {
    const value = slug.trim().toLowerCase();
    if (!value || !state) {
      setCheck(null);
      return;
    }
    setChecking(true);
    const t = window.setTimeout(() => {
      api.domain
        .check(value)
        .then(setCheck)
        .catch(() => setCheck(null))
        .finally(() => setChecking(false));
    }, 350);
    return () => {
      window.clearTimeout(t);
      setChecking(false);
    };
  }, [slug, state]);

  if (!state) {
    return (
      <div className="flex items-center gap-2 p-6 text-sm text-[#141414]/50">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading…
      </div>
    );
  }

  const changed = slug.trim().toLowerCase() !== state.slug;
  const canSave = changed && check?.available === true && !check.current && !saving;

  const save = async () => {
    if (!canSave) return;
    setSaving(true);
    try {
      const next = await api.domain.change(slug.trim().toLowerCase());
      setState(next);
      setConfirming(false);
      toast(
        'success',
        `You are now at ${next.domain}. Refreshing ${next.routers_queued ?? 0} router(s).`
      );
      // The pushes run in the background; re-read shortly to show what actually landed.
      window.setTimeout(load, 4000);
    } catch (e) {
      toast('error', e instanceof ApiError ? e.message : 'Could not change your domain.');
    } finally {
      setSaving(false);
    }
  };

  const unsynced = state.routers.filter((r) => !r.on_current_domain);

  return (
    <div className="space-y-5">
      <p className="text-xs leading-relaxed text-[#141414]/60">
        Where subscribers reach your captive portal. Pick an available subdomain and save —
        we refresh the hotspot files on your MikroTiks, then move you to the new address.
      </p>

      {/* --- The address they are on now ------------------------------------------ */}
      <Panel title="Active domain">
        <p className="mb-3 text-xs text-[#141414]/55">
          Used for captive-portal redirects and subscriber self-serve.
        </p>
        <div className="flex flex-wrap items-center gap-3 border border-[#141414] bg-white p-4">
          <Globe className="h-4 w-4 shrink-0" />
          <span className="min-w-0 flex-1 truncate font-mono text-sm font-bold">
            {state.domain}
          </span>
          <span className="flex shrink-0 items-center gap-1 bg-[#228B22] px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase text-white">
            <Check className="h-3 w-3" /> Active
          </span>
          <a
            href={state.url}
            target="_blank"
            rel="noreferrer"
            className="shrink-0 text-[#141414]/50 hover:text-[#141414]"
            title="Open"
          >
            <ExternalLink className="h-4 w-4" />
          </a>
        </div>

        {state.previous_url && (
          <p className="mt-3 flex gap-2 border border-[#141414]/15 bg-[#f4f3f0] p-3 text-xs leading-relaxed text-[#141414]/65">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span>
              Your old address <b className="font-mono">{state.previous_slug}.{state.base_domain}</b>{' '}
              still works until{' '}
              <b>{state.grace_ends ? new Date(state.grace_ends).toLocaleDateString() : '—'}</b>, so
              customers with old links and routers that have not refreshed yet are not
              stranded. After that it stops.
            </span>
          </p>
        )}
      </Panel>

      {/* --- Change it ------------------------------------------------------------- */}
      <Panel title="Change domain">
        <p className="mb-3 text-xs leading-relaxed text-[#141414]/55">
          Pick an available subdomain on <b className="font-mono">.{state.base_domain}</b>. Saving
          switches you immediately, redownloads the hotspot portal files on your online
          MikroTiks, then opens the new address.
        </p>

        <div className="flex items-stretch">
          <input
            className={`${inputCls} min-w-0 flex-1 rounded-none`}
            value={slug}
            onChange={(e) => setSlug(e.target.value.toLowerCase())}
            placeholder="acme"
            spellCheck={false}
            autoCapitalize="none"
          />
          <span className="flex shrink-0 items-center border border-l-0 border-[#141414] bg-[#f0efec] px-3 font-mono text-sm text-[#141414]/60">
            .{state.base_domain}
          </span>
        </div>

        <div className="mt-2 min-h-[20px] text-xs">
          {checking && (
            <span className="flex items-center gap-1.5 text-[#141414]/45">
              <Loader2 className="h-3 w-3 animate-spin" /> Checking…
            </span>
          )}
          {!checking && check && check.current && (
            <span className="font-mono text-[#141414]/50">
              https://{check.url.replace('https://', '')} · already active
            </span>
          )}
          {!checking && check && !check.current && check.available && (
            <span className="flex items-center gap-1.5 text-[#228B22]">
              <Check className="h-3.5 w-3.5" />
              <span className="font-mono">{check.url.replace('https://', '')}</span> is available
            </span>
          )}
          {!checking && check && !check.available && (
            <span className="flex items-center gap-1.5 text-[#B22222]">
              <X className="h-3.5 w-3.5" /> {check.reason}
            </span>
          )}
        </div>

        {confirming ? (
          <div className="mt-4 border border-[#141414] bg-[#f4f3f0] p-4">
            <p className="flex gap-2 text-xs leading-relaxed">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[#B22222]" />
              <span>
                You are about to move to <b className="font-mono">{check?.url.replace('https://', '')}</b>.
                Your {state.routers.length} router
                {state.routers.length === 1 ? '' : 's'} will be refreshed to send customers
                there. Any that are offline keep using the old address until they come back —
                your old address stays alive for {state.grace_days} days, so nobody is cut off.
              </span>
            </p>
            <div className="mt-3 flex gap-2">
              <Btn onClick={save} disabled={saving}>
                {saving ? 'Moving…' : 'Yes, move me'}
              </Btn>
              <Btn onClick={() => setConfirming(false)} variant="outline">
                Cancel
              </Btn>
            </div>
          </div>
        ) : (
          <div className="mt-4">
            <Btn onClick={() => setConfirming(true)} disabled={!canSave}>
              Save domain
            </Btn>
          </div>
        )}
      </Panel>

      {/* --- The truth about the routers ------------------------------------------- */}
      <Panel title="Routers on this domain">
        <div className="mb-3 flex items-center justify-between gap-2">
          <p className="text-xs leading-relaxed text-[#141414]/55">
            Which of your MikroTiks are actually sending customers to{' '}
            <b className="font-mono">{state.domain}</b>.
          </p>
          <Btn onClick={load} variant="outline">
            <RefreshCw className="h-3.5 w-3.5" /> Refresh
          </Btn>
        </div>

        {state.routers.length === 0 ? (
          <p className="border border-[#141414]/15 bg-white p-4 text-center text-xs text-[#141414]/50">
            No routers yet.
          </p>
        ) : (
          <div className="space-y-2">
            {state.routers.map((r) => (
              <div
                key={r.id}
                className="flex flex-wrap items-center gap-2 border border-[#141414]/20 bg-white p-3"
              >
                <RouterIcon className="h-4 w-4 shrink-0 text-[#141414]/50" />
                <span className="min-w-0 flex-1 truncate font-mono text-xs font-bold">
                  {r.name}
                </span>
                {r.on_current_domain ? (
                  <span className="flex shrink-0 items-center gap-1 bg-[#228B22] px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase text-white">
                    <Check className="h-3 w-3" /> On this domain
                  </span>
                ) : (
                  <span
                    className="flex shrink-0 items-center gap-1 border border-[#B22222]/50 bg-[#B22222]/5 px-1.5 py-0.5 font-mono text-[10px] font-bold uppercase text-[#B22222]"
                    title={r.error || 'Not confirmed yet'}
                  >
                    <AlertTriangle className="h-3 w-3" />
                    {r.online ? 'Not yet' : 'Offline'}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}

        {unsynced.length > 0 && (
          <p className="mt-3 flex gap-2 text-xs leading-relaxed text-[#141414]/60">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            {state.previous_url ? (
              <span>
                {unsynced.length} router{unsynced.length === 1 ? '' : 's'} still point
                {unsynced.length === 1 ? 's' : ''} at your old address. We keep retrying, and an
                offline router picks the change up when it comes back. Nobody is cut off in the
                meantime — the old address still resolves.
              </span>
            ) : (
              <span>
                {unsynced.length} router{unsynced.length === 1 ? '' : 's'} have not confirmed this
                address yet. That is normal until a router has been onboarded or come online once —
                it will confirm on its next sync.
              </span>
            )}
          </p>
        )}
      </Panel>
    </div>
  );
}
