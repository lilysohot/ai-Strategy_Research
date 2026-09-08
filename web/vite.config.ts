import { fileURLToPath, URL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vite'

// The dev server proxies /api to the FastAPI backend so the SPA never has to
// know an absolute origin, and so the SSE stream is same-origin (no CORS
// preflight on a long-lived GET). Production serves the built assets from
// Caddy, which reverse-proxies /api to the api container (deploy/Caddyfile).
const API_TARGET = process.env.VITE_API_PROXY ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: {
      // SSE-friendly: no buffering, long timeout. Vite's proxy forwards the
      // stream chunk-by-chunk by default; `ws: false` keeps it a plain HTTP GET.
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
        ws: false,
      },
    },
  },
  // `vite preview` serves the built assets; mirror the dev proxy so the SPA
  // reaches the backend the same way it would behind Caddy in production.
  preview: {
    port: 4173,
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
        ws: false,
      },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
})
