import { expect, test } from '@playwright/test'

// Dispatch ↔ field messages, the duty roster and the command reports.
async function signIn(page, user) {
  await page.goto('/')
  await page.getByLabel('Username').fill(user)
  await page.getByLabel('Password').fill('e2e-pass-12345')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: /Home|Responders/ }).first()).toBeVisible()
}

test('dispatch messages an assigned officer, who answers from the phone', async ({ browser }) => {
  const desk = await browser.newPage()
  await signIn(desk, 'e2e_desk')
  await desk.goto('/#/incidents')
  await desk.getByRole('button', { name: 'New incident' }).first().click()
  const dlg = desk.getByRole('dialog', { name: 'New incident' })
  await dlg.getByLabel('Title').fill('E2E message thread')
  await dlg.getByLabel('Camera (sets the jurisdiction)').selectOption({ label: 'Lab gate' })
  await dlg.getByRole('button', { name: 'Create' }).click()
  const drawer = desk.getByRole('dialog', { name: 'E2E message thread' })
  await drawer.getByRole('button', { name: 'Assign officers' }).click()
  const picker = desk.getByRole('dialog', { name: /Assign officers/ })
  await picker.getByLabel('Select Karim Hossain').check()
  await picker.getByRole('button', { name: 'Assign 1' }).click()
  await expect(drawer.getByText('SI Karim Hossain')).toBeVisible()
  await drawer.getByRole('textbox', { name: 'Message', exact: true }).fill('Suspect in a red CNG, heading north')
  await drawer.getByRole('button', { name: 'Send' }).click()
  await expect(drawer.getByRole('list', { name: 'Messages' }).getByText('Suspect in a red CNG, heading north')).toBeVisible()

  const phone = await browser.newPage({ viewport: { width: 390, height: 844 } })
  await signIn(phone, 'e2e_off_karim')
  await phone.goto('/#/respond')
  const mine = phone.getByRole('region', { name: 'Your incidents' })
  await mine.getByRole('button', { name: /E2E message thread/ }).click()
  await expect(mine.getByText('Suspect in a red CNG, heading north')).toBeVisible()
  await mine.getByRole('textbox', { name: 'Message', exact: true }).fill('On Road 11, no sign yet')
  await mine.getByRole('button', { name: 'Send' }).click()
  await expect(mine.getByText('On Road 11, no sign yet')).toBeVisible()
  await phone.screenshot({ path: 'test-results/officer-messages.png', fullPage: true })

  await expect(drawer.getByText('On Road 11, no sign yet')).toBeVisible({ timeout: 10000 })   // live on the desk
})

test('supervisor plans a shift and reads the command reports', async ({ page }) => {
  await signIn(page, 'e2e_supervisor')
  await page.goto('/#/roster')
  await expect(page.locator('.card-title', { hasText: 'Add a shift' })).toBeVisible()
  const officer = page.getByRole('combobox', { name: 'Officer', exact: true })
  const value = await officer.locator('option', { hasText: 'Karim Hossain' }).getAttribute('value')
  await officer.selectOption(value)
  await page.getByRole('button', { name: /Evening 14–22/ }).click()
  await page.getByLabel('Assignment (optional)').fill('Patrol car 3')
  await page.getByRole('button', { name: 'Add shift' }).click()
  await expect(page.getByText('Patrol car 3').first()).toBeVisible()

  await page.goto('/#/response')
  await expect(page.getByText('Officer assigned (median)').or(page.getByText('No incidents in this period'))).toBeVisible()
  await page.getByRole('button', { name: 'Patterns' }).click()
  await expect(page.getByText('When incidents happen')).toBeVisible()
  await page.getByRole('button', { name: 'Camera uptime' }).click()
  await expect(page.getByText('Per camera')).toBeVisible()
  await page.screenshot({ path: 'test-results/camera-uptime.png', fullPage: true })
})
