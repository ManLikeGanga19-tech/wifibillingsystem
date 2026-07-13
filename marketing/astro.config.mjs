// @ts-check
import react from '@astrojs/react';
import tailwind from '@tailwindcss/vite';
import { defineConfig } from 'astro/config';

/**
 * The marketing site: static pages, one interactive island (the signup wizard).
 *
 * Astro, not another SPA, because this is the page a stranger loads on a Kenyan
 * mobile network before they trust us with their business. It ships zero JavaScript
 * except where we ask for it, so the hero is readable long before any bundle lands.
 *
 * The API is PROXIED, not called cross-origin. The signup draft lives in an httpOnly
 * cookie (no browser storage — the hard rule of this system), and a same-origin proxy
 * is what lets the browser attach it without CORS credentials, a preflight on every
 * step, and a second copy of the trusted-origins list to keep in sync.
 */
export default defineConfig({
  site: 'https://wifios.co.ke',
  integrations: [react()],
  vite: {
    plugins: [tailwind()],
    server: {
      // Dev server only: allow the compose service hostname so the site is reachable at
      // http://marketing:4900 on the docker network. Astro's bundled Vite wants an
      // explicit list here (it ignores `true`).
      allowedHosts: ['marketing', 'localhost', '127.0.0.1'],
      proxy: {
        '/api': {
          target: process.env.API_ORIGIN ?? 'http://localhost:8000',
          changeOrigin: true,
        },
      },
    },
  },
});
