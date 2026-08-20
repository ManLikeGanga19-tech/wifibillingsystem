import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';
import { VitePWA } from 'vite-plugin-pwa';

// The API target differs by where the dev server runs: the host reaches Django at
// localhost:8000; a Docker container reaches it at http://api:8000 (the compose service
// name). API_PROXY_TARGET lets one config serve both.
const API = process.env.API_PROXY_TARGET ?? 'http://localhost:8000';

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    // Installable PWA — Platform Control as its own app (distinct icon from the ISP consoles).
    // autoUpdate + shell-only precache; /api is never cached.
    VitePWA({
      registerType: 'autoUpdate',
      injectRegister: 'auto',
      includeAssets: ['icons/favicon-32.png', 'icons/favicon-48.png', 'icons/apple-touch-icon.png'],
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,png,woff2}'],
        navigateFallbackDenylist: [/^\/api/],
        cleanupOutdatedCaches: true,
        clientsClaim: true,
      },
      manifest: {
        name: 'WIFI.OS — Platform Control',
        short_name: 'Platform',
        description: 'Danamo Tech platform control — tenants, finance, audit across all ISPs.',
        theme_color: '#141414',
        background_color: '#141414',
        display: 'standalone',
        start_url: '/',
        scope: '/',
        icons: [
          { src: 'icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: 'icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: 'icons/icon-maskable-192.png', sizes: '192x192', type: 'image/png', purpose: 'maskable' },
          { src: 'icons/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
    }),
  ],
  build: {
    // Split the heavy vendor libraries (charts especially) out of the app bundle so no
    // single chunk is oversized and the framework/chart code caches independently. A
    // function (not the object form) so deep imports land in the right vendor chunk.
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (!id.includes('node_modules')) return undefined;
          if (id.includes('recharts') || id.includes('d3-') || id.includes('victory'))
            return 'charts';
          if (id.includes('lucide-react')) return 'icons';
          if (/[/\\](react|react-dom|scheduler)[/\\]/.test(id)) return 'react-vendor';
          return 'vendor';
        },
      },
    },
  },
  server: {
    host: true, // reachable from outside the container when dockerised
    allowedHosts: true as const, // dev server: allow the docker service hostnames
    proxy: { '/api': API },
  },
});
