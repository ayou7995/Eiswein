import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';

// PWA scaffolding (F4): plugin intentionally NOT installed in v1.
// To enable: `npm i -D vite-plugin-pwa workbox-window`, then import and add to plugins below.

// Dev-only middleware that 301-redirects requests on `localhost:5173` to
// `127.0.0.1:5173`. Schwab OAuth has its redirect URI registered as
// `https://127.0.0.1:8000/api/v1/broker/schwab/callback` — browsers treat
// `localhost` and `127.0.0.1` as separate cookie hosts even though they
// resolve to the same IP, so logging in at `http://localhost:5173` and then
// trying to connect Schwab (which navigates to `https://127.0.0.1:8000`)
// silently drops the auth cookie. This plugin forces a single canonical
// host so the cookie always lives where the OAuth callback expects it.
//
// Only active during `vite dev`. The production bundle is served by the
// FastAPI container at a single origin, so there's no hostname split to
// reconcile.
const redirectLocalhostToLoopback: Plugin = {
  name: 'redirect-localhost-to-loopback',
  configureServer(server) {
    server.middlewares.use((req, res, next) => {
      const host = req.headers.host;
      if (!host) {
        next();
        return;
      }
      // `host` is "hostname[:port]". Only intercept the bare `localhost`
      // form so any other hostname (e.g. a LAN IP for mobile testing)
      // passes through untouched.
      if (!host.startsWith('localhost')) {
        next();
        return;
      }
      const target = host.replace(/^localhost/, '127.0.0.1');
      // Vite dev serves over HTTP unless explicitly configured with a
      // cert; the socket's TLS flag is the right source of truth either
      // way.
      const isTls = 'encrypted' in req.socket && req.socket.encrypted === true;
      const protocol = isTls ? 'https' : 'http';
      const location = `${protocol}://${target}${req.url ?? '/'}`;
      res.statusCode = 301;
      res.setHeader('Location', location);
      res.end();
    });
  },
};

export default defineConfig({
  plugins: [redirectLocalhostToLoopback, react()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': {
        target: process.env['VITE_API_URL'] ?? 'https://127.0.0.1:8000',
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
