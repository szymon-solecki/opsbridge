import { join } from 'node:path'
import { expect, test, type Page } from '@playwright/test'

const live = Boolean(process.env.DASHBOARD_URL)
const north = '8f583773-0917-4857-a53b-82c58beb728e'
const fund = 'b662def5-c108-49b0-b05b-63c22c0fc4d4'
const delivery = '3da07a71-92b6-453e-bb90-dc0299fb1845'
const conflict = 'a0565652-372c-47f0-aa2c-0b2a086e244a'
const run = '3d802449-c904-40d5-8c6a-7fbf13a9bd2c'
const deadline = '2026-11-23T08:00:00Z'
const opened = '2026-11-23T08:15:00Z'
const metrics = { total: 12, received: 10, validation_failed: 1, pending: 0, overdue: 2, breached: 4, on_time: 9 }
const known = { delivery_id: delivery, integration_id: north, delivery_type: 'CASH_LEDGER', business_date: '2026-11-23',
  status: 'COMPLETED', deadline_at: deadline, at: opened, action: 'Compare retained evidence with the submission.' }
const issues = [
  { ...known, key: 'validation', kind: 'VALIDATION_FAILURE', recorded_incident: true, reason: 'Invalid row' },
  { ...known, key: 'reconciliation', kind: 'RECONCILIATION_FAILURE', integration_id: fund, recorded_incident: true, reason: 'Material differences recorded' },
  { ...known, key: delivery, kind: 'MISSING_FILE', status: 'EXPECTED', recorded_incident: false, reason: 'The deadline passed with no recorded arrival.' },
  { ...known, key: conflict, kind: 'SOURCE_DELIVERY_ID_CONFLICT', recorded_incident: true, reason: 'Two payloads shared a source delivery ID' },
]

async function workspace(page: Page, role = 'OPERATOR', tooMany = false) {
  let acknowledged = false
  const attentionRequests: URL[] = []
  await page.route('**/api/auth/session', route => route.fulfill({ json: { id: 'operator', username: 'shift-operator', role, csrf: 'synthetic' } }))
  await page.route('**/api/dashboard/**', async route => {
    const url = new URL(route.request().url())
    const path = url.pathname
    if (path.endsWith('/stream')) return route.abort('failed')
    if (path.endsWith('/overview')) return route.fulfill({ json: {
      as_of: opened, metrics, counts: { COMPLETED: 8, PROCESSING: 1, PROCESSING_FAILED: 1 },
      incidents_by_type: { SOURCE_DELIVERY_ID_CONFLICT: 1, RECONCILIATION_FAILURE: 1, VALIDATION_FAILURE: 1 },
      integrations: [{ id: north, name: 'Northstar Treasury', active: true }, { id: fund, name: 'Fund Accounting', active: false }],
      activity: { [north]: { ...metrics, active_incidents: 2, last_arrival: opened }, [fund]: { ...metrics, active_incidents: 1 } },
    } })
    if (path.endsWith('/attention')) {
      attentionRequests.push(url)
      const scope = url.searchParams.get('integration_id')
      return route.fulfill({ json: tooMany ? [...issues, ...Array.from({ length: 37 }, (_, i) => ({
        ...issues[0], key: 'extra-' + i, reason: 'Validation fixture ' + i,
      }))] : issues.filter(item => !scope || item.integration_id === scope) })
    }
    if (path.endsWith('/activity')) return route.fulfill({ json: { items: [{
      source_event_id: 'activity1', delivery_expectation_id: delivery, summary: 'Reconciliation results committed',
      event_type: 'ReconciliationCompleted', occurred_at: opened, payload: { reconciliation_run_id: run },
    }] } })
    if (path.endsWith('/' + delivery)) return route.fulfill({ json: {
      id: delivery, integration_id: north, status: 'COMPLETED', delivery_type: 'CASH_LEDGER', current_file: null,
      business_date: '2026-11-23', deadline_at: deadline, expected_pattern: '*.csv',
    } })
    if (path.endsWith('/incidents')) return route.fulfill({ json: [{
      id: conflict, incident_type: 'SOURCE_DELIVERY_ID_CONFLICT', status: acknowledged ? 'ACKNOWLEDGED' : 'OPEN',
      severity: 'CRITICAL', reason: 'Two payloads shared a source delivery ID', opened_at: opened,
      acknowledgement_enabled: true, acknowledged_at: acknowledged ? opened : null, acknowledgement_comment: 'Reviewing evidence',
    }] })
    if (path.endsWith('/acknowledge')) {
      expect(route.request().headers()['x-csrf-token']).toBe('synthetic')
      expect(route.request().postDataJSON()).toEqual({ comment: 'Reviewing evidence' })
      acknowledged = true
      return route.fulfill({ json: { acknowledged_at: opened } })
    }
    return route.fulfill({ json: [] })
  })
  return attentionRequests
}

