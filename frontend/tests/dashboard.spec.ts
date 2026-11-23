import { test, expect, type Page } from '@playwright/test'

const mockDeliveryId = '00000000-0000-4000-8000-000000000001'
const mockIntegrationId = '00000000-0000-4000-8000-000000000002'
const live = Boolean(process.env.DASHBOARD_URL)
const receivedStatus = process.env.DEMO_OPERATIONS === '1' ? 'COMPLETED' : 'RECEIVED'
async function signIn(page: Page, username: string, password: string) {
  await page.goto('/')
  await page.getByLabel('Username', { exact: true }).fill(username)
  await page.getByLabel('Password', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible()
}

async function authHeaders(page: Page) {
  const session = await page.evaluate(async () => (await fetch('/api/auth/session')).json())
  const cookie = (await page.context().cookies()).find(item => item.name === '__Host-opsbridge_session')
  if (!cookie) throw new Error('Browser session cookie missing')
  return { Cookie: cookie.name + '=' + cookie.value, 'X-CSRF-Token': session.csrf as string }
}

test.beforeEach(async ({ page }, info) => {
  if (live) {
    if (!info.title.includes('role boundaries')) await signIn(page, 'demo-admin', process.env.OPSBRIDGE_DEMO_PASSWORD!)
  } else {
    await page.route('**/api/auth/session', route => route.fulfill({ json: {
      id: 'synthetic', username: 'mock-operator', role: 'OPERATOR', csrf: 'fixture',
    } }))
  }
})

test('loads, filters, opens and refreshes deliveries', async ({ page }) => {
  test.skip(live, 'Uses simulated API responses')
  let refreshes = 0
  const row = {
    id: mockDeliveryId, integration_id: mockIntegrationId, status: 'RECEIVED', delivery_type: 'DAILY_LEDGER',
    business_date: '2026-01-01', deadline_at: '2026-01-02T00:00:00Z', expected_pattern: '*.csv',
    current_file: { original_name: 'ledger.csv', size_bytes: 35, received_at: '2026-01-01T00:00:00Z', content_hash: 'a'.repeat(64) },
  }
  await page.route('**/api/dashboard/**', async route => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/activity')) return route.fulfill({ json: { items: [] } })
    if (['/attention', '/events', '/incidents'].some(suffix => url.pathname.endsWith(suffix))) return route.fulfill({ json: [] })
    if (url.pathname.endsWith('/overview')) {
      refreshes++
      return route.fulfill({ json: { integrations: [{ id: mockIntegrationId, name: 'Treasury', active: true, source_name: 'Vendor' }], counts: { RECEIVED: 1 } } })
    }
    if (url.pathname.endsWith('/' + mockDeliveryId)) return route.fulfill({ json: row })
    const showsRow = ['', 'RECEIVED'].includes(url.searchParams.get('status') ?? '')
    return route.fulfill({ json: showsRow ? [row] : [] })
  })
  await page.goto('/deliveries')
  await expect(page.getByText('ledger.csv')).toBeVisible()
  await page.getByRole('button', { name: 'Treasury' }).click()
  await page.getByLabel('Status').selectOption('VALIDATION_FAILED')
  await expect(page.getByText('No matching deliveries')).toBeVisible()
  await page.getByLabel('Status').selectOption('RECEIVED')
  await page.getByRole('link', { name: 'Daily ledger' }).click()
  await expect(page.locator('.delivery-workspace').getByText('ledger.csv')).toBeVisible()
  await page.getByRole('link', { name: /^Back to / }).click()
  await expect(page.locator('.delivery-workspace')).toHaveCount(0)
  const prior = refreshes
  await page.getByRole('button', { name: 'Refresh' }).click()
  await expect.poll(() => refreshes).toBeGreaterThan(prior)
})

