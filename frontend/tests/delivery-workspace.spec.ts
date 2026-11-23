import { join } from 'node:path'
import { expect, test } from '@playwright/test'

const live = Boolean(process.env.DASHBOARD_URL)
const integration = 'd3389e1c-6187-444b-a595-23563d7b82d9'
const delivery = 'c535be02-198a-4fc6-a534-371031c83e89'
const incident = 'dd6a0e2e-3bd6-4d02-b3c4-6fd044b38f23'
const deadline = '2026-11-23T09:00:00Z'
const root = '/deliveries/' + delivery
const record = {
  id: delivery, integration_id: integration, delivery_type: 'CUSTODY_POSITIONS', business_date: '2026-11-23',
  status: 'COMPLETED', deadline_at: deadline, overdue_at: deadline, expected_pattern: '*.csv',
  current_file: { id: 'current-file', original_name: 'positions.csv', size_bytes: 47, received_at: '2026-11-23T10:30:00Z',
    content_hash: 'a'.repeat(64), status: 'COMPLETED', attempt_series: 2, attempt_count_in_series: 1,
    replaces_file_id: 'prior-file' },
}

test('delivery evidence keeps queue scope, chronological history and a directly focused incident', async ({ page }) => {
  test.skip(live, 'Uses controlled delivery evidence')
  await page.route('**/api/auth/session', route => route.fulfill({ json: {
    id: 'fixture', username: 'viewer', role: 'VIEWER', csrf: 'synthetic',
  } }))
  await page.route('**/api/dashboard/**', route => {
    const url = new URL(route.request().url())
    const path = url.pathname.replace('/api/dashboard', '')
    if (path === '/overview') return route.fulfill({ json: { integrations: [{ id: integration, name: 'Treasury', active: true }] } })
    if (path === '/deliveries') {
      expect(url.searchParams.has('search')).toBe(false)
      return route.fulfill({ json: [record] })
    }
    if (path === root) return route.fulfill({ json: record })
    if (path === root + '/incidents') return route.fulfill({ json: [{
      id: incident, incident_type: 'SOURCE_DELIVERY_ID_CONFLICT', status: 'OPEN', severity: 'CRITICAL',
      reason: 'The source ID is already in use.', opened_at: deadline, acknowledgement_enabled: true,
    }] })
    if (path === root + '/events') return route.fulfill({ json: [{
      id: 'event-first', delivery_id: delivery, event_type: 'FileValidationFailed', occurred_at: deadline,
      filename: 'prior.csv', file_id: 'prior-file', details: { error_code: 'CSV_ROW_INVALID' },
    }, {
      id: 'event-second', delivery_id: delivery, event_type: 'FileProcessingCompleted', occurred_at: '2026-11-23T10:30:00Z',
      filename: 'positions.csv', file_id: 'current-file', replaces_file_id: 'prior-file',
      details: { attempt_series: 2, attempt_count_in_series: 1 },
    }] })
    return route.abort()
  })
  await page.setViewportSize({ width: 390, height: 844 })
  const queue = '/deliveries?integration=' + integration + '&status=COMPLETED&sort=deadline'
  await page.goto(queue)
  const search = page.getByLabel('Search this page')
  await search.fill('absent')
  await expect(page.getByText('No matching deliveries')).toBeVisible()
  await search.fill('positions.csv')
  await expect(page.getByText('Page 1 · 1 shown of 1 loaded · Search applies to this page')).toBeVisible()
  const row = page.getByRole('link', { name: 'Custody positions' })
  await row.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { name: 'Custody positions', level: 1 })).toBeFocused()
  await expect(page.getByRole('region', { name: 'Arrival and SLA' })).toContainText('Recorded breach')
  await expect(page.getByRole('region', { name: 'Delivery timeline' }).locator('li').first()).toContainText('File Validation Failed')
  await expect(page.getByRole('region', { name: 'Delivery timeline' }).locator('li').last()).toContainText('Series 2 · 1 of 3 attempts')
  await expect(page.getByRole('button', { name: 'Acknowledge incident' })).toHaveCount(0)
  await page.getByText('Incident identifiers').click()
  await page.getByRole('link', { name: 'Open this incident directly' }).click()
  await expect(page.locator('.selected-incident')).toBeFocused()
  await page.reload()
  await expect(page.locator('.selected-incident')).toBeFocused()
  await page.goBack()
  await expect(page).toHaveURL(new RegExp(root + '\\?'))
  await page.goBack()
  await expect(search).toHaveValue('positions.csv')
  await page.goForward()
  await expect(page.getByRole('heading', { name: 'Custody positions', level: 1 })).toBeVisible()
  await page.goForward()
  await expect(page).toHaveURL(new RegExp(root + '/incidents/' + incident))
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
})

