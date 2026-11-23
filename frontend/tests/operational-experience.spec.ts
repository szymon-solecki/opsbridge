import { join } from 'node:path'
import { expect, test, type Page } from '@playwright/test'

const live = Boolean(process.env.DASHBOARD_URL)
const delivery = 'cf6b6570-eb42-4f72-b877-4d6b4a320b6e'
const incident = 'f7a4aca0-a263-4085-b954-7856380eadf8'
const run = '4c157a7b-2e8d-47b2-9b8c-fc6d04b9e146'
const date = '2026-11-23T09:15:00Z'
const policy = [{
  integration_id: null, incident_type: null, severity: null,
  opened: [{ owner: 'Shift desk', email: 'shift@ops.test' }], resolved: [],
  escalations: [{ after_seconds: 60, recipients: [{ owner: 'Duty lead', email: 'lead@ops.test' }] },
    { after_seconds: 120, recipients: [{ owner: 'Duty manager', email: 'manager@ops.test' }] }],
}]
async function session(page: Page, role = 'ADMIN') {
  await page.route('**/api/auth/session', route => route.fulfill({ json: { id: 'admin', username: 'synthetic', role, csrf: 'fixture' } }))
}

test('Copilot citations open evidence, preserve identifiers and navigate to verified records', async ({ page }) => {
  test.skip(live, 'Uses controlled Copilot references')
  await session(page, 'VIEWER')
  await page.route('**/api/dashboard/**', route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/copilot/status')) return route.fulfill({ json: { provider: 'mock' } })
    if (path.endsWith('/copilot/investigate')) return route.fulfill({ json: {
      provider: 'mock', summary: 'One incident needs review.', summary_references: ['E1'], observations: ['E1'],
      hypotheses: [{ key: 'check', hypothesis: 'Delivery may be late.', next_step: 'Check the vendor handoff.', references: ['E2'] }],
      evidence: [
        { ref: 'E1', kind: 'incident', record_id: incident, delivery_id: delivery, timestamp: date, fact: 'An incident is recorded.' },
        { ref: 'E2', kind: 'reconciliation_exception', record_id: run + ':4', timestamp: date, fact: 'An amount mismatch is recorded.' },
        { ref: 'E3', kind: 'file', record_id: delivery, timestamp: date, fact: 'A historical file is recorded.' },
      ], missing_evidence: ['The handoff record is unavailable.'], truncated: true,
    } })
    if (path.endsWith('/deliveries/' + delivery)) return route.fulfill({ json: {
      id: delivery, integration_id: delivery, status: 'EXPECTED', delivery_type: 'POS', business_date: '2026-11-23', deadline_at: date,
    } })
    if (path.endsWith('/incidents')) return route.fulfill({ json: [{
      id: incident, incident_type: 'MISSING_FILE', status: 'OPEN', reason: 'Awaiting file', opened_at: date,
    }] })
    if (path.endsWith('/overview')) return route.fulfill({ json: { integrations: [] } })
    return route.fulfill({ json: [] })
  })
  await page.goto('/copilot')
  await expect(page.getByText('Simulated analysis', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Which integrations currently have unresolved incidents?' }).click()
  await page.getByRole('button', { name: 'Ask Copilot' }).click()
  await expect(page.getByRole('heading', { name: 'Operational conclusion' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Which integrations currently have unresolved incidents?' })).toBeHidden()
  await expect(page.getByRole('heading', { name: 'Recommended next steps' })).toBeVisible()
  await expect(page.getByText(incident, { exact: true })).toBeHidden()
  await page.getByRole('link', { name: 'E1 · Incident' }).first().click()
  const card = page.getByRole('article').filter({ has: page.getByRole('heading', { name: 'E1 · Incident' }) })
  await expect(card).toBeFocused()
  await card.getByText('Technical identifier', { exact: true }).click()
  await expect(card.getByText(incident, { exact: true })).toBeVisible()
  await expect(page.getByRole('link', { name: 'Open exception group' })).toHaveAttribute('href', '/reconciliation/runs/' + run + '?exception=4')
  await expect(page.getByRole('link', { name: 'Open delivery evidence' })).toHaveCount(0)
  await card.getByRole('link', { name: 'Open incident evidence' }).click()
  await expect(page).toHaveURL('/deliveries/' + delivery + '/incidents/' + incident)
  await expect(page.locator('.selected-incident')).toBeFocused()
  await expect(page.getByRole('link', { name: 'Back to AI Copilot' })).toHaveAttribute('href', '/copilot')
  await page.goBack()
  await expect(page).toHaveURL('/copilot')
})

test('Monitoring separates observed data, absent metrics and configured destinations', async ({ page }) => {
  test.skip(live, 'Uses controlled monitoring observations')
  await session(page, 'VIEWER')
  await page.route('**/opsbridge-monitoring.json', route => route.fulfill({ json: {
    grafana: 'https://grafana.ops.test/d/operations', prometheus: 'https://operator:password@metrics.ops.test/',
  } }))
  await page.route('**/api/dashboard/**', route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/overview')) return route.fulfill({ json: { integrations: [], counts: { PROCESSING: 2 } } })
    if (path.endsWith('/activity')) return route.fulfill({ status: 503 })
    return route.abort()
  })
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/monitoring')
  await expect(page.getByText('Last read succeeded')).toBeVisible()
  await expect(page.getByText('Unavailable in workspace', { exact: true })).toHaveCount(2)
  await expect(page.getByText('Activity is unavailable.')).toBeVisible()
  const link = page.getByRole('link', { name: 'Open Grafana (new tab)' })
  await expect(link).toHaveAttribute('href', 'https://grafana.ops.test/d/operations')
  await expect(link).toHaveAttribute('rel', 'noopener noreferrer')
  await expect(page.getByRole('link', { name: 'Open Prometheus (new tab)' })).toHaveCount(0)
  await expect(page.getByText('Destination not configured or invalid')).toBeVisible()
  await page.reload()
  await expect(link).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
})

test('Administration confirms account edits and reviews structured policy changes before saving', async ({ page }) => {
  test.skip(live, 'Uses controlled administrative actions')
  await session(page)
  let changes = 0
  let saves = 0
  await page.route('**/api/auth/operators**', route => {
    if (route.request().method() === 'PATCH') {
      changes++
      expect(route.request().postDataJSON()).toEqual({ role: 'OPERATOR' })
      expect(route.request().headers()['x-csrf-token']).toBe('fixture')
      return route.fulfill({ json: {} })
    }
    return route.fulfill({ json: [{ id: 'admin', username: 'demo-admin', role: 'ADMIN', active: true },
      { id: 'viewer', username: 'reviewer', role: 'VIEWER', active: true }] })
  })
  await page.route('**/api/dashboard/notification-policies', route => {
    if (route.request().method() !== 'PUT') return route.fulfill({ json: { rules: policy } })
    saves++
    expect(route.request().headers()['x-csrf-token']).toBe('fixture')
    expect(route.request().postDataJSON()).toEqual([{ ...policy[0], opened: null }])
    return route.fulfill({ json: { rules: route.request().postDataJSON() } })
  })
  await page.goto('/administration')
  await expect(page.getByLabel('demo-admin role')).toBeDisabled()
  await page.getByLabel('reviewer role').selectOption('OPERATOR')
  expect(changes).toBe(0)
  await page.getByRole('button', { name: 'Confirm account change' }).click()
  await expect(page.getByText('Account updated.')).toBeVisible()
  expect(changes).toBe(1)
  await page.getByRole('link', { name: 'Notification policies' }).click()
  await page.reload()
  await page.getByRole('button', { name: 'Edit policies', exact: true }).click()
  await page.getByLabel('Opening notifications behavior').selectOption('inherit')
  await page.getByLabel('Delay in seconds').last().fill('30')
  await page.getByRole('button', { name: 'Review changes' }).click()
  await expect(page.getByRole('alert')).toContainText('strictly increasing delays')
  await page.getByLabel('Delay in seconds').last().fill('120')
  await page.getByRole('button', { name: 'Review changes' }).click()
  await expect(page.getByRole('region', { name: 'Review pending policy changes' })).toContainText('Inherit matching rule')
  expect(saves).toBe(0)
  await page.getByRole('button', { name: 'Save notification policy' }).click()
  await expect(page.getByText('Notification policy saved.')).toBeVisible()
  expect(saves).toBe(1)
  await page.goBack()
  await expect(page.getByRole('heading', { name: 'Operator accounts' })).toBeVisible()
})

test('real intake operational experience renders simulated evidence and administration at three widths', async ({ page }) => {
  test.skip(!live || process.env.DEMO_OPERATIONS !== '1' || process.env.DEMO_EVENTS !== '1', 'Requires the isolated synthetic demo')
  await page.goto('/copilot')
  await page.getByLabel('Username', { exact: true }).fill('demo-admin')
  await page.getByLabel('Password', { exact: true }).fill(process.env.OPSBRIDGE_DEMO_PASSWORD!)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByText('Simulated analysis', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Which deliveries breached their SLA?' }).click()
  await page.getByRole('button', { name: 'Ask Copilot' }).click()
  await expect(page.getByRole('heading', { name: 'Operational conclusion' })).toBeVisible()
  await page.getByLabel('Investigation result').getByRole('link').first().click()
  await expect(page.getByRole('link', { name: 'Open delivery evidence' }).first()).toBeVisible()
  await page.mouse.wheel(0, -10000)
  const directory = process.env.OPSBRIDGE_EXPERIENCE_SCREENSHOTS
  async function capture(name: string) {
    for (const [width, height] of [[1440, 1050], [768, 1024], [390, 844]]) {
      await page.setViewportSize({ width, height })
      await page.evaluate(() => window.scrollTo(0, 0))
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width)
      if (directory) await page.screenshot({ path: join(directory, name + '-' + width + '.png'), animations: 'disabled' })
    }
  }
  await capture('copilot')
  await page.goto('/monitoring')
  await expect(page.getByText('Last read succeeded')).toBeVisible()
  await expect(page.getByText('Destination not configured or invalid')).toHaveCount(2)
  await capture('monitoring')
  await page.goto('/administration')
  await expect(page.getByLabel('demo-admin role')).toBeDisabled()
  await capture('accounts')
  await page.getByRole('link', { name: 'Notification policies' }).click()
  await expect(page.getByRole('button', { name: 'Edit policies', exact: true })).toBeVisible()
  await capture('notification-policies')
})