test('shows loading and recovers from a failed request', async ({ page }) => {
  test.skip(live, 'Uses simulated API responses')
  let release!: () => void
  const wait = new Promise<void>(resolve => { release = resolve })
  let failure = true
  await page.route('**/api/dashboard/**', async route => {
    await wait
    if (failure) return route.fulfill({ status: 503 })
    if (route.request().url().includes('/activity?')) return route.fulfill({ json: { items: [] } })
    return route.fulfill({ json: route.request().url().endsWith('/overview') ? { integrations: [], counts: {} } : [] })
  })
  await page.goto('/deliveries')
  await expect(page.getByText('Loading deliveries')).toBeVisible()
  release()
  await expect(page.getByRole('alert').filter({ hasText: 'Could not load deliveries' })).toBeVisible()
  failure = false
  await page.getByRole('button', { name: 'Try again' }).click()
  await expect(page.getByText('No matching deliveries')).toBeVisible()
})

test('shows the real intake result through the dashboard proxy', async ({ page, request }) => {
  test.skip(!live, 'Requires the isolated intake demo')
  await page.goto('/overview/activity')
  await expect(page.getByText('Live', { exact: true })).toBeVisible()
  if (process.env.DEMO_EVENTS === '1') {
    const feed = page.getByRole('region', { name: 'Activity feed' })
    await page.getByLabel('Event type').selectOption('FileReceived')
    await expect(feed.getByText('Intake accepted a file').first()).toBeVisible()
    await feed.getByRole('button', { name: 'Load older activity' }).click()
    await expect(feed.locator('li')).toHaveCount(20)
    await feed.getByRole('button', { name: 'View delivery' }).first().click()
    await expect(page.locator('.delivery-workspace').getByText('File Received', { exact: true })).toBeVisible()
    await page.getByRole('link', { name: /^Back to / }).click()
  }
  await page.getByRole('link', { name: 'Action Center', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Requires attention' })).toBeVisible()
  const attention = page.getByRole('region', { name: 'Requires attention' })
  await expect(attention.locator('li').first()).toContainText('Source delivery ID conflict')
  await page.getByRole('link', { name: 'Deliveries', exact: true }).click()
  await page.getByRole('button', { name: 'Demo', exact: true }).click()
  await page.getByLabel('Status').selectOption(receivedStatus)
  await expect(page.getByRole('region', { name: 'Delivery results' }).locator('tbody tr')).toHaveCount(1)
  await page.getByRole('link', { name: 'Daily', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Current file' }).getByText('data.csv', { exact: true })).toBeVisible()
  await page.getByText('File identifiers and integrity', { exact: true }).click()
  await expect(page.locator('.delivery-workspace').getByText('SHA-256')).toBeVisible()
  await expect(page.locator('.delivery-workspace').getByText('File Received', { exact: true })).toBeVisible()
  if (receivedStatus === 'COMPLETED') {
    const response = await request.get('/api/dashboard/deliveries?status=COMPLETED&limit=1', { headers: await authHeaders(page) })
    const completed = (await response.json())[0]
    const rejected = await request.post(`/api/dashboard/deliveries/${completed.id}/reprocess`, {
      headers: await authHeaders(page), data: { confirmed: false, file_id: completed.current_file.id, attempt_series: 1 },
    })
    expect(rejected.status()).toBe(422)
    await expect(page.locator('.delivery-workspace').getByText('File Processing Completed', { exact: true })).toBeVisible()
    await expect(page.locator('.delivery-workspace').getByText('Series 1 · 1 of 3', { exact: true })).toBeVisible()
  }
  await page.getByRole('link', { name: /^Back to / }).click()
  await page.getByRole('button', { name: /^Northstar Treasury/ }).click()
  await page.getByLabel('Status').selectOption('VALIDATION_FAILED')
  await expect(page.getByRole('region', { name: 'Delivery results' }).locator('tbody tr')).toHaveCount(1)
  await page.locator('tbody').getByRole('link', { name: 'Fx confirmations' }).click()
  await expect(page.locator('.delivery-workspace').getByText('Csv row invalid')).toBeVisible()
  await expect(page.getByRole('region', { name: 'Delivery timeline' })
    .getByText('CSV_ROW_INVALID', { exact: true })).toBeVisible()
  await page.getByRole('link', { name: /^Back to / }).click()
  await page.getByLabel('Status').selectOption(receivedStatus)
  await page.getByLabel('Sort').selectOption('deadline')
  await page.locator('tbody').getByRole('link', { name: 'Custody positions' }).click()
  await expect(page.locator('.delivery-workspace').getByText('File Validation Failed', { exact: true })).toBeVisible()
  await expect(page.locator('.delivery-workspace').getByText('File Received', { exact: true })).toBeVisible()
  await page.getByRole('link', { name: /^Back to / }).click()
  if (receivedStatus === 'COMPLETED') {
    await page.getByLabel('Status').selectOption('EXPECTED')
    await page.locator('tbody').getByRole('link', { name: 'Settlement report' }).click()
    await expect(page.locator('.delivery-workspace').getByText('Delivery Overdue', { exact: true })).toBeVisible()
    await expect(page.locator('.delivery-workspace').getByText(/^Missing or overdue · (Open|Acknowledged)$/)).toBeVisible()
    await page.getByRole('link', { name: /^Back to / }).click()
  }
  await page.setViewportSize({ width: 390, height: 840 })
  await page.getByRole('button', { name: 'Open navigation' }).click()
  await page.getByRole('dialog', { name: 'Workspace menu' }).getByRole('link', { name: 'Action Center', exact: true }).click()
  await expect(attention).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
  if (process.env.DEMO_NOTIFICATIONS === '1') {
    await page.getByRole('button', { name: 'Open navigation' }).click()
    await page.getByRole('dialog', { name: 'Workspace menu' }).getByRole('link', { name: 'Deliveries', exact: true }).click()
    await page.getByRole('combobox', { name: 'Integration', exact: true }).selectOption({ label: 'Demo' })
    await page.getByLabel('Status').selectOption('EXPECTED')
    await page.locator('tbody').getByRole('link', { name: 'Notify browser' }).click()
    const detail = page.locator('.delivery-workspace')
    await expect(detail.getByText('Process owners', { exact: false })).toBeVisible()
    await detail.getByText('Notification history (4)', { exact: true }).click()
    await expect(detail.getByText('Opened · Sent', { exact: true })).toHaveCount(2)
    await detail.getByLabel('Comment (optional)').fill('Investigating in the browser')
    await detail.getByRole('button', { name: 'Acknowledge incident' }).click()
    await expect(detail.getByText('Investigating in the browser', { exact: true })).toBeVisible()
    await expect(detail.getByText('Escalated · Level 1 · Cancelled', { exact: true })).toBeVisible()
    await page.getByRole('link', { name: /^Back to / }).click()
    await page.getByRole('button', { name: 'Open navigation' }).click()
    await page.getByRole('dialog', { name: 'Workspace menu' }).getByRole('link', { name: 'Action Center', exact: true }).click()
    await page.getByText('Notification policies', { exact: true }).click()
    await expect(page.getByText('All incident types · All severities', { exact: true })).toBeVisible()
  }
})

test('real intake dashboard refreshes after another client commits a delivery and acknowledges an incident', async ({ page, request }) => {
  test.skip(!live || process.env.DEMO_NOTIFICATIONS !== '1', 'Requires the isolated demo with incidents')
  const api = 'http://127.0.0.1:8000'
  await page.goto('/deliveries')
  await expect(page.getByText('Live', { exact: true })).toBeVisible()
  const overview = await (await request.get('/api/dashboard/overview', { headers: await authHeaders(page) })).json()
  const integration = overview.integrations.find((item: { name: string }) => item.name === 'Demo')
  await page.getByRole('button', { name: 'Demo', exact: true }).click()
  const delivery = await request.post(api + '/integrations/' + integration.id + '/delivery-expectations', {
    headers: await authHeaders(page), data: { delivery_type: 'LIVE_BROWSER_CHECK', business_date: '2026-01-01', expected_pattern: '*.csv',
      deadline_at: new Date(Date.now() + 86_400_000).toISOString() },
  })
  expect(delivery.status()).toBe(201)
  await expect(page.getByRole('link', { name: 'Live browser check', exact: true })).toBeVisible()

  await page.getByRole('button', { name: /^Northstar Treasury/ }).click()
  await page.getByRole('region', { name: 'Delivery results' })
    .getByRole('link', { name: 'Settlement report', exact: true }).click()
  const dialog = page.locator('.delivery-workspace')
  await expect(dialog.getByText('Missing or overdue · Open')).toBeVisible()
  const northstar = overview.integrations.find((item: { name: string }) => item.name === 'Northstar Treasury')
  const deliveries = await (await request.get('/api/dashboard/deliveries?integration_id=' + northstar.id, { headers: await authHeaders(page) })).json()
  const settlement = deliveries.find((item: { delivery_type: string }) => item.delivery_type === 'SETTLEMENT_REPORT')
  const incidents = await (await request.get('/api/dashboard/deliveries/' + settlement.id + '/incidents', { headers: await authHeaders(page) })).json()
  const missing = incidents.find((item: { incident_type: string }) => item.incident_type === 'MISSING_FILE')
  const ack = await request.post('/api/dashboard/incidents/' + missing.id + '/acknowledge', {
    headers: await authHeaders(page), data: { comment: 'Acknowledged from another client' },
  })
  expect(ack.ok()).toBe(true)
  await expect(dialog.getByText('Missing or overdue · Acknowledged')).toBeVisible()
})

test('coalesces invalidations, polls on disconnect and refreshes after reconnect', async ({ page }) => {
  test.skip(live, 'Uses a controlled EventSource')
  await page.addInitScript(() => {
    class MockEvents extends EventTarget {
      onerror?: () => void
      constructor() {
        super()
        Object.assign(window, { sendDashboardSignal: (kind: string) => {
          if (kind === 'error') this.onerror?.()
          else this.dispatchEvent(new Event(kind))
        } })
      }
      close() {}
    }
    Object.defineProperty(window, 'EventSource', { value: MockEvents })
  })
  await page.clock.install()
  let outcome = 'EXPECTED'
  let snapshots = 0
  await page.route('**/api/dashboard/**', route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/overview')) {
      snapshots++
      return route.fulfill({ json: { integrations: [] } })
    }
    if (path.endsWith('/deliveries')) return route.fulfill({ json: [{
      id: mockDeliveryId, integration_id: mockIntegrationId, status: outcome, delivery_type: 'DAILY',
      business_date: '2026-01-01', deadline_at: '2026-01-02T00:00:00Z',
    }] })
    return route.fulfill({ json: path.endsWith('/activity') ? { items: [] } : [] })
  })
  const signal = (kind: string) => page.evaluate(value => {
    (window as unknown as { sendDashboardSignal: (signal: string) => void }).sendDashboardSignal(value)
  }, kind)
  const row = page.locator('tbody tr').first()
  await page.goto('/deliveries')
  await expect(row).toContainText('Expected')
  const before = snapshots
  outcome = 'RECEIVED'
  await signal('invalidate')
  await signal('invalidate')
  await signal('invalidate')
  await page.clock.runFor(2_100)
  await expect(row).toContainText('Received')
  expect(snapshots).toBe(before + 1)
  await signal('error')
  await expect(page.getByText('Polling fallback')).toBeVisible()
  outcome = 'VALIDATION_FAILED'
  await page.clock.runFor(17_100)
  await expect(row).toContainText('Validation failed')
  outcome = 'COMPLETED'
  await signal('invalidate')
  await page.clock.runFor(2_100)
  await expect(page.getByText('Live', { exact: true })).toBeVisible()
  await expect(row).toContainText('Completed')
  const afterReconnect = snapshots
  await page.clock.runFor(17_100)
  expect(snapshots).toBe(afterReconnect)
})

test('manual reprocessing requires confirmation and includes the audited actor', async ({ page }) => {
  test.skip(live, 'Uses simulated API responses for the confirmation flow')
  const row = {
    id: mockDeliveryId, integration_id: mockIntegrationId, status: 'PROCESSING_FAILED', delivery_type: 'DAILY_LEDGER',
    business_date: '2026-01-01', deadline_at: '2026-01-02T00:00:00Z', expected_pattern: '*.csv',
    current_file: { id: 'file-1', original_name: 'ledger.csv', size_bytes: 35, received_at: '2026-01-01T00:00:00Z',
      content_hash: 'a'.repeat(64), attempt_series: 1, attempt_count_in_series: 3, can_reprocess: true },
  }
  await page.route('**/api/dashboard/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/activity')) return route.fulfill({ json: { items: [] } })
    if (path.endsWith('/overview')) return route.fulfill({ json: { integrations: [], reprocessing_enabled: true } })
    if (path.endsWith('/reprocess')) {
      expect(route.request().postDataJSON()).toEqual({ confirmed: true, file_id: 'file-1', attempt_series: 1 })
      return route.fulfill({ status: 202, json: { status: 'queued' } })
    }
    if (path.endsWith('/' + mockDeliveryId)) return route.fulfill({ json: row })
    return route.fulfill({ json: path.endsWith('/deliveries') ? [row] : [] })
  })
  await page.goto('/deliveries')
  await page.getByRole('link', { name: 'Daily ledger' }).click()
  const queue = page.getByRole('button', { name: 'Queue reprocessing' })
  await expect(queue).toBeDisabled()
  await page.getByLabel('Confirm a new processing series').check()
  await queue.click()
  await expect(page.getByText('A new processing series was queued.')).toBeVisible()
})

