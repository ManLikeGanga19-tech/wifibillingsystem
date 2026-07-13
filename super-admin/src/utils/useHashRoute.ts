import { useCallback, useEffect, useState } from 'react';

/**
 * Where you are, kept in the URL — so a refresh lands you back on the page you were on
 * instead of dumping you at the dashboard, and Back/Forward do what a browser is
 * supposed to do.
 *
 * The URL, not storage. That is the rule for this system (nothing about a session lives
 * in the browser), and it happens to be the right call anyway: a page you can link to,
 * bookmark and send to a colleague is worth more than one only your own tab remembers.
 *
 * Shape: `#/<section>` or `#/<section>/<subsection>` — e.g. `#/settings/branding`.
 * The hash (not a real path) keeps this working on any static host without needing an
 * SPA rewrite rule in front of it.
 */

export interface Route {
  section: string;
  sub?: string;
}

function parse(fallback: string): Route {
  const raw = window.location.hash.replace(/^#\/?/, '');
  const [section, sub] = raw.split('/').filter(Boolean);
  return { section: section || fallback, sub };
}

export function useHashRoute(fallback: string) {
  const [route, setRoute] = useState<Route>(() => parse(fallback));

  useEffect(() => {
    const onChange = () => setRoute(parse(fallback));
    window.addEventListener('hashchange', onChange);
    return () => window.removeEventListener('hashchange', onChange);
  }, [fallback]);

  const navigate = useCallback((section: string, sub?: string) => {
    const next = sub ? `#/${section}/${sub}` : `#/${section}`;
    if (window.location.hash === next) {
      // Same URL: no hashchange event will fire, so settle the state ourselves.
      setRoute({ section, sub });
      return;
    }
    window.location.hash = next;
  }, []);

  return { route, navigate };
}
