import { expect, test } from '@playwright/test'

// Phase 12: upload with progress to an incident; the gallery shows it with its custody chain.
const PNG = Buffer.from('89504e470d0a1a0a0000000d4948445200000001000000010806000000' +
  '1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082', 'hex')

test('operator uploads a photo to an incident and checks its integrity', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Username').fill('e2e_desk')
  await page.getByLabel('Password').fill('e2e-pass-12345')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Home' })).toBeVisible()
  await page.goto('/#/evidence')
  await page.getByRole('button', { name: 'Upload', exact: true }).click()
  await page.getByLabel('Linked incident (required)').selectOption({ label: 'INC-TRK1 — E2E tracked vehicle' })
  await page.getByLabel('Choose evidence files').setInputFiles([
    { name: 'scene.png', mimeType: 'image/png', buffer: PNG },
    { name: 'virus.exe', mimeType: 'application/x-msdownload', buffer: Buffer.from('MZ') },
  ])
  await expect(page.getByText('File type not accepted')).toBeVisible()
  await page.getByLabel('Description').fill('Scene, north entrance')
  await page.getByRole('button', { name: /Upload 1/ }).click()
  await expect(page.getByText('1 file(s) added to the incident')).toBeVisible()
  await page.screenshot({ path: 'test-results/evidence-upload.png', fullPage: true })

  await page.getByRole('button', { name: 'Case evidence' }).click()
  const tile = page.getByRole('button', { name: /Open EV-/ }).first()
  await tile.click()
  const lb = page.getByRole('dialog', { name: /EV-.* scene\.png/ })
  await lb.getByRole('button', { name: 'Check integrity' }).click()
  await expect(lb.getByText(/Intact · \d+ custody records/)).toBeVisible()
  await lb.getByText(/Chain of custody/).click()
  await expect(lb.getByText('UPLOADED', { exact: true })).toBeVisible()
})
