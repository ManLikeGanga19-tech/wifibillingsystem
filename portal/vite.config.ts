import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const API = process.env.API_PROXY_TARGET ?? 'http://localhost:8000';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: true,
    allowedHosts: true as const, // dev server: allow the docker service hostnames
    proxy: { '/api': API },
  },
});
