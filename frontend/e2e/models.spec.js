import { expect, test } from '@playwright/test'

// Phase 7.4: an ML engineer builds a dataset: add, label, split, freeze.
const JPG = Buffer.from('/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/wAALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQQAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8AKp//2Q==', 'base64')

test('ML engineer creates, labels, splits and freezes a dataset', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Username').fill('e2e_ml')
  await page.getByLabel('Password').fill('e2e-pass-12345')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await page.goto('/#/models')
  await page.getByLabel('Dataset name').fill('e2e-attrs')
  await page.getByRole('button', { name: 'Create' }).click()
  const dlg = page.getByRole('dialog', { name: /e2e-attrs v1/ })
  await dlg.locator('input[type=file]').setInputFiles({ name: 'a.jpg', mimeType: 'image/jpeg', buffer: JPG })
  await expect(dlg.getByText(/1 items · 0 labelled/)).toBeVisible()
  await dlg.getByLabel('color').selectOption('white')
  await expect(dlg.getByText(/1 labelled/)).toBeVisible()
  await dlg.getByRole('button', { name: 'Split' }).click()
  await expect(page.getByText('Split 80 / 10 / 10')).toBeVisible()
  await dlg.getByRole('button', { name: 'Freeze' }).click()
  await expect(dlg.getByText('Frozen', { exact: true })).toBeVisible()
  await expect(dlg.getByRole('link', { name: 'attributes' })).toBeVisible()
  await page.screenshot({ path: 'test-results/models-data.png' })
})
