import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// Port 8001 is the compatible Phase 1+ backend (adds simulator controls to live-sample).
// The older process on 8000 rejects those fields. Override with PUMPGUARD_API_PROXY_TARGET if needed.
const apiProxyTarget = process.env.PUMPGUARD_API_PROXY_TARGET ?? 'http://127.0.0.1:8001';

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: apiProxyTarget, changeOrigin: true },
      '/health': { target: apiProxyTarget, changeOrigin: true },
    },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    css: true,
  },
});
