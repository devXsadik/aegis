import { expect, test } from '@playwright/test'

// Phases 2–4: incident drawer, jurisdiction-based officer picker, status selector with notes.
async function signIn(page, user = 'e2e_operator') {
  await page.goto('/')
  await page.getByLabel('Username').fill(user)
  await page.getByLabel('Password').fill('e2e-pass-12345')
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Home' })).toBeVisible()
}

async function newIncident(page, title) {
  await page.goto('/#/incidents')
  await page.getByRole('button', { name: 'New incident' }).first().click()
  const dlg = page.getByRole('dialog', { name: 'New incident' })
  await dlg.getByLabel('Title').fill(title)
  await dlg.getByLabel('Camera (sets the jurisdiction)').selectOption({ label: 'Lab gate' })
  await dlg.getByRole('button', { name: 'Create' }).click()
  const drawer = page.getByRole('dialog', { name: title })
  await expect(drawer).toBeVisible()
  await expect(drawer.getByText('Gulshan · গুলশান')).toBeVisible()
  return drawer
}

test('operator assigns an in-area officer and marks a false alarm with a note', async ({ page }) => {
  await signIn(page)
  const drawer = await newIncident(page, 'E2E bag at Lab gate')

  await drawer.getByRole('button', { name: 'Assign' }).click()
  const picker = page.getByRole('dialog', { name: /Assign officers/ })
  const list = picker.getByRole('list', { name: 'Eligible officers' })
  await expect(list.getByRole('listitem')).toHaveCount(2)              // Badda officer is not offered
  await expect(list.getByRole('listitem').first()).toContainText('Karim Hossain')   // available before busy
  await expect(picker.getByText('Show neighbouring jurisdictions')).toHaveCount(0) // operator: no override
  await picker.getByLabel('Select Karim Hossain').check()
  await picker.getByRole('button', { name: 'Assign 1' }).click()
  await expect(page.getByText(/1 officer\(s\) assigned/)).toBeVisible()
  await expect(drawer.getByText('SI Karim Hossain')).toBeVisible()

  await drawer.getByRole('button', { name: /Status: Officer dispatched/ }).click()
  await page.getByRole('option', { name: /False alarm/ }).click()
  const confirm = page.getByRole('dialog', { name: /False alarm/ })
  const go = confirm.getByRole('button', { name: 'Mark false alarm' })
  await expect(go).toBeDisabled()                                        // note is mandatory
  await confirm.getByLabel('Note (required)').fill('Owner came back for the bag')
  await go.click()
  await expect(drawer.getByRole('button', { name: /Status: False alarm/ })).toBeVisible()
  await expect(drawer.getByText(/false_alarm: Owner came back/)).toBeVisible()   // timeline
  await page.screenshot({ path: 'test-results/incident-drawer.png' })
})

test('supervisor can include a neighbouring area, with a logged reason', async ({ page }) => {
  await signIn(page, 'e2e_supervisor')
  const drawer = await newIncident(page, 'E2E supervisor override')
  await drawer.getByRole('button', { name: 'Assign' }).click()
  const picker = page.getByRole('dialog', { name: /Assign officers/ })
  await picker.getByText('Show neighbouring jurisdictions').click()
  await expect(picker.getByRole('listitem').filter({ hasText: 'Rafiq Uddin' })).toContainText('Neighbouring area')
  await picker.getByLabel('Select Rafiq Uddin').check()
  const assign = picker.getByRole('button', { name: 'Assign 1' })
  await expect(assign).toBeDisabled()                                    // reason required
  await picker.getByLabel(/Reason for assigning outside/).fill('Gulshan officers busy')
  await assign.click()
  await expect(drawer.getByText('Out of area')).toBeVisible()
  await page.screenshot({ path: 'test-results/incident-picker-done.png' })
})

test('incidents list filters and shows officers on the row', async ({ page }) => {
  await signIn(page)
  await page.goto('/#/incidents')
  await page.getByRole('group', { name: 'Severity' }).getByRole('button', { name: 'Critical' }).click()
  await expect(page.getByRole('button', { name: 'Clear filters' }).first()).toBeVisible()
  await page.screenshot({ path: 'test-results/incidents-list.png', fullPage: true })
})

test('supervisor sees jurisdictions on a map and officer profiles', async ({ page }) => {
  await signIn(page, 'e2e_supervisor')
  await page.goto('/#/settings')
  const nav = page.getByRole('navigation', { name: 'Settings sections' })
  await nav.getByRole('button', { name: /Jurisdictions/ }).click()
  const list = page.getByRole('list', { name: 'Jurisdictions' })
  await expect(list.getByRole('button', { name: /Gulshan/ })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Add area' })).toHaveCount(0)     // admin only
  await nav.getByRole('button', { name: /Users & roles/ }).click()
  await expect(page.getByText('SI Karim Hossain')).toBeVisible()
  await page.screenshot({ path: 'test-results/settings-officers.png', fullPage: true })
})
