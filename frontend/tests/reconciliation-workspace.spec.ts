import { join } from 'node:path'
import { expect, test, type Page } from '@playwright/test'

const live = Boolean(process.env.DASHBOARD_URL)
const previous = '853007a4-65b7-465a-86c7-52986a7b8a21'
const selected = '6124a3c9-269a-4562-a2b9-b8959abd60d7'
const delivery = 'ee08d4ed-baf1-47fe-b12e-dd358287bb4c'
const pin = 'b2fae6ff-d17a-4edb-9a90-ef2ab6f46dc3'
const date = '2026-11-23T09:00:00Z'
const prefix = '/reconciliation/runs/'
const outcome = { status: 'COMPLETED', attempts: 1, created_at: date, finished_at: date, error_code: null }
const original = { ...outcome, id: previous, name: 'Original review', counts: { EXACT: 1, AMOUNT_MISMATCH: 2 }, parent_id: null }
const corrected = { ...outcome, id: selected, name: 'Corrected review', counts: { EXACT: 2 }, parent_id: previous }
const difference = { index: 23, category: 'AMOUNT_MISMATCH', count_a: 1, count_b: 1, difference: '-9007199254740993.000001', currency: 'EUR' }

async function mockRuns(page: Page, role: string, providers = 'mock') {
  const reruns: string[] = []
  let calls = 0
  await page.route('**/api/auth/session', route => route.fulfill({ json: { id: 'test', username: 'synthetic', role, csrf: 'fixture' } }))
  await page.route('**/api/dashboard/**', route => {
    const url = new URL(route.request().url())
    const path = url.pathname.replace('/api/dashboard', '')
    if (path === '/overview') return route.fulfill({ json: { integrations: [] } })
    if (path === '/reconciliation') return route.fulfill({ json: { items: [corrected, original], has_more: false, rerun_enabled: true } })
    if (path === '/copilot/status') return route.fulfill({ json: { provider: providers } })
    if (path === '/copilot/investigate') { calls++; return route.abort() }
    if (path.endsWith('/rerun')) {
      expect(route.request().headers()['x-csrf-token']).toBe('fixture')
      expect(route.request().postDataJSON().confirmed).toBe(true)
      reruns.push(route.request().postDataJSON().request_id)
      return reruns.length === 1 ? route.abort() : route.fulfill({ status: 202, json: { run_id: selected } })
    }
    if (path.startsWith(prefix)) {
      const isPrevious = path.endsWith(previous)
      const category = url.searchParams.get('category')
      const offset = url.searchParams.get('offset')
      const items = isPrevious && (category === 'AMOUNT_MISMATCH' || (!category && offset === '22')) ? [difference] : []
      return route.fulfill({ json: {
        ...(isPrevious ? original : corrected), match_on: 'reference', tolerance: '0.010000', material: isPrevious,
        file_a_id: pin, file_b_id: null, sources: [{ id: delivery, integration: 'Synthetic Custodian',
          delivery_type: 'POSITIONS', business_date: '2026-11-23', status: 'COMPLETED' }], items, has_more: false,
      } })
    }
    if (path === '/deliveries/' + delivery) return route.fulfill({ json: {
      id: delivery, delivery_type: 'POSITIONS', business_date: '2026-11-23', status: 'COMPLETED', deadline_at: date, current_file: null,
    } })
    return route.fulfill({ json: [] })
  })
  return { reruns, copilotCalls: () => calls }
}

