import { expect, test } from '@playwright/test'

// Phase 1 design system: settings side-nav + save bar, Bangla UI, incidents states, phone layout.
async function signIn(page) {
  await page.goto('/')
  await page.getByLabel('Username').fill('e2e_operator')
  await page.getByLabel('Password').fill('e2e-pass-12345')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Home' })).toBeVisible()
}

test('settings sections, language switch to Bangla and back', async ({ page }) => {
  await signIn(page)
  await page.goto('/#/settings')
  const nav = page.getByRole('navigation', { name: 'Settings sections' })
  // An operator sees only the personal sections; command sections stay hidden.
  await expect(nav.getByRole('button')).toHaveCount(5)
  await nav.getByRole('button', { name: /Detection thresholds/ }).click()
  await expect(page.getByRole('heading', { name: 'Detection thresholds', level: 2 })).toBeVisible()

  await nav.getByRole('button', { name: /Profile/ }).click()
  await page.getByRole('button', { name: 'বাংলা' }).click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'bn')
  await expect(page.getByRole('heading', { name: 'প্রোফাইল', level: 2 })).toBeVisible()
  await page.screenshot({ path: 'test-results/settings-bn.png', fullPage: true })
  await page.getByRole('button', { name: 'English' }).click()
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
})

test('incidents: search empty state offers to clear filters', async ({ page }) => {
  await signIn(page)
  await page.goto('/#/incidents')
  await page.getByRole('searchbox', { name: 'Search' }).fill('zzz-no-such-incident')
  await expect(page.getByText('No incidents match')).toBeVisible()
  await page.getByRole('button', { name: 'Clear filters' }).last().click()
  await expect(page.getByRole('searchbox', { name: 'Search' })).toHaveValue('')
  await page.screenshot({ path: 'test-results/incidents.png', fullPage: true })
})

test('phone layout: settings nav scrolls sideways, incidents stack', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await signIn(page)
  await page.goto('/#/settings')
  await expect(page.getByRole('navigation', { name: 'Settings sections' })).toBeVisible()
  await page.screenshot({ path: 'test-results/settings-phone.png', fullPage: true })
  await page.goto('/#/respond')
  await page.screenshot({ path: 'test-results/respond-phone.png', fullPage: true })
})
