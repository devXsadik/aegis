import { expect, test } from '@playwright/test'

// Phase 7.6: search needs a reason; results lead to a lookout that boosts the cameras.
test('operator searches white cars with a reason, then starts and ends a lookout', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Username').fill('e2e_desk')
  await page.getByLabel('Password').fill('e2e-pass-12345')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Home' })).toBeVisible()
  await page.goto('/#/search')
  const search = page.getByRole('button', { name: 'Search', exact: true })
  await page.getByRole('group', { name: 'Colour' }).getByRole('button', { name: 'White' }).click()
  await expect(search).toBeDisabled()                                     // no reason yet
  await page.getByLabel('Reason / case number (required)').fill('Gulshan FIR 77/2026 tracing')
  await search.click()
  await expect(page.getByText('2 detection(s)')).toBeVisible()
  await expect(page.locator('.vs-card').first()).toContainText('white')
  await page.screenshot({ path: 'test-results/vehicle-search.png', fullPage: true })
  await page.locator('.vs-card').first().getByRole('button', { name: 'Lookout' }).click()
  const dlg = page.getByRole('dialog', { name: 'Start a live lookout' })
  await dlg.getByRole('button', { name: 'Start lookout' }).click()
  const toast = page.getByText(/Lookout B-[0-9A-F]+ active on 1 camera/)
  await expect(toast).toBeVisible()
  const ref = (await toast.textContent()).match(/B-[0-9A-F]+/)[0]
  const active = page.locator('.wl-item').filter({ hasText: ref })
  await expect(active).toHaveCount(1)
  await active.getByRole('button', { name: 'End' }).click()
  await expect(page.getByText(/ended/)).toBeVisible()
})
