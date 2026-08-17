import { useEffect, useRef, useState } from 'react';
import { MapPin, MapPinOff } from 'lucide-react';
import { api } from '../api/client';

// Only report when the tech has actually moved, and no faster than this — light on battery and on
// the server. A stationary tech still refreshes occasionally so they don't fall to "stale".
const MIN_INTERVAL_MS = 45_000;
const MOVED_METRES = 25;
const HEARTBEAT_MS = 4 * 60_000;   // even stationary, ping this often to stay "live"

function metresBetween(a: { lat: number; lng: number }, b: { lat: number; lng: number }): number {
  const R = 6371_000;
  const p1 = (a.lat * Math.PI) / 180, p2 = (b.lat * Math.PI) / 180;
  const dphi = ((b.lat - a.lat) * Math.PI) / 180, dl = ((b.lng - a.lng) * Math.PI) / 180;
  const h = Math.sin(dphi / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

type State = 'starting' | 'sharing' | 'denied' | 'unsupported';

/**
 * The technician side of fleet tracking: while `active` (the signed-in user is a field technician),
 * the device streams its position to the server — throttled, paused when backgrounded, and ALWAYS
 * with a visible indicator so a tech is never tracked silently. Renders the indicator strip; the
 * sharing itself is the effect. `active=false` renders nothing and shares nothing.
 */
export default function LocationSharing({ active }: { active: boolean }) {
  const [state, setState] = useState<State>('starting');
  const lastPing = useRef(0);
  const lastPos = useRef<{ lat: number; lng: number } | null>(null);

  useEffect(() => {
    if (!active) return;
    if (!window.isSecureContext || !navigator.geolocation) { setState('unsupported'); return; }

    let watchId: number | null = null;
    const send = (lat: number, lng: number, accuracy?: number, heading?: number | null) => {
      api.fleet.ping({
        lat: lat.toFixed(6), lng: lng.toFixed(6),
        accuracy: accuracy != null ? Math.round(accuracy) : undefined,
        heading: heading != null && !Number.isNaN(heading) ? Math.round(heading) : undefined,
      }).catch(() => {});
    };

    const onFix = (pos: GeolocationPosition) => {
      setState('sharing');
      const { latitude: lat, longitude: lng, accuracy, heading } = pos.coords;
      const now = Date.now();
      const here = { lat, lng };
      const moved = !lastPos.current || metresBetween(lastPos.current, here) >= MOVED_METRES;
      const due = now - lastPing.current >= MIN_INTERVAL_MS;
      const heartbeat = now - lastPing.current >= HEARTBEAT_MS;
      if (!heartbeat && !(moved && due)) return;   // throttle: only on real movement, or the heartbeat
      lastPing.current = now;
      lastPos.current = here;
      send(lat, lng, accuracy, heading);
    };
    const onErr = (err: GeolocationPositionError) => { if (err.code === 1) setState('denied'); };

    const startWatch = () => {
      if (watchId != null) return;
      watchId = navigator.geolocation.watchPosition(onFix, onErr, {
        enableHighAccuracy: true, maximumAge: 30_000, timeout: 30_000,
      });
    };
    const stopWatch = () => { if (watchId != null) { navigator.geolocation.clearWatch(watchId); watchId = null; } };

    // Pause while the app is backgrounded (screen off / tab hidden) — saves battery, resumes on return.
    const onVisibility = () => { if (document.hidden) stopWatch(); else startWatch(); };
    if (!document.hidden) startWatch();
    document.addEventListener('visibilitychange', onVisibility);

    return () => { stopWatch(); document.removeEventListener('visibilitychange', onVisibility); };
  }, [active]);

  if (!active) return null;

  if (state === 'denied') {
    return (
      <div className="bg-[#B26B00] text-white px-4 py-1.5 text-[11px] font-mono flex items-center gap-2 shrink-0">
        <MapPinOff className="h-3.5 w-3.5 shrink-0" />
        Location is off, so you won't appear on dispatch — open the padlock ▸ Site settings ▸ Location ▸ Allow, then reload.
      </div>
    );
  }
  if (state === 'unsupported') {
    return (
      <div className="bg-[#B26B00] text-white px-4 py-1.5 text-[11px] font-mono flex items-center gap-2 shrink-0">
        <MapPinOff className="h-3.5 w-3.5 shrink-0" />
        Location sharing needs HTTPS — you won't appear on dispatch on this connection.
      </div>
    );
  }
  return (
    <div className="bg-[#065f46] text-white px-4 py-1.5 text-[11px] font-mono flex items-center gap-2 shrink-0">
      <span className="relative flex h-2.5 w-2.5 shrink-0">
        <span className="absolute inline-flex h-full w-full rounded-full bg-white/70 animate-ping" />
        <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-white" />
      </span>
      <MapPin className="h-3.5 w-3.5 shrink-0" />
      {state === 'sharing' ? 'Sharing your location with dispatch while you’re signed in.' : 'Starting location sharing…'}
    </div>
  );
}