test('Copilot labels simulated analysis and handles loading, citations and timeouts on mobile', async ({ page }) => {
  test.skip(live, 'Uses simulated API responses')
  let unblock!: () => void
  const pending = new Promise<void>(resolve => { unblock = resolve })
  let calls = 0
  await page.route('**/api/dashboard/**', async route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/copilot/status')) return route.fulfill({ json: { provider: 'mock' } })
    if (path.endsWith('/copilot/investigate')) {
      expect(route.request().headers()['x-csrf-token']).toBe('fixture')
      expect(route.request().postDataJSON().question).toBe('Which deliveries breached their SLA?')
      if (++calls > 1) return route.fulfill({ status: 504, json: { detail: 'provider_timeout' } })
      await pending
      return route.fulfill({ json: {
        provider: 'mock', summary: 'The deadline was breached.', summary_references: ['E1'], observations: ['E1'],
        hypotheses: [{ key: 'arrival', hypothesis: 'An upstream delay is possible.', next_step: 'Check vendor logs.', references: ['E1'] }],
        evidence: [{ ref: 'E1', kind: 'delivery', fact: 'An SLA breach was recorded.',
          record_id: 'e16a6345-2fbe-460c-90a0-2198b05dc50c', timestamp: '2026-01-01T00:00:00Z' }],
        missing_evidence: ['Vendor transfer logs are unavailable.'],
      } })
    }
    if (path.endsWith('/stream')) return route.fulfill({ status: 503 })
    if (path.endsWith('/activity')) return route.fulfill({ json: { items: [] } })
    return route.fulfill({ json: path.endsWith('/overview') ? { integrations: [] } : [] })
  })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/copilot')
  await expect(page.getByText('Simulated analysis')).toBeVisible()
  await page.getByRole('button', { name: 'Which deliveries breached their SLA?' }).click()
  await page.getByRole('button', { name: 'Ask Copilot' }).click()
  await expect(page.getByText('Reviewing persisted evidence…')).toBeVisible()
  unblock()
  const result = page.getByLabel('Investigation result')
  await expect(result.getByText('An upstream delay is possible.')).toBeVisible()
  await result.getByRole('link', { name: 'E1 · Delivery' }).first().click()
  await result.getByText('Technical identifier', { exact: true }).click()
  await expect(result.getByText('e16a6345-2fbe-460c-90a0-2198b05dc50c')).toBeVisible()
  await expect(result.getByText('Check vendor logs.')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
  await page.getByRole('button', { name: 'Ask Copilot' }).click()
  await expect(page.getByRole('alert')).toHaveText('The provider timed out. Try again.')
})

