import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import {defineConfig} from 'vite';

export default defineConfig(() => {
  return {
    plugins: [react(), tailwindcss()],
    // maplibre-gl ships its own web worker; Vite's dep pre-bundler mishandles it
    // ("maplibre-gl-worker.mjs does not exist"), so serve it un-bundled. It's already ESM.
    optimizeDeps: { exclude: ['maplibre-gl'] },
    // maplibre creates its worker with { type: 'module' }; build workers as ES modules so the
    // format matches (a classic/IIFE worker loaded as a module silently does nothing).
    worker: { format: 'es' },
    build: {
      // Split the vendor libraries out of the app bundle so no single chunk is oversized
      // and the rarely-changing framework code caches independently of our app code. A
      // function (not the object form) so deep imports like `react-dom/client` land in the
      // framework chunk too, instead of leaking back into the app bundle.
      rollupOptions: {
        output: {
          manualChunks(id: string) {
            if (!id.includes('node_modules')) return undefined;
            if (id.includes('lucide-react')) return 'icons';
            if (/[/\\](react|react-dom|scheduler)[/\\]/.test(id)) return 'react-vendor';
            return 'vendor';
          },
        },
      },
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, '.'),
      },
    },
    server: {
      // HMR is disabled in AI Studio via DISABLE_HMR env var.
      // Do not modifyâfile watching is disabled to prevent flickering during agent edits.
      hmr: process.env.DISABLE_HMR !== 'true',
      // Disable file watching when DISABLE_HMR is true to save CPU during agent edits.
      watch: process.env.DISABLE_HMR === 'true' ? null : {},
      host: true, // reachable from outside the container when dockerised
      // Dev server only (never prod): accept the compose service hostnames too, so the
      // app is reachable at http://admin-ui:4600 etc. on the docker network.
      allowedHosts: true as const,
      // localhost:8000 on the host, http://api:8000 inside Docker (compose service name)
      proxy: {
        '/api': process.env.API_PROXY_TARGET ?? 'http://localhost:8000',
      },
    },
    // `vite preview` (production build) needs the same /api proxy for local prod-parity testing.
    preview: {
      proxy: { '/api': process.env.API_PROXY_TARGET ?? 'http://localhost:8000' },
    },
  };
});
