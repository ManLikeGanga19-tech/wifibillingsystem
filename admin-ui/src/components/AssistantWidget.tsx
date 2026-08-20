import { useEffect, useRef, useState } from 'react';
import {
  Sparkles, X, Send, Loader2, Settings2, ThumbsUp, ThumbsDown, BookOpen, Zap,
  MessagesSquare, Plus, Pencil, Trash2, ChevronLeft,
} from 'lucide-react';
import { api, ApiError, type AIUsage, type ChatSource, type Conversation, type ConvMessage } from '../api/client';

type Turn = ConvMessage & { rating?: 1 | -1 | 0 };

// The docs site — citations deep-link to the exact page the answer came from.
const DOCS_BASE = 'https://docs.wifios.co.ke';

/**
 * The floating AI assistant. Grounded in the product docs (answers cite the page), tier-aware
 * (a usage meter + upgrade prompt), and organised into saved, named conversations — one thread
 * per task, private to the signed-in staff member and kept on the server (no browser storage).
 */
export default function AssistantWidget() {
  const [open, setOpen] = useState(false);
  const [convos, setConvos] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<number | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [showList, setShowList] = useState(false);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [usage, setUsage] = useState<AIUsage | null>(null);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight });
  }, [turns, busy]);

  const loadConvos = () =>
    api.assistant.conversations.list().then((r) => setConvos(r.results)).catch(() => {});

  // On open: load the thread list + usage, and open the most recent thread (or a fresh one).
  useEffect(() => {
    if (!open) return;
    api.assistant.usage().then(setUsage).catch(() => {});
    api.assistant.conversations
      .list()
      .then((r) => {
        setConvos(r.results);
        if (r.results.length && activeId == null) openConvo(r.results[0].id);
      })
      .catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const openConvo = async (id: number) => {
    setShowList(false);
    setNotice(null);
    try {
      const detail = await api.assistant.conversations.get(id);
      setActiveId(detail.id);
      setTurns(detail.messages);
    } catch {
      setNotice('Could not open that conversation.');
    }
  };

  const newChat = () => {
    setActiveId(null);
    setTurns([]);
    setShowList(false);
    setNotice(null);
  };

  const renameConvo = async (c: Conversation) => {
    const title = window.prompt('Rename conversation', c.title)?.trim();
    if (!title || title === c.title) return;
    try {
      await api.assistant.conversations.rename(c.id, title);
      setConvos((cs) => cs.map((x) => (x.id === c.id ? { ...x, title } : x)));
    } catch { /* non-critical */ }
  };

  const deleteConvo = async (c: Conversation) => {
    if (!window.confirm(`Delete "${c.title || 'this conversation'}"?`)) return;
    try {
      await api.assistant.conversations.remove(c.id);
      setConvos((cs) => cs.filter((x) => x.id !== c.id));
      if (activeId === c.id) newChat();
    } catch { /* non-critical */ }
  };

  const send = async () => {
    const text = draft.trim();
    if (!text || busy) return;
    setDraft('');
    setNotice(null);
    setBusy(true);
    // Optimistic user turn.
    const temp: Turn = {
      id: -Date.now(), role: 'user', content: text, sources: [], question_id: null,
      created_at: new Date().toISOString(),
    };
    setTurns((t) => [...t, temp]);
    try {
      let id = activeId;
      if (id == null) {
        const created = await api.assistant.conversations.create();
        id = created.id;
        setActiveId(id);
        setConvos((cs) => [created, ...cs]);
      }
      const res = await api.assistant.conversations.send(id, text);
      setTurns((t) => [...t, res.message]);
      setUsage(res.usage);
      loadConvos(); // title + order may have changed
    } catch (e) {
      setTurns((t) => t.filter((x) => x.id !== temp.id)); // roll the optimistic turn back out
      setDraft(text);
      if (e instanceof ApiError && e.status === 402) {
        api.assistant.usage().then(setUsage).catch(() => {});
      }
      setNotice(e instanceof ApiError ? e.message : 'Something went wrong. Try again.');
    } finally {
      setBusy(false);
    }
  };

  const rate = async (idx: number, value: 1 | -1) => {
    const turn = turns[idx];
    if (!turn.question_id) return;
    const next: 1 | -1 | 0 = turn.rating === value ? 0 : value;
    setTurns((ts) => ts.map((t, i) => (i === idx ? { ...t, rating: next } : t)));
    try {
      await api.assistant.rate(turn.question_id, next);
    } catch {
      setTurns((ts) => ts.map((t, i) => (i === idx ? { ...t, rating: turn.rating } : t)));
    }
  };

  const uniqueSources = (sources: ChatSource[] = []) => {
    const seen = new Set<string>();
    return sources.filter((s) => (seen.has(s.slug) ? false : seen.add(s.slug)));
  };

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        title="AI Assistant"
        className="fixed bottom-5 right-5 z-40 flex items-center gap-2 border border-[#141414] bg-[#141414] px-4 py-2.5 font-mono text-xs font-bold uppercase text-[#E4E3E0] shadow-lg hover:bg-[#228B22] transition"
      >
        <Sparkles className="h-4 w-4" /> Ask AI
      </button>
    );
  }

  const activeTitle = convos.find((c) => c.id === activeId)?.title;

  return (
    <div className="fixed bottom-5 right-5 z-40 flex h-[32rem] max-h-[calc(100vh-2.5rem)] w-[min(24rem,calc(100vw-2.5rem))] flex-col border border-[#141414] bg-white shadow-2xl">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[#141414] bg-[#141414] px-3 py-2.5 text-[#E4E3E0]">
        <button
          onClick={() => setShowList((v) => !v)}
          title="Conversations"
          className="flex items-center gap-2 font-mono text-xs font-bold uppercase hover:text-white"
        >
          {showList ? <ChevronLeft className="h-4 w-4" /> : <MessagesSquare className="h-4 w-4" />}
          <span className="max-w-[9rem] truncate normal-case font-sans">
            {showList ? 'Chats' : activeTitle || 'New chat'}
          </span>
        </button>
        <div className="flex items-center gap-2">
          {usage && (
            <span
              title={usage.unlimited
                ? `${usage.tier === 'byo' ? 'Your own key' : 'Pro'} — unlimited`
                : `${usage.used} of ${usage.limit} free questions used this month`}
              className="flex items-center gap-1 font-mono text-[10px] uppercase text-[#E4E3E0]/70"
            >
              {usage.unlimited
                ? <><Zap className="h-3 w-3 text-[#228B22]" />{usage.tier === 'byo' ? 'Own key' : 'Pro'}</>
                : <>{usage.used}/{usage.limit}</>}
            </span>
          )}
          <button onClick={() => setOpen(false)} className="p-0.5 hover:text-[#B22222]">
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {showList ? (
        /* Conversation list */
        <div className="flex-1 overflow-y-auto">
          <button
            onClick={newChat}
            className="flex w-full items-center gap-2 border-b border-[#141414]/10 px-3 py-2.5 text-left text-xs font-bold text-[#141414] hover:bg-[#f4f4f2]"
          >
            <Plus className="h-4 w-4" /> New chat
          </button>
          {convos.length === 0 && (
            <p className="p-3 text-center text-xs text-[#141414]/45">No saved chats yet.</p>
          )}
          {convos.map((c) => (
            <div
              key={c.id}
              className={`group flex items-center gap-1 border-b border-[#141414]/8 px-3 py-2 text-xs ${
                c.id === activeId ? 'bg-[#EAF3FF]' : 'hover:bg-[#f4f4f2]'
              }`}
            >
              <button onClick={() => openConvo(c.id)} className="min-w-0 flex-1 truncate text-left">
                {c.title || 'Untitled chat'}
              </button>
              <button onClick={() => renameConvo(c)} title="Rename" className="p-0.5 text-[#141414]/30 hover:text-[#141414]">
                <Pencil className="h-3.5 w-3.5" />
              </button>
              <button onClick={() => deleteConvo(c)} title="Delete" className="p-0.5 text-[#141414]/30 hover:text-[#B22222]">
                <Trash2 className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
        </div>
      ) : (
        <>
          {/* Transcript */}
          <div ref={scroller} className="flex-1 space-y-3 overflow-y-auto p-3">
            {turns.length === 0 && !notice && (
              <div className="mt-6 text-center text-xs text-[#141414]/50">
                <Sparkles className="mx-auto mb-2 h-6 w-6 text-[#141414]/25" />
                Ask about your ISP — how the console works, your numbers, or help drafting a customer
                message. Answers are grounded in the docs.
              </div>
            )}
            {turns.map((m, i) => (
              <div key={m.id} className={m.role === 'user' ? 'text-right' : 'text-left'}>
                <span
                  className={`inline-block max-w-[85%] whitespace-pre-wrap px-3 py-2 text-xs leading-relaxed ${
                    m.role === 'user'
                      ? 'border border-[#141414] bg-[#141414] text-[#E4E3E0]'
                      : 'border border-[#141414]/15 bg-[#f4f4f2] text-[#141414]'
                  }`}
                >
                  {m.content}
                </span>

                {m.role === 'assistant' && (
                  <div className="mt-1.5 space-y-1.5">
                    {uniqueSources(m.sources).length > 0 && (
                      <div className="flex flex-wrap items-center gap-1">
                        <BookOpen className="h-3 w-3 text-[#141414]/40" />
                        {uniqueSources(m.sources).map((s) => (
                          <a
                            key={s.slug}
                            href={`${DOCS_BASE}/${s.slug}/`}
                            target="_blank"
                            rel="noreferrer"
                            title={s.heading ? `${s.title} — ${s.heading}` : s.title}
                            className="border border-[#141414]/15 bg-white px-1.5 py-0.5 text-[10px] text-[#141414]/70 hover:border-[#141414] hover:text-[#141414]"
                          >
                            {s.title}
                          </a>
                        ))}
                      </div>
                    )}
                    {m.question_id != null && (
                      <div className="flex items-center gap-1">
                        <button
                          onClick={() => rate(i, 1)}
                          title="Helpful"
                          className={`p-0.5 ${m.rating === 1 ? 'text-[#228B22]' : 'text-[#141414]/30 hover:text-[#141414]/70'}`}
                        >
                          <ThumbsUp className="h-3.5 w-3.5" />
                        </button>
                        <button
                          onClick={() => rate(i, -1)}
                          title="Not helpful"
                          className={`p-0.5 ${m.rating === -1 ? 'text-[#B22222]' : 'text-[#141414]/30 hover:text-[#141414]/70'}`}
                        >
                          <ThumbsDown className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))}
            {busy && (
              <div className="flex items-center gap-1.5 text-xs text-[#141414]/50">
                <Loader2 className="h-3.5 w-3.5 animate-spin" /> Thinking…
              </div>
            )}
            {notice && (
              <div className="border border-[#B26B00]/30 bg-[#FFF8EC] p-2.5 text-[11px] text-[#7a4a00]">
                <p>{notice}</p>
                <button
                  onClick={() => { window.location.hash = '#/settings/ai'; setOpen(false); }}
                  className="mt-1.5 inline-flex items-center gap-1 font-bold uppercase hover:underline"
                >
                  <Settings2 className="h-3 w-3" /> Open AI settings
                </button>
              </div>
            )}
          </div>

          {/* Composer */}
          <div className="flex items-end gap-2 border-t border-[#141414] p-2">
            <textarea
              rows={1}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              placeholder="Ask anything…"
              className="max-h-24 flex-1 resize-none border border-[#141414]/20 bg-white p-2 text-xs focus:border-[#141414] focus:outline-none"
            />
            <button
              onClick={send}
              disabled={busy || !draft.trim()}
              className="flex h-9 w-9 shrink-0 items-center justify-center border border-[#141414] bg-[#141414] text-[#E4E3E0] hover:bg-[#228B22] disabled:opacity-40 transition"
            >
              <Send className="h-4 w-4" />
            </button>
          </div>
        </>
      )}
    </div>
  );
}
