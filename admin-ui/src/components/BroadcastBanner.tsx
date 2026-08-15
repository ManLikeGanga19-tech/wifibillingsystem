import { useEffect, useState } from 'react';
import { AlertTriangle, Info, Megaphone, X } from 'lucide-react';
import { api, type Broadcast } from '../api/client';

/**
 * Platform broadcasts — Danamo speaking to every ISP at once (a maintenance window, a price
 * change, an outage). Self-contained: it asks the server what's live and not-yet-dismissed
 * for this user, and clears one when they wave it away. Renders nothing in the common case of
 * no notices, so a quiet platform costs the console nothing.
 */
export default function BroadcastBanner() {
  const [items, setItems] = useState<Broadcast[]>([]);

  useEffect(() => {
    let alive = true;
    api
      .activeBroadcasts()
      .then((b) => alive && setItems(b))
      .catch(() => {}); // a notice board must never break the console
    return () => {
      alive = false;
    };
  }, []);

  const dismiss = async (b: Broadcast) => {
    setItems((cur) => cur.filter((x) => x.id !== b.id)); // optimistic — it's only a banner
    try {
      await api.dismissBroadcast(b.id);
    } catch {
      /* the server is the source of truth; a failed dismiss just reappears next load */
    }
  };

  if (items.length === 0) return null;

  return (
    <div className="space-y-2">
      {items.map((b) => {
        const s = STYLE[b.level];
        return (
          <div key={b.id} className={`flex flex-wrap items-start gap-3 border p-3.5 ${s.tone}`}>
            <span className="shrink-0 mt-0.5 flex items-center gap-1.5">
              <Megaphone className="h-4 w-4 opacity-60" />
              {s.icon}
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-bold">{b.title}</p>
              <p className="text-xs leading-relaxed opacity-80 whitespace-pre-wrap">{b.body}</p>
            </div>
            {b.dismissable && (
              <button
                onClick={() => dismiss(b)}
                title="Dismiss"
                className="shrink-0 p-1 opacity-60 hover:opacity-100 cursor-pointer"
              >
                <X className="h-4 w-4" />
              </button>
            )}
          </div>
        );
      })}
    </div>
  );
}

const STYLE = {
  info: { tone: 'border-[#141414]/25 bg-[#f4f3f0] text-[#141414]', icon: <Info className="h-4 w-4" /> },
  warning: { tone: 'border-[#B26B00]/50 bg-[#B26B00]/5 text-[#B26B00]', icon: <AlertTriangle className="h-4 w-4" /> },
  critical: { tone: 'border-[#B22222] bg-[#B22222]/10 text-[#B22222]', icon: <AlertTriangle className="h-4 w-4" /> },
} as const;
