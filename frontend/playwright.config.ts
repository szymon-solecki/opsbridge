import { defineConfig } from '@playwright/test'

const port = Number(process.env.OPSBRIDGE_PLAYWRIGHT_PORT ?? '4173')
if (!Number.isInteger(port) || port < 1024 || port > 65535) throw new Error('Invalid Playwright port')
const localOrigin = 'http://127.0.0.1:' + port

export default defineConfig({
  testDir: './tests',
  use: {
    baseURL: process.env.DASHBOARD_URL ?? localOrigin,
    launchOptions: process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {},
  },
  webServer: process.env.DASHBOARD_URL ? undefined : {
    command: 'npx vite --host 127.0.0.1 --port ' + port + ' --strictPort',
    url: localOrigin,
  },
})