test('overview separates current and historical signals and links to evidence', async ({ page }) => {
  test.skip(live, 'Uses controlled operation results')
  await workspace(page)
  await page.goto('/overview')
  const snapshot = page.getByRole('region', { name: 'Operational snapshot' })
  await expect(snapshot).toContainText('1 critical · 1 high priority')
  await expect(snapshot).toContainText('9 of 10 recorded arrivals')
  await expect(snapshot).toContainText('1 processing · 1 processing failed')
  await expect(page.getByRole('region', { name: 'SLA history' })).toContainText('4Recorded SLA breaches')
  const integration = page.getByRole('region', { name: 'Integration health' })
  await expect(integration.getByRole('link', { name: 'Northstar Treasury' })).toHaveAttribute('href', '/deliveries?integration=' + north)
  await expect(integration.getByText('No arrival recorded')).toBeVisible()
  await expect(page.getByRole('link', { name: 'View run evidence' })).toHaveAttribute('href', '/reconciliation/runs/' + run)
  await page.getByRole('region', { name: 'Needs attention' }).getByRole('link', { name: 'Investigate incident' }).first().click()
  await expect(page).toHaveURL('/deliveries/' + delivery + '/incidents/' + conflict)
  await expect(page.locator('.delivery-workspace').getByText('Source delivery ID conflict · Open')).toBeVisible()
  await page.getByRole('link', { name: /^Back to / }).click()
  await expect(page).toHaveURL('/overview')
})

test('Action Center ranks the bounded slice and scopes filters to the correct data', async ({ page }) => {
  test.skip(live, 'Uses controlled queue ordering')
  const requests = await workspace(page)
  await page.goto('/action-center')
  const queue = page.getByRole('region', { name: 'Requires attention' })
  await expect(queue.locator('.ops-band > h3')).toHaveText([
    'Critical incidents1', 'High-priority incidents1', 'Overdue or missing1', 'Other operational issues1',
  ])
  await expect(queue.getByRole('region', { name: 'Critical incidents' })).toContainText('Delivery status Completed')
  await expect(queue.getByRole('region', { name: 'Overdue or missing' })).toContainText('Detected problem')
  await expect(queue.getByRole('region', { name: 'Overdue or missing' })).not.toContainText('Severity High')
  await page.getByLabel('Integration', { exact: true }).selectOption(north)
  await expect(queue).toContainText('3 shown of 3 loaded')
  await expect.poll(() => requests.at(-1)?.searchParams.get('integration_id')).toBe(north)
  await expect.poll(() => requests.at(-1)?.searchParams.get('limit')).toBe('41')
  await page.getByLabel('Issue scope').selectOption('recorded')
  await expect(queue).toContainText('2 shown of 3 loaded')
  await queue.getByRole('link', { name: 'Investigate incident' }).first().click()
  const detail = page.locator('.delivery-workspace')
  await detail.getByLabel('Comment (optional)').fill('Reviewing evidence')
  await detail.getByRole('button', { name: 'Acknowledge incident' }).click()
  await expect(detail.getByText('Source delivery ID conflict · Acknowledged')).toBeVisible()
  await page.reload()
  await expect(detail.getByText('Source delivery ID conflict · Acknowledged')).toBeVisible()
  await page.getByRole('link', { name: /^Back to / }).click()
  await expect(page).toHaveURL('/action-center?integration=' + north + '&issues=recorded')
  await expect(page.getByLabel('Issue scope')).toHaveValue('recorded')
})

test('Viewer can investigate but cannot acknowledge and sees a clear bounded scope', async ({ page }) => {
  test.skip(live, 'Uses controlled permission and look-ahead responses')
  await workspace(page, 'VIEWER', true)
  await page.goto('/action-center')
  await expect(page.getByText(/40 shown of 40 loaded.*first 40 server results/)).toBeVisible()
  await expect(page.getByText('Validation fixture 36', { exact: true })).toHaveCount(0)
  await page.getByRole('link', { name: 'Investigate incident' }).first().click()
  await expect(page.locator('.delivery-workspace').getByText('Source delivery ID conflict · Open')).toBeVisible()
  await expect(page.getByRole('button', { name: 'Acknowledge incident' })).toHaveCount(0)
})

async function checkResponsive(page: Page, screenshots?: string) {
  for (const [width, height] of [[1440, 1050], [1920, 1200], [2560, 1240], [768, 1024], [390, 844]]) {
    await page.setViewportSize({ width, height })
    for (const [route, heading] of [['overview', 'Operational snapshot'], ['action-center', 'Requires attention']]) {
      await page.goto('/' + route)
      await expect(page.getByRole('heading', { name: heading, exact: true })).toBeVisible()
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width)
      if (screenshots) {
        if (route === 'overview') await expect(page.getByRole('heading', { name: 'Integration health' })).toBeVisible()
        await expect(page.getByRole('link', { name: 'Investigate incident' }).first()).toBeVisible()
        await page.evaluate(() => document.fonts.ready)
        await page.screenshot({ path: join(screenshots, route + '-' + width + '.png'), animations: 'disabled' })
      }
    }
  }
}

test('briefing and queue fit desktop, ultrawide, tablet and mobile without horizontal overflow', async ({ page }) => {
  test.skip(live, 'Uses the controlled responsive fixture')
  await workspace(page)
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await checkResponsive(page)
})

test('real intake Stage 2 briefing and Action Center render isolated operational evidence', async ({ page }) => {
  test.skip(!live || process.env.DEMO_OPERATIONS !== '1' || process.env.DEMO_EVENTS !== '1', 'Requires the isolated synthetic demo')
  await page.goto('/overview')
  await page.getByLabel('Username', { exact: true }).fill('demo-admin')
  await page.getByLabel('Password', { exact: true }).fill(process.env.OPSBRIDGE_DEMO_PASSWORD!)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('region', { name: 'Operational snapshot' })).toContainText('critical')
  await expect(page.getByRole('region', { name: 'Integration health' })).toContainText('Northstar Treasury')
  await expect(page.getByRole('region', { name: 'Recent activity' }).locator('li').first()).toBeVisible()
  await checkResponsive(page, process.env.OPSBRIDGE_BRIEFING_SCREENSHOTS)
})
