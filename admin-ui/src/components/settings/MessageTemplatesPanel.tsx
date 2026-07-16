import { Fragment, useEffect, useRef, useState } from 'react';
import { Loader2, Check, RotateCcw, MessageSquare, AlertTriangle, ArrowRight } from 'lucide-react';
import { api, MessageTemplate } from '../../api/client';
import { Btn, toast } from '../ui';

/**
 * Settings > Message templates — the body of each automated customer SMS.
 *
 * Each template edits independently: change the wording, tap a variable to insert it, watch
 * the live preview and the SMS-segment counter (every extra segment is money the ISP pays),
 * toggle it off, or reset to the default. The server validates that every @variable is one
 * this message actually knows — a typo can never be saved and later sent to a customer.
 */
export default function MessageTemplatesPanel() {
  const [groups, setGroups] = useState<string[]>([]);
  const [templates, setTemplates] = useState<MessageTemplate[] | null>(null);
  // The gateway these SMS actually leave on — so this page is tied to the comms module,
  // not a silo. Null while loading; { name } when a gateway is live; false when none is.
  const [gateway, setGateway] = useState<{ name: string } | null | false>(null);

  useEffect(() => {
    api.messageTemplates
      .get()
      .then((r) => {
        setGroups(r.groups);
        setTemplates(r.templates);
      })
      .catch(() => toast('error', 'Could not load your message templates.'));
    api.messaging
      .providers('sms')
      .then((r) => {
        const active = r.providers.find((p) => p.active);
        setGateway(active ? { name: active.name } : false);
      })
      .catch(() => setGateway(false));
  }, []);

  if (!templates) {
    return (
      <div className="flex items-center gap-2 p-6 text-sm text-[#141414]/50">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading…
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-3xl">
      <div>
        <h2 className="text-lg font-bold font-mono uppercase tracking-wide">Message templates</h2>
        <p className="text-sm text-[#141414]/60 mt-1">
          The body of each automated SMS. Tap a variable below a field to insert it. Blank
          falls back to the default; switch one off to stop sending it.
        </p>
      </div>

      {/* Which gateway these messages leave on — the link to the communications module. */}
      {gateway === false ? (
        <a
          href="#/settings/sms"
          className="flex items-center gap-2.5 border border-[#B26B00] bg-[#FFF8EC] px-3 py-2.5 text-xs hover:bg-[#FFF3DC] transition"
        >
          <AlertTriangle className="h-4 w-4 text-[#B26B00] shrink-0" />
          <span className="flex-1 text-[#141414]/75">
            <b className="text-[#B26B00]">No SMS gateway is active.</b> These messages won&apos;t
            send until you set one up in Communications → SMS.
          </span>
          <span className="inline-flex items-center gap-1 font-mono uppercase text-[10px] text-[#B26B00] font-bold shrink-0">
            Set up <ArrowRight className="h-3 w-3" />
          </span>
        </a>
      ) : gateway ? (
        <a
          href="#/settings/sms"
          className="flex items-center gap-2.5 border border-[#141414]/15 bg-[#f4f4f2] px-3 py-2.5 text-xs hover:border-[#141414]/40 transition"
        >
          <MessageSquare className="h-4 w-4 text-[#228B22] shrink-0" />
          <span className="flex-1 text-[#141414]/70">
            Sending on <b>{gateway.name}</b>. Manage the gateway and balance in Communications.
          </span>
          <span className="inline-flex items-center gap-1 font-mono uppercase text-[10px] text-[#141414]/50 shrink-0">
            SMS settings <ArrowRight className="h-3 w-3" />
          </span>
        </a>
      ) : null}

      {groups.map((group) => {
        const rows = templates.filter((t) => t.group === group);
        if (rows.length === 0) return null;
        return (
          <div key={group} className="space-y-3">
            <h3 className="text-xs font-bold font-mono uppercase tracking-widest text-[#141414]/40">
              {group}
            </h3>
            {rows.map((t) => (
              <Fragment key={t.key}>
                <TemplateCard template={t} />
              </Fragment>
            ))}
          </div>
        );
      })}
    </div>
  );
}

function segmentCount(text: string): number {
  const len = text.length;
  if (len === 0) return 0;
  if (len <= 160) return 1;
  return Math.ceil(len / 153); // concatenated SMS use 153-char parts
}

function renderPreview(body: string, variables: MessageTemplate['variables']): string {
  const map: Record<string, string> = {};
  for (const v of variables) map[v.name] = v.sample;
  return body.replace(/@(\w+)/g, (m, n) => (n in map ? map[n] : m));
}

function TemplateCard({ template }: { template: MessageTemplate }) {
  const [body, setBody] = useState(template.body);
  const [enabled, setEnabled] = useState(template.is_enabled);
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);

  const dirty = body !== template.body || enabled !== template.is_enabled;
  const chars = body.length;
  const segs = segmentCount(body);

  const insert = (name: string) => {
    const el = ref.current;
    const token = `@${name}`;
    if (!el) {
      setBody((b) => b + token);
      return;
    }
    const start = el.selectionStart ?? body.length;
    const end = el.selectionEnd ?? body.length;
    const next = body.slice(0, start) + token + body.slice(end);
    setBody(next);
    // Restore focus + caret just after the inserted token.
    requestAnimationFrame(() => {
      el.focus();
      const pos = start + token.length;
      el.setSelectionRange(pos, pos);
    });
  };

  const save = async () => {
    if (busy || !dirty) return;
    setBusy(true);
    try {
      await api.messageTemplates.update({ key: template.key, body, is_enabled: enabled });
      template.body = body; // keep the card's baseline in step so `dirty` resets
      template.is_enabled = enabled;
      template.is_customized = body.trim() !== '' && body !== template.default_body;
      toast('success', `Saved “${template.label}”.`);
    } catch (e) {
      const msg =
        e && typeof e === 'object' && 'body' in e
          ? String((e as { body?: { body?: string; detail?: string } }).body?.body ||
              (e as { body?: { detail?: string } }).body?.detail || '')
          : '';
      toast('error', msg || 'Could not save this template.');
    } finally {
      setBusy(false);
    }
  };

  const reset = () => setBody(template.default_body);

  return (
    <div className={`bg-white border ${enabled ? 'border-[#141414]/20' : 'border-[#141414]/10'}`}>
      <div className="flex items-start justify-between gap-3 px-4 pt-3.5">
        <div className="min-w-0">
          <h4 className="text-sm font-bold">{template.label}</h4>
          <p className="text-[11px] text-[#141414]/50 mt-0.5">{template.description}</p>
        </div>
        <label className="flex items-center gap-1.5 text-[11px] font-mono uppercase text-[#141414]/60 shrink-0 cursor-pointer">
          <input
            type="checkbox"
            checked={enabled}
            onChange={(e) => setEnabled(e.target.checked)}
            className="accent-[#228B22]"
          />
          {enabled ? 'On' : 'Off'}
        </label>
      </div>

      <div className={`px-4 pb-4 ${enabled ? '' : 'opacity-50'}`}>
        <textarea
          ref={ref}
          value={body}
          onChange={(e) => setBody(e.target.value)}
          disabled={!enabled}
          rows={3}
          className="mt-2.5 w-full bg-white border border-[#141414] p-2.5 text-sm outline-none focus:bg-[#f8f8f6] resize-y"
        />

        {/* variable chips */}
        <div className="mt-2 flex flex-wrap gap-1.5">
          {template.variables.map((v) => (
            <button
              key={v.name}
              onClick={() => insert(v.name)}
              disabled={!enabled}
              title={`Insert @${v.name} — e.g. "${v.sample}"`}
              className="px-1.5 py-0.5 text-[11px] font-mono border border-[#141414]/25 text-[#141414]/70 hover:border-[#141414] hover:text-[#141414] transition disabled:opacity-40"
            >
              @{v.name}
            </button>
          ))}
        </div>

        {/* preview + counter */}
        <div className="mt-3 border border-dashed border-[#141414]/20 bg-[#faf9f7] p-2.5">
          <p className="text-[10px] font-mono uppercase text-[#141414]/40 mb-1">Preview</p>
          <p className="text-xs text-[#141414]/80 leading-relaxed">
            {renderPreview(body, template.variables) || (
              <span className="text-[#141414]/40 italic">
                Empty — the default message will be sent.
              </span>
            )}
          </p>
        </div>

        <div className="mt-2.5 flex items-center justify-between">
          <span
            className={`text-[11px] font-mono ${segs > 1 ? 'text-[#B26B00]' : 'text-[#141414]/45'}`}
          >
            {chars} chars · {segs} SMS{segs > 1 ? ' (costs more)' : ''}
          </span>
          <div className="flex items-center gap-2">
            {body !== template.default_body && (
              <button
                onClick={reset}
                className="inline-flex items-center gap-1 text-[11px] font-mono uppercase text-[#141414]/55 hover:text-[#141414]"
                title="Reset to the default wording"
              >
                <RotateCcw className="h-3 w-3" /> Reset
              </button>
            )}
            <Btn variant="green" onClick={save} disabled={busy || !dirty}>
              {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Check className="h-3.5 w-3.5" />}
              Save
            </Btn>
          </div>
        </div>
      </div>
    </div>
  );
}
