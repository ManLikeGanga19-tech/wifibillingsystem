import { useEffect, useRef, useState } from 'react';
import { Sparkles, X, Send, Loader2, Settings2 } from 'lucide-react';
import { api, ApiError, ChatMessage } from '../api/client';

/**
 * The floating AI Chat assistant for the ISP dashboard. A button bottom-right opens a chat panel
 * that talks to /assistant/chat/. If the assistant isn't configured (no ISP key and no platform
 * default) the panel says so and links to Settings > AI Assistant, rather than failing silently.
 */
export default function AssistantWidget() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight });
  }, [messages, busy]);

  const send = async () => {
    const text = draft.trim();
    if (!text || busy) return;
    const next: ChatMessage[] = [...messages, { role: 'user', content: text }];
    setMessages(next);
    setDraft('');
    setNotice(null);
    setBusy(true);
    try {
      const { reply } = await api.assistant.chat(next);
      setMessages([...next, { role: 'assistant', content: reply }]);
    } catch (e) {
      // Roll the unanswered question back out and explain, rather than leaving a dangling turn.
      setMessages(next.slice(0, -1));
      setDraft(text);
      if (e instanceof ApiError && (e.status === 503 || e.status === 502)) {
        setNotice(e.message);
      } else {
        setNotice(e instanceof ApiError ? e.message : 'Something went wrong. Try again.');
      }
    } finally {
      setBusy(false);
    }
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

  return (
    <div className="fixed bottom-5 right-5 z-40 flex h-[32rem] max-h-[calc(100vh-2.5rem)] w-[min(24rem,calc(100vw-2.5rem))] flex-col border border-[#141414] bg-white shadow-2xl">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-[#141414] bg-[#141414] px-3 py-2.5 text-[#E4E3E0]">
        <span className="flex items-center gap-2 font-mono text-xs font-bold uppercase">
          <Sparkles className="h-4 w-4" /> AI Assistant
        </span>
        <button onClick={() => setOpen(false)} className="p-0.5 hover:text-[#B22222]">
          <X className="h-4 w-4" />
        </button>
      </div>

      {/* Transcript */}
      <div ref={scroller} className="flex-1 space-y-3 overflow-y-auto p-3">
        {messages.length === 0 && !notice && (
          <div className="mt-6 text-center text-xs text-[#141414]/50">
            <Sparkles className="mx-auto mb-2 h-6 w-6 text-[#141414]/25" />
            Ask about your ISP — how the console works, your numbers, or help drafting a customer
            message.
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={m.role === 'user' ? 'text-right' : 'text-left'}>
            <span
              className={`inline-block max-w-[85%] whitespace-pre-wrap px-3 py-2 text-xs leading-relaxed ${
                m.role === 'user'
                  ? 'border border-[#141414] bg-[#141414] text-[#E4E3E0]'
                  : 'border border-[#141414]/15 bg-[#f4f4f2] text-[#141414]'
              }`}
            >
              {m.content}
            </span>
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
              onClick={() => {
                window.location.hash = '#/settings/ai';
                setOpen(false);
              }}
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
    </div>
  );
}
