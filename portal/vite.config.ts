import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Dev-only: forward API calls to the Docker backend so the portal needs no CORS setup
    proxy: {
      '/api': 'http://localhost:8000',
    },
  },
});
