import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// PWA scaffolding (F4): plugin intentionally NOT installed in v1.
// To enable: `npm i -D vite-plugin-pwa workbox-window`, then import and add to plugins below.

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env['VITE_API_URL'] ?? 'http://localhost:8000',
        changeOrigin: true,
        secure: false,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: true,
    target: 'es2022',
  },
});
