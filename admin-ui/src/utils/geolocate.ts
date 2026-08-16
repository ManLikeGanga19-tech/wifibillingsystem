/**
 * Robust device geolocation. The naive `getCurrentPosition(..., { enableHighAccuracy: true })`
 * fails constantly in the field: high-accuracy GPS TIMES OUT on a desktop (no GPS chip) or a
 * phone indoors, firing the error callback even after the user approved the prompt.
 *
 * So: try a quick high-accuracy fix first, and if it times out or the position is unavailable,
 * fall back to a coarse network/wifi fix (fast and almost always succeeds). A recent cached
 * position (maximumAge) is accepted so repeated taps are instant. Returns a clear, specific
 * message on failure instead of one catch-all.
 */
export type Coords = { lat: number; lng: number; accuracy: number };

const HIGH: PositionOptions = { enableHighAccuracy: true, timeout: 8000, maximumAge: 30000 };
const COARSE: PositionOptions = { enableHighAccuracy: false, timeout: 15000, maximumAge: 120000 };

function once(opts: PositionOptions): Promise<GeolocationPosition> {
  return new Promise((resolve, reject) =>
    navigator.geolocation.getCurrentPosition(resolve, reject, opts));
}

function reason(err: unknown): string {
  const code = (err as GeolocationPositionError | undefined)?.code;
  if (code === 1) return 'Location access was blocked — allow it for this site, or click the map.';
  if (code === 2) return "Your device couldn't get a location fix — check that GPS/location is on, or click the map.";
  if (code === 3) return 'Getting your location timed out — try again outdoors, or click the map.';
  return 'Could not get your location — allow location access, or click the map.';
}

export async function getPosition(): Promise<Coords> {
  if (!navigator.geolocation) throw new Error('This device has no location service.');
  try {
    const p = await once(HIGH);
    return { lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy };
  } catch (highErr) {
    // Timeout (3) or unavailable (2) → the fast coarse path usually still works. A hard
    // permission denial (1) won't, so surface that immediately rather than retrying.
    if ((highErr as GeolocationPositionError)?.code === 1) throw new Error(reason(highErr));
    try {
      const p = await once(COARSE);
      return { lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy };
    } catch (coarseErr) {
      throw new Error(reason(coarseErr));
    }
  }
}
