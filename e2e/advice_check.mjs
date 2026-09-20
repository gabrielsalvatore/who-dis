/** Checks callback-verification advice, masking, and the second filler in the UI. */
import { chromium } from 'playwright'
const BASE = process.env.CK_BASE ?? 'http://localhost:8000'
const browser = await chromium.launch({ channel: 'chromium', headless: true,
  args: ['--autoplay-policy=no-user-gesture-required'] })
const page = await browser.newPage()
await page.goto(BASE, { waitUntil: 'networkidle' })

async function say(text) {
  await page.locator('#typed').fill(text)
  await page.locator('.typed-fallback button').click()
  await page.waitForFunction(() => !document.querySelector('.processing'), null, { timeout: 60000 })
  await page.waitForTimeout(400)
}

await say("Grandma it's Tom, I've had an accident.")
await say("I need three thousand dollars for bail right now, my reference is 558812, don't tell mum.")

console.log('alert tag    :', (await page.locator('.alert-tag').first().textContent())?.trim())
console.log('headline     :', (await page.locator('.alert-card h3').first().textContent())?.trim())
const advice = await page.locator('.alert-advice').first().textContent().catch(() => null)
console.log('advice       :', advice?.trim().replace(/\s+/g, ' ') ?? '(NONE)')
console.log('assistant    :', (await page.locator('.last-turn .said').textContent())?.trim().slice(0, 140))
const transcript = await page.locator('.transcript').textContent()
console.log('code 558812 masked in transcript:', !transcript.includes('558812'))
console.log('mask marker present             :', transcript.includes('number masked'))
console.log('masking note shown              :', await page.locator('.masking-note').count() > 0)
await page.screenshot({ path: 'eval/results/shot_emergency_advice.png', fullPage: true })
await browser.close()
