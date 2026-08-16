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

const HIGH: PositionOptions = { enableHighAccuracy: true, timeout: 8000, maximumAge: 30000 };
const COARSE: PositionOptions = { enableHighAccuracy: false, timeout: 15000, maximumAge: 120000 };

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
  if (code === 3) return 'Getting your location timed out — try again outdoors, or click the map.';
  return 'Could not get your location — allow location access, or click the map.';
}

export async function getPosition(): Promise<Coords> {
  if (!window.isSecureContext) {
    throw new Error('Location only works over HTTPS — open the site with https://, not http://.');
  }
  if (!navigator.geolocation) throw new Error('This device has no location service.');
  if (policyBlocksGeolocation()) {
    throw new Error('Location is disabled for this site by its security policy (a server setting). Click the map to place the pin instead.');
  }
  try {
    const p = await once(HIGH);
    return { lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy };
  } catch (highErr) {
    // A hard permission denial (1) won't be fixed by retrying; a timeout (3) or unavailable (2)
    // usually still works on the fast coarse path.
    if ((highErr as GeolocationPositionError)?.code === 1) throw new Error(reason(highErr));
    try {
      const p = await once(COARSE);
      return { lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy };
    } catch (coarseErr) {
      throw new Error(reason(coarseErr));
    }
  }
}
