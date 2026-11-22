import { expect, test } from '@playwright/test'

// The shift's core loop: sign in, see what needs review, decide, open a case.
test('operator signs in, confirms a repeated watchlist match, and opens an incident', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Username').fill('e2e_operator')
  await page.getByLabel('Password').fill('e2e-pass-12345')
  await page.getByRole('button', { name: 'Sign in' }).click()

  // Session is an httpOnly cookie: present for requests, invisible to scripts.
  await expect(page.getByRole('heading', { name: 'Home' })).toBeVisible()
  expect(await page.evaluate(() => document.cookie)).not.toContain('aegis_session')

  // Every page is in the sidebar; the Alerts entry carries the "needs action" count.
  const alertsNav = page.getByRole('complementary', { name: 'Main navigation' }).getByRole('button', { name: /Alerts/ })
  await expect(alertsNav).toContainText('3')                    // 3 alerts waiting

  await alertsNav.click()
  const queue = page.getByRole('listbox', { name: 'Alerts' })
  const match = queue.getByRole('option', { name: /Watchlist match/ })
  await expect(match).toContainText('×2')                       // two alerts, one decision
  await expect(page.getByText('2 entries · 3 alerts')).toBeVisible()
  await match.click()
  await expect(page.getByText('Your decision applies to all 2.')).toBeVisible()

  await page.keyboard.press('v')
  await page.getByRole('button', { name: /Confirm.*all 2/ }).click()
  await expect(page.getByText('Alert confirmed (2 alerts)')).toBeVisible()
  await expect(queue.getByRole('option')).toHaveCount(1)        // only the loitering alert is left

  await queue.getByRole('option', { name: /Suspicious behavior/ }).click()
  await page.keyboard.press('i')
  await expect(page.getByText('Incident created')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Incidents' })).toBeVisible()
  await expect(page.locator('.page-view')).toContainText(/Lab|Suspicious/i)

  // Reload keeps the session (cookie), sign-out ends it.
  await page.reload()
  await expect(page.getByRole('heading', { name: 'Incidents' })).toBeVisible()
  await page.getByRole('button', { name: 'Account menu' }).click()
  await page.getByRole('menuitem', { name: 'Sign out' }).click()
  await expect(page.getByRole('button', { name: 'Sign in' })).toBeVisible()
})
