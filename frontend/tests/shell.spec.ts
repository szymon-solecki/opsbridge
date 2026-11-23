import { mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test, type Page } from '@playwright/test'

const integration = '3dd5c46f-9f54-470c-bdc0-62fd473c46f1'
const delivery = '57e46882-696a-4469-8ae9-8d5b16c4c9c2'
const incident = 'd211db69-854d-4f9b-b022-66ea2af873eb'
const run = '79880256-757e-40aa-a4c2-b91644d6c5fa'
const overview = {
  integrations: [{ id: integration, name: 'Northstar Treasury', active: true, source_name: 'Synthetic custodian' }],
  counts: { COMPLETED: 24 },
  metrics: { total: 31, received: 27, validation_failed: 2, pending: 4, overdue: 3, breached: 5, on_time: 25 },
  incidents_by_type: { MISSING_FILE: 3, VALIDATION_FAILURE: 2, SOURCE_DELIVERY_ID_CONFLICT: 1 },
}

test.skip(Boolean(process.env.DASHBOARD_URL), 'Uses simulated API responses')

async function stubWorkspace(page: Page, role = 'ADMIN', expiresAt?: string) {
  const requests: string[] = []
  await page.addInitScript(() => {
    class LocalEvents extends EventTarget {
      constructor() {
        super()
        setTimeout(() => this.dispatchEvent(new Event('invalidate')), 30)
      }
      close() {}
    }
    Object.defineProperty(window, 'EventSource', { value: LocalEvents })
  })
  await page.route('**/api/auth/session', route => route.fulfill({ json: {
    id: 'shell-test', username: 'demo-operator', role, csrf: 'synthetic-csrf', expires_at: expiresAt,
  } }))
  await page.route('**/api/dashboard/**', route => {
    const path = new URL(route.request().url()).pathname.replace('/api/dashboard', '')
    requests.push(path)
    if (path === '/overview') return route.fulfill({ json: overview })
    if (path === '/reconciliation') return route.fulfill({ json: { items: [], has_more: false, rerun_enabled: false } })
    if (path === '/activity') return route.fulfill({ json: { items: [] } })
    if (path === '/copilot/status') return route.fulfill({ json: { provider: 'mock' } })
    if (path === '/notification-policies') return route.fulfill({ json: { rules: [] } })
    if (path === '/deliveries/' + delivery) return route.fulfill({ json: {
      id: delivery, integration_id: integration, status: 'EXPECTED', delivery_type: 'SETTLEMENT_REPORT',
      business_date: '2026-11-23', deadline_at: '2026-11-23T08:00:00Z', expected_pattern: '*.csv',
    } })
    if (path === '/deliveries/' + delivery + '/incidents') return route.fulfill({ json: [{
      id: incident, incident_type: 'MISSING_FILE', status: 'OPEN', severity: 'HIGH',
      reason: 'Settlement report has not arrived', opened_at: '2026-11-23T08:15:00Z',
    }] })
    if (path === '/reconciliation/runs/' + run) return route.fulfill({ status: 404 })
    return route.fulfill({ json: [] })
  })
  await page.route('**/api/auth/operators', route => {
    requests.push(new URL(route.request().url()).pathname)
    return route.fulfill({ json: [] })
  })
  return requests
}

test('desktop navigation uses stable links and browser history', async ({ page }) => {
  await stubWorkspace(page)
  await page.goto('/')
  await expect(page).toHaveURL(/\/overview$/)
  const navigation = page.getByRole('navigation', { name: 'Workspace navigation' })
  expect(await navigation.getByRole('link').count()).toBe(7)
  for (const [title, path] of [
    ['Action Center', 'action-center'], ['Deliveries', 'deliveries'], ['Reconciliation', 'reconciliation'],
    ['AI Copilot', 'copilot'], ['Monitoring', 'monitoring'], ['Administration', 'administration'],
  ]) {
    const link = navigation.getByRole('link', { name: title, exact: true })
    await link.click()
    await expect(page).toHaveURL(new RegExp('/' + path + '$'))
    await expect(link).toHaveAttribute('aria-current', 'page')
    await expect(page.getByRole('heading', { name: title, exact: true, level: 1 })).toBeFocused()
  }
  await page.goBack()
  await expect(page.getByRole('heading', { name: 'Monitoring', exact: true, level: 1 })).toBeVisible()
  await page.goForward()
  await expect(page.getByRole('heading', { name: 'Administration', exact: true, level: 1 })).toBeVisible()
})