test('real intake Copilot investigates a persisted validation incident and answers an SLA question', async ({ page }) => {
  test.skip(!live || process.env.DEMO_OPERATIONS !== '1', 'Requires isolated persisted intake and SLA records')
  await page.goto('/deliveries')
  await page.getByRole('button', { name: /^Northstar Treasury/ }).click()
  await page.getByLabel('Status').selectOption('VALIDATION_FAILED')
  await page.locator('tbody').getByRole('link', { name: 'Fx confirmations' }).click()
  const detail = page.locator('.delivery-workspace')
  await detail.getByText('Investigate with Copilot', { exact: true }).click()
  await detail.getByRole('button', { name: 'Analyze incident' }).click()
  const result = detail.getByLabel('Investigation result')
  await expect(result.getByText(/CSV_ROW_INVALID/).first()).toBeVisible()
  await expect(result.getByText(/export formatting or encoding issue/)).toBeVisible()
  await expect(result.getByText(/root cause/)).toBeVisible()
  await expect(detail.getByText('Simulated analysis')).toBeVisible()
  await page.getByRole('link', { name: /^Back to / }).click()
  await page.getByRole('link', { name: 'AI Copilot', exact: true }).click()
  await page.getByRole('button', { name: 'Which deliveries breached their SLA?' }).click()
  await page.getByRole('button', { name: 'Ask Copilot' }).click()
  await expect(page.getByLabel('Investigation result').getByText(/A breach was recorded/).first()).toBeVisible()
})

