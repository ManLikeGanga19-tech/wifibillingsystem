import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// The API target differs by where the dev server runs: the host reaches Django at
// localhost:8000; a Docker container reaches it at http://api:8000 (the compose service
// name). API_PROXY_TARGET lets one config serve both.
const API = process.env.API_PROXY_TARGET ?? 'http://localhost:8000';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true, // reachable from outside the container when dockerised
    proxy: { '/api': API },
  },
});