test('direct loading and refresh preserve incident, delivery filter and run context', async ({ page }) => {
  const requests = await stubWorkspace(page, 'OPERATOR')
  const filters = '?status=EXPECTED&integration=' + integration
  await page.goto('/deliveries/' + delivery + '/incidents/' + incident + filters)
  let detail = page.locator('.delivery-workspace')
  await expect(detail.getByText('Settlement report has not arrived')).toBeVisible()
  await page.reload()
  await expect(detail.getByText('Settlement report has not arrived')).toBeVisible()
  await detail.getByRole('link', { name: /^Back to / }).click()
  await expect(page).toHaveURL('/deliveries' + filters)
  await expect(page.getByLabel('Status')).toHaveValue('EXPECTED')
  await expect(page.getByRole('button', { name: /Northstar Treasury/ })).toHaveAttribute('aria-pressed', 'true')
  await page.goto('/reconciliation/runs/' + run + '?exception=3')
  await expect(page.getByRole('heading', { name: 'Reconciliation', level: 1 })).toBeVisible()
  await expect.poll(() => requests.filter(path => path === '/reconciliation/runs/' + run).length).toBeGreaterThan(0)
  await page.goto('/missing-workspace-page')
  await expect(page.getByRole('heading', { name: 'Page not found', level: 1 })).toBeVisible()
  await page.getByRole('link', { name: 'Return to Overview' }).click()
  await expect(page).toHaveURL(/\/overview$/)
})

for (const role of ['VIEWER', 'OPERATOR']) {
  test(`${role} cannot open Administration by link or by URL`, async ({ page }) => {
    const requests = await stubWorkspace(page, role)
    await page.goto('/administration')
    await expect(page.getByRole('alert')).toContainText('Administration requires the Admin role.')
    await expect(page.getByRole('navigation').getByRole('link', { name: 'Administration' })).toHaveCount(0)
    expect(requests.some(path => path === '/api/auth/operators' || path === '/notification-policies')).toBe(false)
  })
}

test('session expiration keeps the protected deep link but removes the workspace', async ({ page }) => {
  const start = new Date('2026-11-23T09:00:00Z')
  await page.clock.install({ time: start })
  await stubWorkspace(page, 'OPERATOR', '2026-11-23T09:01:00Z')
  await page.goto('/deliveries/' + delivery)
  await expect(page.locator('.delivery-workspace').getByText('Settlement report', { exact: true })).toBeVisible()
  await page.clock.fastForward(61000)
  await expect(page.getByRole('heading', { name: 'Sign in to OpsBridge' })).toBeVisible()
  await expect(page.getByRole('navigation')).toHaveCount(0)
  await expect(page).toHaveURL('/deliveries/' + delivery)
})

test('responsive navigation is keyboard accessible and keeps the content in the viewport', async ({ page }) => {
  await stubWorkspace(page)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.goto('/overview')
  await expect(page.getByRole('heading', { name: 'Operational snapshot' })).toBeVisible()
  await expect(page.getByText('Live', { exact: true })).toBeVisible()
  const directory = process.env.OPSBRIDGE_SCREENSHOTS_DIR
  if (directory) {
    mkdirSync(directory, { recursive: true })
    await page.screenshot({ path: join(directory, 'desktop.png'), animations: 'disabled' })
  }
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
  if (directory) await page.screenshot({ path: join(directory, 'mobile.png'), fullPage: true, animations: 'disabled' })
  const menu = page.getByRole('button', { name: 'Open navigation' })
  await menu.focus()
  await page.keyboard.press('Enter')
  const drawer = page.getByRole('dialog', { name: 'Workspace menu' })
  await expect(drawer.getByRole('link', { name: 'Overview' })).toHaveAttribute('aria-current', 'page')
  if (directory) await page.screenshot({ path: join(directory, 'mobile-navigation.png'), animations: 'disabled' })
  await page.keyboard.press('Escape')
  await expect(drawer).toHaveCount(0)
  await expect(menu).toBeFocused()
  await menu.click()
  await drawer.getByRole('link', { name: 'Action Center' }).click()
  await expect(page).toHaveURL(/\/action-center$/)
  await expect(drawer).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'Action Center', level: 1 })).toBeFocused()
})
