/**
 * Robust device geolocation with a PRECISE failure reason. The naive
 * `getCurrentPosition(..., { enableHighAccuracy: true })` both fails constantly (high-accuracy
 * GPS times out on a desktop or indoors) AND hides *why* it failed behind one generic message —
 * so a blocked-by-policy problem looks identical to a user denial, and you chase the wrong layer.
 *
 * So this: (1) checks the things that make geolocation impossible regardless of the device — a
 * non-secure context, and a Permissions-Policy that disables the feature — and reports each
 * distinctly; (2) tries a quick high-accuracy fix, falling back to a coarse network fix; and
 * (3) maps the browser's error codes to specific, actionable messages.
 */
export type Coords = { lat: number; lng: number; accuracy: number };

// Two attempts, run in PARALLEL, first success wins (see getPosition). The coarse network fix
// usually returns in a second or two; the high-accuracy GPS fix is slower but more precise, so
// whichever the device can deliver first is used. Both are patient (a cold GPS can take a
// while) and accept a recent cached position so repeat taps are instant.
const HIGH: PositionOptions = { enableHighAccuracy: true, timeout: 20000, maximumAge: 60000 };
const COARSE: PositionOptions = { enableHighAccuracy: false, timeout: 20000, maximumAge: 600000 };

function once(opts: PositionOptions): Promise<GeolocationPosition> {
  return new Promise((resolve, reject) =>
    navigator.geolocation.getCurrentPosition(resolve, reject, opts));
}

/** True when the page's Permissions-Policy DISABLES geolocation (the server/CSP layer), as
 *  opposed to the user's own allow/block choice. Uses the (Chromium) featurePolicy reader when
 *  present; returns false ("not policy-blocked") when it can't tell, so we don't misreport. */
export function policyBlocksGeolocation(): boolean {
  const fp = (document as unknown as { featurePolicy?: { allowsFeature(n: string): boolean } }).featurePolicy;
  try {
    return fp ? fp.allowsFeature('geolocation') === false : false;
  } catch {
    return false;
  }
}

function reason(err: unknown): string {
  const code = (err as GeolocationPositionError | undefined)?.code;
  if (code === 1) {
    // Distinguish "the site is allowed to ask, but you blocked it" from "the site itself is
    // forbidden from asking" — completely different fixes.
    return policyBlocksGeolocation()
      ? 'Location is disabled for this site by its security policy (a server setting), so the browser never asks. Click the map to place the pin instead.'
      : "Location is blocked for this site — open the padlock ▸ Site settings ▸ Location and set it to Allow, then reload. (Turning on the device's location isn't enough; the site permission is separate.)";
  }
  if (code === 2) return "Your device couldn't get a location fix — check that GPS/location is on, or click the map.";
  if (code === 3) return "Couldn't get a location fix in time (common on desktops or indoors) — click the map to place the pin, or try on a phone outdoors.";
  return 'Could not get your location — allow location access, or click the map.';
}

/**
 * Live-follow the device position (the map's "you are here" blue dot). Uses watchPosition with
 * high accuracy so the dot tracks movement, but the FIRST fix comes from getPosition()'s
 * coarse+precise race so the dot appears fast instead of waiting on a cold GPS lock. Returns a
 * stop() to clear the watch. Errors are reported via onError with the same actionable messages.
 */
export function watchPosition(
  onFix: (c: Coords) => void,
  onError: (msg: string) => void,
): () => void {
  let stopped = false;
  let watchId: number | null = null;

  // Fast first fix (may be coarse) so the dot shows immediately.
  getPosition().then((c) => { if (!stopped) onFix(c); }).catch((e) => {
    if (!stopped) onError(e instanceof Error ? e.message : 'Could not get your location.');
  });

  if (navigator.geolocation) {
    watchId = navigator.geolocation.watchPosition(
      (p) => { if (!stopped) onFix({ lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy }); },
      (e) => { if (!stopped) onError(reason(e)); },
      HIGH,
    );
  }
  return () => {
    stopped = true;
    if (watchId != null) navigator.geolocation.clearWatch(watchId);
  };
}

export async function getPosition(): Promise<Coords> {
  if (!window.isSecureContext) {
    throw new Error('Location only works over HTTPS — open the site with https://, not http://.');
  }
  if (!navigator.geolocation) throw new Error('This device has no location service.');
  if (policyBlocksGeolocation()) {
    throw new Error('Location is disabled for this site by its security policy (a server setting). Click the map to place the pin instead.');
  }
  // Race a coarse (fast, network) and a precise (slower, GPS) fix — take whichever the device
  // can deliver first, so a phone gets GPS precision while a desktop still gets *a* location
  // quickly instead of both timing out one after the other.
  try {
    const p = await Promise.any([once(COARSE), once(HIGH)]);
    return { lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy };
  } catch (agg) {
    const errs = (agg as { errors?: GeolocationPositionError[] }).errors;
    // Report the most actionable failure: denied (1) > unavailable (2) > timeout (3).
    const best = (errs ?? []).slice().sort((a, b) => (a?.code ?? 9) - (b?.code ?? 9))[0];
    throw new Error(reason(best ?? agg));
  }
}
