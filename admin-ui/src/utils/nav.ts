/**
 * Phone hand-off: turn a coordinate into deep links that open the technician's OWN maps app for
 * turn-by-turn navigation. Techs carry different phones, so we offer a chooser rather than assume
 * one app. All are plain https links except `geo:` (Android's native "let the OS pick" scheme),
 * so they work from any browser and open the installed app on a phone.
 */
export interface NavLinks {
  google: string;
  apple: string;
  waze: string;
  osm: string;
  geo: string;
}

export function navLinks(lat: number, lng: number, label?: string): NavLinks {
  const q = `${lat},${lng}`;
  const name = label ? encodeURIComponent(label) : '';
  return {
    // Universal — opens the Google Maps app on Android/iOS, the website on desktop.
    google: `https://www.google.com/maps/dir/?api=1&destination=${q}`,
    apple: `https://maps.apple.com/?daddr=${q}${name ? `&q=${name}` : ''}`,
    waze: `https://waze.com/ul?ll=${q}&navigate=yes`,
    osm: `https://www.openstreetmap.org/directions?to=${q}#map=17/${lat}/${lng}`,
    // Android intent — the OS shows its own app chooser (Maps, Waze, Organic Maps…).
    geo: `geo:${q}?q=${q}${label ? `(${label})` : ''}`,
  };
}

export interface NavApp {
  key: keyof NavLinks;
  label: string;
}
/** The apps the chooser offers, in order. `geo` is intentionally excluded from the UI list — it's
 *  available on the type for callers who want the raw Android intent. */
export const NAV_APPS: NavApp[] = [
  { key: 'google', label: 'Google Maps' },
  { key: 'apple', label: 'Apple Maps' },
  { key: 'waze', label: 'Waze' },
  { key: 'osm', label: 'OpenStreetMap' },
];