test('real intake reconciliation displays differences, cited exceptions and an audited rerun', async ({ page }) => {
  test.skip(!live || process.env.DEMO_RECONCILIATION !== '1', 'Requires isolated two-source reconciliation')
  await page.goto('/reconciliation')
  const workbench = page.getByRole('region', { name: 'Reconciliation workbench' })
  await workbench.getByRole('link', { name: 'Fund vs Custodian · exception review' }).click()
  const run = workbench.getByLabel('Reconciliation run', { exact: true })
  await expect(run.getByText('2 matched pairs · 5 exception groups · Material difference detected')).toBeVisible()
  await expect(page).toHaveURL(/\/reconciliation\/runs\/[0-9a-f-]{36}$/)
  await page.reload()
  await expect(run.getByText('Source A · Synthetic Fund Accounting')).toBeVisible()
  await expect(run.getByText('Source B · Synthetic Custodian')).toBeVisible()
  await run.getByLabel('Result category').selectOption('AMOUNT_MISMATCH')
  await expect(run.getByText('-10.000000 USD')).toBeVisible()
  const inspect = run.getByRole('link', { name: /Inspect group/ })
  await expect(inspect).toHaveCount(1)
  await inspect.click()
  await run.getByText('Investigate exception with Copilot', { exact: true }).click()
  await run.getByRole('button', { name: 'Analyze exception' }).click()
  await expect(run.getByText(/valuation, rounding, or posting difference/)).toBeVisible()
  await run.getByRole('link', { name: 'View linked incident' }).click()
  const dialog = page.locator('.delivery-workspace')
  await expect(dialog.getByText('Reconciliation failure · Open')).toBeVisible()
  await dialog.getByRole('link', { name: 'View reconciliation run' }).click()
  const queue = run.getByRole('button', { name: 'Queue reconciliation rerun' })
  await expect(queue).toBeDisabled()
  await run.getByLabel('Confirm a new reconciliation run').check()
  await queue.click()
  await expect(run.getByRole('link', { name: 'View preceding run' })).toBeVisible()
  await run.getByRole('link', { name: 'View preceding run' }).click()
  await expect(run.getByText('2 matched pairs · 5 exception groups · Material difference detected')).toBeVisible()
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
})

