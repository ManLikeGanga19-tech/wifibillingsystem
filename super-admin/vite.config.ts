import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    // Dev-only: forward API calls to the Docker backend (no CORS setup needed)
    proxy: { '/api': 'http://localhost:8000' },
  },
});
