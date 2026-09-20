/** Confirms offline replay is explicit, labelled, and needs no provider. */
import { chromium } from 'playwright'
const browser = await chromium.launch({ channel: 'chromium', headless: true,
  args: ['--autoplay-policy=no-user-gesture-required'] })
const page = await browser.newPage()
await page.goto(`${process.env.CK_BASE ?? 'http://localhost:8000'}`, { waitUntil: 'networkidle' })

await page.locator('.replay-controls summary').click()
const note = await page.locator('.replay-controls .fine').textContent()
console.log('replay note :', note?.trim().replace(/\s+/g, ' ').slice(0, 130))

await page.locator('.replay-controls button', { hasText: 'bank impersonation' }).click()
await page.waitForTimeout(1200)
console.log('mode badge  :', (await page.locator('.caller-panel .mode-label').textContent())?.trim())

for (let i = 0; i < 2; i++) {
  await page.locator('#typed').fill('this text is ignored during replay')
  await page.locator('.typed-fallback button').click()
  await page.waitForFunction(() => !document.querySelector('.processing'), null, { timeout: 30000 })
  await page.waitForTimeout(500)
}
console.log('heard       :', (await page.locator('.last-turn .heard').textContent())?.trim().slice(0, 90))
console.log('status      :', (await page.locator('.status-pill').textContent())?.trim())
console.log('alert       :', (await page.locator('.alert-tag').first().textContent().catch(() => '(none)'))?.trim())
console.log('family mode :', (await page.locator('.family-panel .mode-label').textContent())?.trim())
await page.screenshot({ path: 'eval/results/shot_replay.png', fullPage: true })
await browser.close()
