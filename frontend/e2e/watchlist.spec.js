import { expect, test } from '@playwright/test'

// Phase 6: watchlist entries need legal details and a second person's approval.
async function signIn(page, user) {
  await page.goto('/')
  await page.getByLabel('Username').fill(user)
  await page.getByLabel('Password').fill('e2e-pass-12345')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Home' })).toBeVisible()
}

test('operator requests a vehicle with a Bangla plate; supervisor approves it', async ({ browser }) => {
  const op = await (await browser.newContext()).newPage()
  await signIn(op, 'e2e_desk')
  await op.goto('/#/settings')
  await op.getByRole('navigation', { name: 'Settings sections' }).getByRole('button', { name: /Watchlists/ }).click()
  await op.locator('.settings-content').getByRole('button', { name: 'Vehicles', exact: true }).click()
  await op.getByRole('button', { name: 'Add vehicle' }).click()
  const dlg = op.getByRole('dialog', { name: 'Add vehicle to the watchlist' })
  await dlg.getByLabel('Number plate (Bangla or English)').fill('Dhaka Metro Ga 12-3456')
  await expect(dlg.locator('.plate-plate')).toHaveText('ঢাকা মেট্রো-গ ১২-৩৪৫৬')
  await expect(dlg.getByText('DHAKA-METRO-GA-12-3456')).toBeVisible()
  await dlg.getByLabel('Type').selectOption('microbus')
  await dlg.getByRole('radio', { name: 'White' }).first().click()
  const send = dlg.getByRole('button', { name: 'Send for approval' })
  await expect(send).toBeDisabled()                                   // legal details missing
  await dlg.getByLabel('Case / FIR / GD number').fill('Gulshan FIR 77/2026')
  await dlg.getByLabel('Issuing authority').fill('DMP Gulshan')
  await dlg.getByLabel(/Legal basis — which law/).fill('Arrest warrant 12/2026, CMM Court Dhaka')
  await op.screenshot({ path: 'test-results/watchlist-vehicle-form.png' })
  await send.click()
  await expect(op.getByText(/sent for approval/)).toBeVisible()
  await expect(op.locator('.wl-item').getByText('Pending approval').first()).toBeVisible()

  const sup = await (await browser.newContext()).newPage()
  await signIn(sup, 'e2e_supervisor')
  await sup.goto('/#/settings')
  await sup.getByRole('navigation', { name: 'Settings sections' }).getByRole('button', { name: /Watchlists/ }).click()
  const queue = sup.locator('.wl-item').filter({ hasText: 'ঢাকা মেট্রো-গ ১২-৩৪৫৬' })
  await queue.getByRole('button', { name: 'Approve' }).click()
  await sup.getByRole('button', { name: 'Approve and activate' }).click()
  await expect(sup.getByText(/approved/)).toBeVisible()
  await sup.locator('.settings-content').getByRole('button', { name: 'Vehicles', exact: true }).click()
  await expect(sup.locator('.wl-item').filter({ hasText: 'ঢাকা মেট্রো-গ ১২-৩৪৫৬' }).getByText('Active — alerting')).toBeVisible()
  await sup.screenshot({ path: 'test-results/watchlist-approved.png', fullPage: true })
})

test('a criminal profile needs a request before it can alert', async ({ page }) => {
  await signIn(page, 'e2e_desk')
  await page.goto('/#/settings')
  await page.getByRole('navigation', { name: 'Settings sections' }).getByRole('button', { name: /Watchlists/ }).click()
  const row = page.locator('.wl-item').filter({ hasText: 'Kalam Sheikh' })
  await expect(row.getByText('Not requested')).toBeVisible()
  await row.getByRole('button', { name: 'Request entry' }).click()
  const dlg = page.getByRole('dialog', { name: /Watchlist request — Kalam Sheikh/ })
  await dlg.getByLabel('Case / FIR / GD number').fill('Mirpur GD 5/2026')
  await dlg.getByLabel('Issuing authority').fill('DMP Mirpur')
  await dlg.getByLabel(/Legal basis — which law/).fill('Warrant of arrest, Section 75 CrPC')
  await dlg.getByRole('button', { name: 'Send for approval' }).click()
  await expect(row.getByText('Pending approval')).toBeVisible()
  await expect(row.getByRole('button', { name: 'Approve' })).toHaveCount(0)   // operator cannot approve
})
