import { expect, test } from '@playwright/test'

async function signIn(page, user) {
  await page.goto('/')
  await page.getByLabel('Username').fill(user)
  await page.getByLabel('Password').fill('e2e-pass-12345')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: /Home|Responders/ }).first()).toBeVisible()
}

// Phase 10: the officer answers a notification from the phone; the incident follows.
test('officer answers "On my way" on a target notification', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await signIn(page, 'e2e_off_karim')
  await page.goto('/#/respond')
  const card = page.getByRole('article', { name: /V-E2E detected at Lab gate/ })
  await expect(card).toBeVisible()
  await expect(card.getByText('Moving N', { exact: true })).toBeVisible()
  await expect(card.getByText(/Answer within/)).toBeVisible()
  await page.screenshot({ path: 'test-results/officer-inbox.png', fullPage: true })
  await expect(page.getByRole('radiogroup', { name: 'Duty status' })).toBeVisible()
  await card.getByRole('button', { name: 'On my way' }).click()
  await expect(card.getByText(/You answered “On my way”/)).toBeVisible()
})

// Phase 11: the command map shows the followed target with its predicted next camera.
test('command map lists the target, its lookout and camera status', async ({ page }) => {
  await signIn(page, 'e2e_supervisor')
  await page.goto('/#/command')
  await expect(page.getByRole('application', { name: 'Command map' })).toBeVisible()
  const item = page.locator('.wl-item').filter({ hasText: 'V-E2E' })
  await expect(item).toContainText('Confirmed')
  await expect(item).toContainText('next: North road')
  await expect(page.getByText(/1 on lookout/)).toBeVisible()
  await page.screenshot({ path: 'test-results/command-map.png' })
})
