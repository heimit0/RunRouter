import { defineConfig } from '@playwright/test'

/**
 * Playwright-Konfiguration für das RunRouter-Frontend.
 *
 * Zwei Projekte:
 * - `mock` – deterministische UI-Tests, /api/*-Antworten werden im Browser
 *           gemockt (kein OSRM/Nominatim/Overpass nötig).
 * - `real` – echter End-to-End-Test gegen laufendes Backend + öffentliches
 *           OSRM/Nominatim (extern, kann schwanken).
 *
 * Beide nutzen das System-Chrome (`channel: 'chrome'`), kein Browser-Download.
 */
export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : [['list'], ['html', { open: 'never' }]],
  use: {
    channel: 'chrome',
    headless: true,
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
  },
  webServer: {
    command: 'uv run runrouter',
    url: 'http://127.0.0.1:8010/api/health',
    reuseExistingServer: !process.env.CI,
    timeout: 30_000,
  },
  projects: [
    {
      name: 'mock',
      testMatch: /smoke\.spec\.ts/,
      use: { baseURL: 'http://127.0.0.1:8010' },
    },
    {
      name: 'real',
      testMatch: /real\.spec\.ts/,
      use: { baseURL: 'http://127.0.0.1:8010' },
    },
  ],
})
