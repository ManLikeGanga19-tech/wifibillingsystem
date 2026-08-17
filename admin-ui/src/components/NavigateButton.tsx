import { useEffect, useRef, useState } from 'react';
import { Navigation } from 'lucide-react';
import { navLinks, NAV_APPS } from '../utils/nav';

/**
 * "Navigate" — hands a coordinate off to the technician's phone maps app. A small chooser (Google /
 * Apple / Waze / OSM) because field techs carry different phones. Each choice opens in the maps app
 * on a phone, or a new tab on desktop. Compact by default so it fits in a table row.
 */
export default function NavigateButton({
  lat, lng, label, compact = false,
}: {
  lat: number | null | undefined;
  lng: number | null | undefined;
  label?: string;
  compact?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);

  if (lat == null || lng == null) return null;   // nothing to navigate to
  const links = navLinks(Number(lat), Number(lng), label);

  return (
    <div ref={ref} className="relative inline-block">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title="Navigate here"
        className={`inline-flex items-center gap-1.5 border border-[#141414]/30 hover:bg-[#141414] hover:text-white cursor-pointer font-mono uppercase ${compact ? 'p-1.5' : 'px-2.5 py-1.5 text-[11px] font-bold'}`}
      >
        <Navigation className="h-3.5 w-3.5" />{!compact && 'Navigate'}
      </button>
      {open && (
        <div className="absolute right-0 z-30 mt-1 w-40 bg-white border border-[#141414] shadow-md">
          <div className="px-2.5 py-1.5 text-[10px] font-mono uppercase tracking-wider text-[#141414]/40 border-b border-[#141414]/10">Open in…</div>
          {NAV_APPS.map((app) => (
            <a
              key={app.key}
              href={links[app.key]}
              target="_blank"
              rel="noreferrer"
              onClick={() => setOpen(false)}
              className="block px-2.5 py-2 text-xs hover:bg-[#f0efec] cursor-pointer"
            >
              {app.label}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