test('a linked older incident remains reachable through bounded history pages', async ({ page }) => {
  test.skip(live, 'Uses controlled incident pages')
  await page.route('**/api/auth/session', route => route.fulfill({ json: { id: 'fixture', username: 'viewer', role: 'VIEWER' } }))
  await page.route('**/api/dashboard/**', route => {
    const url = new URL(route.request().url())
    if (url.pathname.endsWith('/overview')) return route.fulfill({ json: { integrations: [] } })
    if (url.pathname.endsWith(root)) return route.fulfill({ json: record })
    if (url.pathname.endsWith('/incidents')) {
      const older = url.searchParams.get('offset') === '100'
      expect(url.searchParams.get('limit')).toBe('100')
      const missing = { id: incident, incident_type: 'MISSING_FILE', status: 'RESOLVED', reason: 'Arrival recorded.', opened_at: deadline }
      return route.fulfill({ json: older ? [missing] : Array.from({ length: 100 }, (_, i) => ({
        ...missing, id: 'newer-' + i,
      })) })
    }
    return route.fulfill({ json: [] })
  })
  await page.goto(root + '/incidents/' + incident)
  await expect(page.getByText('The linked incident is outside the loaded records or is unavailable.')).toBeVisible()
  await page.getByRole('button', { name: 'Older incidents' }).click()
  await expect(page).toHaveURL(/incident_offset=100$/)
  await expect(page.locator('.selected-incident')).toContainText('Missing or overdue · Resolved')
  await page.reload()
  await expect(page.locator('.selected-incident')).toBeFocused()
})

test('real intake delivery workspace displays queue, file and incident evidence at desktop and mobile widths', async ({ page }) => {
  test.skip(!live || process.env.DEMO_OPERATIONS !== '1', 'Requires the isolated synthetic demo')
  await page.goto('/deliveries')
  await page.getByLabel('Username', { exact: true }).fill('demo-admin')
  await page.getByLabel('Password', { exact: true }).fill(process.env.OPSBRIDGE_DEMO_PASSWORD!)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible()
  const directory = process.env.OPSBRIDGE_DELIVERY_SCREENSHOTS
  for (const [width, height] of [[1440, 1050], [768, 1024], [390, 844]]) {
    await page.setViewportSize({ width, height })
    await page.goto('/deliveries')
    if (width <= 672) await page.getByRole('combobox', { name: 'Integration', exact: true }).selectOption({ label: 'Northstar Treasury' })
    else await page.getByRole('button', { name: 'Northstar Treasury', exact: true }).click()
    const row = page.getByRole('link', { name: 'Payment register', exact: true })
    await expect(row).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width)
    if (directory) await page.screenshot({ path: join(directory, 'delivery-queue-' + width + '.png'), animations: 'disabled' })
    await row.click()
    await expect(page.getByRole('heading', { name: 'Payment register', level: 1 })).toBeVisible()
    await expect(page.getByRole('region', { name: 'Current file' }).getByText(/payment_register.*\.csv$/)).toBeVisible()
    await expect(page.getByRole('heading', { name: 'Source delivery ID conflict · Open' })).toBeVisible()
    await expect(page.getByRole('region', { name: 'Delivery timeline' }).getByText('File Received', { exact: true })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width)
    if (directory) await page.screenshot({ path: join(directory, 'delivery-evidence-' + width + '.png'), animations: 'disabled' })
    await page.getByText('Incident identifiers', { exact: true }).click()
    await page.getByRole('link', { name: 'Open this incident directly' }).click()
    await expect(page.locator('.selected-incident')).toBeFocused()
    if (directory && width === 390) await page.screenshot({ path: join(directory, 'delivery-incident-390.png'), animations: 'disabled' })
  }
})
