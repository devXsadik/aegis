import { expect, test } from '@playwright/test'

// Phase 5: camera health, registry editor (heading dial, capabilities, webhook token), CSV import.
async function signIn(page, user) {
  await page.goto('/')
  await page.getByLabel('Username').fill(user)
  await page.getByLabel('Password').fill('e2e-pass-12345')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Home' })).toBeVisible()
}

test('admin edits a camera in the registry and checks a CSV before importing', async ({ page }) => {
  await signIn(page, 'e2e_admin')
  await page.goto('/#/cameras')
  await page.getByRole('button', { name: 'Health' }).click()
  await expect(page.getByRole('group', { name: 'Filter by status' })).toBeVisible()
  const row = page.getByRole('row').filter({ hasText: 'e2e_lab' })
  await row.getByRole('button', { name: 'Registry' }).click()
  const dlg = page.getByRole('dialog', { name: /Registry — Lab gate/ })
  const dial = dlg.getByRole('slider', { name: 'Camera heading' })
  await dial.focus()
  for (let i = 0; i < 6; i++) await page.keyboard.press('Shift+ArrowRight')     // 0° → 90°
  await expect(dial).toHaveAttribute('aria-valuetext', '90° E')
  await dlg.getByLabel('Number plates').check()
  await dlg.getByRole('button', { name: 'Issue token' }).click()
  await expect(dlg.getByText('X-Camera-Token:')).toBeVisible()
  await page.screenshot({ path: 'test-results/camera-registry.png' })
  await dlg.getByRole('button', { name: 'Save' }).click()
  await expect(page.getByText('Lab gate saved')).toBeVisible()

  await page.getByRole('button', { name: 'Import CSV' }).click()
  const imp = page.getByRole('dialog', { name: 'Import cameras from CSV' })
  await imp.getByLabel(/CSV file/).setInputFiles({
    name: 'cams.csv', mimeType: 'text/csv',
    buffer: Buffer.from('camera_id,name,lat,lng,capabilities\ncsv_one,One,23.79,90.41,anpr\ncsv_two,Two,123,90,laser\n'),
  })
  await expect(imp.getByText('unknown capabilities: laser')).toBeVisible()
  await expect(imp.getByRole('button', { name: /Import/ })).toBeDisabled()
})
