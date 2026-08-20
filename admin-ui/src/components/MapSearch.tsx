import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react';
import { Search, X, Loader2, MapPin } from 'lucide-react';
import { api, type GeoResult } from '../api/client';

/**
 * Google/Apple-style place search for the map. Type a place, get live suggestions ranked toward
 * the current viewport, pick one (mouse or keyboard) to fly there. Purely presentational about
 * the map itself — it emits the picked place; the parent owns the flyTo + marker.
 *
 * `getCenter` lets us bias results toward wherever the map is looking right now, exactly the way
 * Google surfaces nearby places first — read lazily on each keystroke so it always reflects the
 * latest pan/zoom.
 */
export default function MapSearch({
  getCenter,
  onPick,
}: {
  getCenter: () => { lat: number; lng: number } | null;
  onPick: (r: GeoResult) => void;
}) {
  const [q, setQ] = useState('');
  const [results, setResults] = useState<GeoResult[]>([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [active, setActive] = useState(-1); // keyboard-highlighted row
  const boxRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  // getCenter is a fresh closure each parent render; keep it in a ref so the search effect
  // depends only on the typed query, never on the parent's re-render cadence (fleet polling etc.).
  const getCenterRef = useRef(getCenter);
  getCenterRef.current = getCenter;

  // Debounced live search: one request per ~250ms of quiet typing, and the previous in-flight
  // request is aborted so a slow response for "nai" can't overwrite a newer one for "nairobi".
  useEffect(() => {
    const term = q.trim();
    if (term.length < 2) {
      setResults([]);
      setBusy(false);
      abortRef.current?.abort();
      return;
    }
    setBusy(true);
    const t = setTimeout(() => {
      abortRef.current?.abort();
      const ctrl = new AbortController();
      abortRef.current = ctrl;
      const c = getCenterRef.current();
      api.map
        .search(term, c?.lat, c?.lng, ctrl.signal)
        .then((r) => {
          setResults(r.results);
          setActive(r.results.length ? 0 : -1);
          setOpen(true);
        })
        .catch((e) => {
          if (e?.name === 'AbortError') return; // superseded by a newer keystroke
          setResults([]);
        })
        .finally(() => {
          if (abortRef.current === ctrl) setBusy(false);
        });
    }, 250);
    return () => clearTimeout(t);
  }, [q]);

  // Close the dropdown on an outside click.
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (boxRef.current && !boxRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, []);

  const choose = (r: GeoResult) => {
    onPick(r);
    setQ(r.label);
    setOpen(false);
    setResults([]);
  };

  const clear = () => {
    setQ('');
    setResults([]);
    setOpen(false);
    abortRef.current?.abort();
  };

  const onKey = (e: KeyboardEvent) => {
    if (!open || !results.length) {
      if (e.key === 'Escape') clear();
      return;
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setActive((i) => (i + 1) % results.length);
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setActive((i) => (i - 1 + results.length) % results.length);
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (results[active]) choose(results[active]);
    } else if (e.key === 'Escape') {
      setOpen(false);
    }
  };

  const showDrop = useMemo(() => open && (busy || results.length > 0), [open, busy, results]);

  return (
    <div ref={boxRef} className="w-[min(380px,calc(100vw-2.5rem))]">
      <div className="flex items-center gap-2 bg-white border border-[#141414] px-3 py-2 shadow-sm">
        {busy ? (
          <Loader2 className="h-4 w-4 shrink-0 animate-spin text-[#141414]/60" />
        ) : (
          <Search className="h-4 w-4 shrink-0 text-[#141414]/60" />
        )}
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onFocus={() => results.length && setOpen(true)}
          onKeyDown={onKey}
          placeholder="Search a place or address…"
          className="flex-1 min-w-0 bg-transparent text-sm outline-none placeholder:text-[#141414]/40"
          aria-label="Search the map for a place or address"
          autoComplete="off"
          spellCheck={false}
        />
        {q && (
          <button
            onClick={clear}
            className="shrink-0 text-[#141414]/40 hover:text-[#141414] cursor-pointer"
            title="Clear"
            aria-label="Clear search"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>

      {showDrop && (
        <div className="mt-1 bg-white border border-[#141414] shadow-md max-h-[46vh] overflow-y-auto">
          {results.length === 0 && busy && (
            <div className="px-3 py-2.5 text-xs text-[#141414]/50 flex items-center gap-2">
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Searching…
            </div>
          )}
          {results.length === 0 && !busy && (
            <div className="px-3 py-2.5 text-xs text-[#141414]/50">No places found.</div>
          )}
          {results.map((r, i) => (
            <button
              key={`${r.lat},${r.lng},${i}`}
              onClick={() => choose(r)}
              onMouseEnter={() => setActive(i)}
              className={`w-full text-left px-3 py-2 flex items-start gap-2.5 cursor-pointer border-b border-[#141414]/8 last:border-b-0 ${
                i === active ? 'bg-[#EAF3FF]' : 'hover:bg-[#F5F7FA]'
              }`}
            >
              <MapPin className="h-4 w-4 mt-0.5 shrink-0 text-[#2563EB]" />
              <span className="min-w-0">
                <span className="block text-sm text-[#141414] truncate">{r.label}</span>
                {r.secondary && (
                  <span className="block text-xs text-[#141414]/50 truncate">{r.secondary}</span>
                )}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