test('history separates execution and outcomes and compares only recorded totals', async ({ page }) => {
  test.skip(live, 'Uses controlled run reports')
  const actions = await mockRuns(page, 'VIEWER', 'openai')
  await page.goto('/reconciliation')
  await expect(page.getByRole('row').filter({ hasText: 'Corrected review' })).toContainText('No exceptions recorded')
  await expect(page.getByRole('row').filter({ hasText: 'Original review' })).toContainText('Exceptions recorded')
  await page.getByRole('link', { name: 'Corrected review' }).click()
  const comparison = page.getByRole('region', { name: 'Immediate predecessor comparison' })
  await expect(comparison.getByRole('row').filter({ hasText: 'Exception groups' }).getByRole('cell')).toHaveText(['2', '0', '-2'])
  await expect(comparison).toContainText('Individual exceptions cannot be paired')
  await comparison.getByRole('link', { name: 'View preceding run' }).click()
  await page.getByLabel('Result category').selectOption('EXACT')
  await expect(page).toHaveURL(/category=EXACT/)
  await page.goto(prefix + previous + '?category=EXACT&exception=23')
  const group = page.getByRole('region', { name: 'Group 23 evidence' })
  await expect(group).toContainText('-9007199254740993.000001 EUR')
  await expect(group).toBeFocused()
  await group.getByText('Investigate exception with Copilot', { exact: true }).click()
  await expect(group.getByText('Simulation unavailable')).toBeVisible()
  await expect(group.getByRole('button', { name: 'Analyze exception' })).toBeDisabled()
  expect(actions.copilotCalls()).toBe(0)
  await expect(page.getByRole('button', { name: 'Queue reconciliation rerun' })).toHaveCount(0)
  await page.getByText('Pinned file ID', { exact: true }).click()
  await expect(page.getByText(pin, { exact: true })).toBeVisible()
  await page.getByRole('link', { name: 'View source A delivery' }).click()
  await expect(page).toHaveURL('/deliveries/' + delivery)
  await page.goBack()
  await expect(group).toBeVisible()
  await page.reload()
  await expect(group).toBeVisible()
  await page.goForward()
  await expect(page).toHaveURL('/deliveries/' + delivery)
})

test('explicit rerun confirmation and request identity survive an uncertain response', async ({ page }) => {
  test.skip(live, 'Uses controlled rerun responses')
  const { reruns } = await mockRuns(page, 'OPERATOR')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(prefix + previous)
  const button = page.getByRole('button', { name: 'Queue reconciliation rerun' })
  await expect(button).toBeDisabled()
  await page.getByLabel('Confirm a new reconciliation run').check()
  await button.click()
  await expect(page.getByRole('alert')).toContainText('Retrying uses the same request ID')
  await button.click()
  await expect(page).toHaveURL(prefix + selected)
  expect(reruns).toHaveLength(2)
  expect(reruns[1]).toBe(reruns[0])
  await expect(page.getByRole('region', { name: 'Immediate predecessor comparison' })).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390)
})

test('real intake reconciliation history and comparison fit desktop tablet and mobile', async ({ page }) => {
  test.skip(!live || process.env.DEMO_RECONCILIATION !== '1', 'Requires the isolated synthetic demo')
  await page.goto('/reconciliation')
  await page.getByLabel('Username', { exact: true }).fill('demo-admin')
  await page.getByLabel('Password', { exact: true }).fill(process.env.OPSBRIDGE_DEMO_PASSWORD!)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Sign out' })).toBeVisible()
  const directory = process.env.OPSBRIDGE_RECONCILIATION_SCREENSHOTS
  for (const [width, height] of [[1440, 1050], [768, 1024], [390, 844]]) {
    await page.setViewportSize({ width, height })
    await page.goto('/reconciliation')
    const originalLink = page.getByRole('row').filter({ hasNotText: 'Has a preceding run' })
      .getByRole('link', { name: 'Fund vs Custodian · exception review', exact: true })
    const correctedLink = page.getByRole('link', { name: 'Fund vs Custodian · corrected exports', exact: true })
    await expect(page.getByRole('row').filter({ hasText: 'fully matched' }).first()).toContainText('No exceptions recorded')
    await expect(originalLink).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width)
    if (directory) await page.screenshot({ path: join(directory, 'reconciliation-history-' + width + '.png'), animations: 'disabled' })
    await originalLink.click()
    await expect(page.getByRole('link', { name: /Inspect group/ }).first()).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width)
    if (directory) await page.screenshot({ path: join(directory, 'reconciliation-run-' + width + '.png'), animations: 'disabled' })
    await page.getByRole('link', { name: 'Back to run history' }).click()
    await correctedLink.click()
    const comparison = page.getByRole('region', { name: 'Immediate predecessor comparison' })
    await expect(comparison.getByRole('row').filter({ hasText: 'Exception groups' }).getByRole('cell')).toHaveText(['5', '0', '-5'])
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width)
    if (directory) await comparison.screenshot({ path: join(directory, 'reconciliation-comparison-' + width + '.png'), animations: 'disabled' })
  }
  const runUrl = page.url()
  await page.getByRole('link', { name: 'View source A delivery' }).click()
  await expect(page).toHaveURL(/\/deliveries\/[0-9a-f-]{36}$/)
  await expect(page.getByRole('region', { name: 'Current file' })).toBeVisible()
  await page.goBack()
  await expect(page).toHaveURL(runUrl)
  await expect(page.getByRole('region', { name: 'Immediate predecessor comparison' })).toBeVisible()
})