test('real intake authentication enforces role boundaries, CSRF and logout', async ({ page, request }) => {
  test.skip(!live, 'Requires the disposable PostgreSQL login service')
  expect((await request.get('/api/dashboard/stream')).status()).toBe(401)
  await signIn(page, 'demo-viewer', process.env.OPSBRIDGE_VIEWER_PASSWORD!)
  await expect(page.getByText('demo-viewer · VIEWER')).toBeVisible()
  await expect(page.getByText('Administration', { exact: true })).toHaveCount(0)
  const headers = await authHeaders(page)
  const missingId = '00000000-0000-0000-0000-000000000001'
  const denied = await request.post('/api/dashboard/incidents/' + missingId + '/acknowledge', {
    headers, data: {},
  })
  expect(denied.status()).toBe(403)
  expect((await request.post('/api/dashboard/deliveries/' + missingId + '/reprocess', {
    headers, data: { confirmed: true, file_id: missingId, attempt_series: 1 },
  })).status()).toBe(403)
  expect((await request.post('/api/dashboard/reconciliation/runs/' + missingId + '/rerun', {
    headers, data: { confirmed: true, request_id: missingId },
  })).status()).toBe(403)
  expect((await request.post('/api/dashboard/copilot/investigate', {
    headers: { Cookie: headers.Cookie }, data: { question: 'Which deliveries breached their SLA?' },
  })).status()).toBe(403)
  expect((await request.post('/api/dashboard/copilot/investigate', {
    headers, data: { question: 'Which deliveries breached their SLA?' },
  })).status()).toBe(200)
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page.getByRole('heading', { name: 'Sign in to OpsBridge' })).toBeVisible()
  expect((await request.get('/api/dashboard/overview', { headers })).status()).toBe(401)
  await signIn(page, 'demo-operator', process.env.OPSBRIDGE_OPERATOR_PASSWORD!)
  await expect(page.getByText('demo-operator · OPERATOR')).toBeVisible()
  await expect(page.getByText('Administration', { exact: true })).toHaveCount(0)
  await expect(page.getByText('Live', { exact: true })).toBeVisible()
})

