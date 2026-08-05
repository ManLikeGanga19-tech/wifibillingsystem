import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// The API target differs by where the dev server runs: the host reaches Django at
// localhost:8000; a Docker container reaches it at http://api:8000 (the compose service
// name). API_PROXY_TARGET lets one config serve both.
const API = process.env.API_PROXY_TARGET ?? 'http://localhost:8000';

export default defineConfig({
  plugins: [react(), tailwindcss()],
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
