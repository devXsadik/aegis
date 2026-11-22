import { defineConfig } from '@playwright/test'

// Smoke test of the real dashboard against a throwaway API (scripts/e2e_server.py: temp SQLite,
// seeded alerts, every outside channel blanked). `npm run e2e`; first time: `npx playwright install chromium`
// (or PW_CHANNEL=chrome to use the installed Google Chrome).
const PY = process.env.PYTHON || '../.venv/bin/python'

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  use: {
    baseURL: 'http://localhost:5174',
    channel: process.env.PW_CHANNEL || undefined,
    trace: 'retain-on-failure',
  },
  webServer: [
    {
      command: `${PY} ../scripts/e2e_server.py`,
      url: 'http://127.0.0.1:8010/health',
      timeout: 120_000,
      reuseExistingServer: false,
    },
    {
      command: 'npx vite --port 5174 --strictPort',
      url: 'http://localhost:5174',
      env: { API_PROXY: 'http://127.0.0.1:8010' },
      reuseExistingServer: false,
    },
  ],
})