test('real intake reprocessing confirms one new series and rejects a stale replay', async ({ page, request }) => {
  test.skip(!live || process.env.DEMO_RELIABILITY !== '1', 'Requires the disposable retry exhaustion fixture')
  const headers = await authHeaders(page)
  const listed = await request.get('/api/dashboard/deliveries?status=PROCESSING_FAILED&limit=100', { headers })
  expect(listed.ok()).toBeTruthy()
  const failed = (await listed.json()).find((delivery: { delivery_type: string }) => delivery.delivery_type === 'FAULT_REPROCESS')
  expect(failed?.current_file?.can_reprocess).toBe(true)
  const endpoint = `/api/dashboard/deliveries/${failed.id}/reprocess`
  await page.goto(`/deliveries/${failed.id}`)
  const queue = page.getByRole('button', { name: 'Queue reprocessing' })
  await expect(queue).toBeDisabled()
  await page.getByLabel('Confirm a new processing series').check()
  const recorded = page.waitForResponse(response => new URL(response.url()).pathname === endpoint && response.request().method() === 'POST')
  await queue.click()
  const response = await recorded
  expect(response.status()).toBe(202)
  await expect(page.getByText('A new processing series was queued.')).toBeVisible()
  expect((await request.post(endpoint, { headers, data: response.request().postDataJSON() })).status()).toBe(409)
  await expect(page.getByRole('region', { name: 'Delivery timeline' })
    .getByText('Manual Reprocessing Requested', { exact: true })).toHaveCount(1)
})

test('real intake SSE catches up after an interrupted browser connection', async ({ page, request }) => {
  test.skip(!live || process.env.DEMO_RELIABILITY !== '1', 'Requires the disposable reliability scenario')
  const stream = '**/api/dashboard/stream'
  await page.route(stream, route => route.abort('failed'))
  await page.goto('/deliveries')
  await expect(page.getByText('Polling fallback')).toBeVisible()
  await expect(page.getByRole('region', { name: 'Delivery results' })).toBeVisible()
  const headers = await authHeaders(page)
  const overview = await (await request.get('/api/dashboard/overview', { headers })).json()
  const integration = overview.integrations.find((item: { name: string }) => item.name === 'Reliability fixtures')
  const response = await request.post('http://127.0.0.1:8000/integrations/' + integration.id + '/delivery-expectations', {
    headers, data: { delivery_type: 'SSE_CATCHUP', business_date: '2026-01-01',
      deadline_at: new Date(Date.now() + 86_400_000).toISOString(), expected_pattern: '*.csv' },
  })
  expect(response.status()).toBe(201)
  const row = page.getByRole('link', { name: 'Sse catchup', exact: true })
  await expect(row).toHaveCount(0)
  const start = performance.now()
  await page.unroute(stream)
  await expect(page.getByText('Live', { exact: true })).toBeVisible({ timeout: 12000 })
  await expect(row).toBeVisible()
  console.log(JSON.stringify({ sse_unblock_to_visible_ms: Math.round(performance.now() - start) }))
})
