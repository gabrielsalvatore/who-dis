/** Phone layout and real API flow using offline fixtures; never paid inference.
 * Start backend with APP_MODE=fixture and empty provider keys on port 8001.
 */
import assert from 'node:assert/strict'
import { chromium } from 'playwright'

const base = process.env.CK_BASE ?? 'http://localhost:8001'
const health = await fetch(`${base}/api/health`).then(r => r.json())
assert.equal(health.app_mode, 'fixture', 'Use a fixture-only backend for this check')
assert.equal(health.speech_configured, false, 'Disable provider keys for this check')
const browser = await chromium.launch({ headless: true, args: [
  '--use-fake-device-for-media-stream', '--use-fake-ui-for-media-stream',
] })
try {
  const context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true })
  const page = await context.newPage()
  await page.addInitScript(() => {
    const originalFetch = window.fetch.bind(window)
    window.fetch = (input, init) => {
      const audio = init?.body instanceof FormData ? init.body.get('audio') : null
      if (audio instanceof File) window.phoneTestUpload = { name: audio.name, size: audio.size }
      return originalFetch(input, init)
    }
  })
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  await page.goto(`${base}/phone`)
  await page.getByRole('button', { name: 'Start call', exact: true }).click()
  await page.getByRole('button', { name: 'Hold to talk', exact: true }).waitFor()
  assert.equal(await page.getByText('Offline replay', { exact: true }).first().isVisible(), true)
  await page.screenshot({ path: 'eval/results/phone-active.png', fullPage: true })
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true)

  // Send typed turns through the existing backend and follow the family feed.
  const family = await context.newPage()
  await family.goto(`${base}/family`)
  await page.getByRole('button', { name: 'Type', exact: true }).click()
  const sendText = async () => {
    await page.getByLabel('Your side of the call').fill('Synthetic fixture input')
    const response = page.waitForResponse(r => r.url().endsWith('/turns') && r.request().method() === 'POST')
    await page.getByRole('button', { name: 'Send', exact: true }).click()
    assert.equal((await response).status(), 200)
    await page.waitForFunction(() => !document.querySelector('.phone-status')?.textContent?.includes('Screening'))
  }
  await sendText()
  await sendText()
  await page.getByRole('button', { name: 'Call again', exact: true }).waitFor()
  await family.locator('.alert-tag').first().waitFor()
  await page.getByRole('button', { name: 'Transcript', exact: true }).click()
  assert.ok(await page.locator('#phone-transcript p').count() >= 5)
  await page.screenshot({ path: 'eval/results/phone-ended.png', fullPage: true })

  // Manual hang-up keeps the same session accessible in the family view.
  await page.getByRole('button', { name: 'Call again', exact: true }).click()
  await page.getByRole('button', { name: 'End call', exact: true }).waitFor()
  const current = await context.request.get(`${base}/api/calls/current`).then(r => r.json())
  await page.getByRole('button', { name: 'End call', exact: true }).click()
  await page.getByRole('button', { name: 'Call again', exact: true }).waitFor()
  const ended = await context.request.get(`${base}/api/calls/${current.call_id}`).then(r => r.json())
  assert.equal(ended.status, 'ended')
  assert.ok(ended.turns.length > 0)

  // Real browser recording (fake mic), uploaded through the same audio endpoint.
  await page.getByRole('button', { name: 'Call again', exact: true }).click()
  await page.getByRole('button', { name: 'Transcript', exact: true }).click()
  await page.locator('.phone-demo-options > summary').click()
  await page.getByLabel('Tap to record, then tap to send').check()
  await page.getByRole('button', { name: 'Start recording', exact: true }).click()
  await page.getByRole('button', { name: 'Send recording', exact: true }).waitFor()
  await page.waitForTimeout(800)
  const audioResponse = page.waitForResponse(r => r.url().endsWith('/turns') && r.request().method() === 'POST')
  await page.getByRole('button', { name: 'Send recording', exact: true }).click()
  const uploaded = await audioResponse
  assert.equal(uploaded.status(), 200)
  const audioFile = await page.evaluate(() => window.phoneTestUpload)
  assert.match(audioFile.name, /^turn\./)
  assert.ok(audioFile.size > 0)
  await page.getByRole('button', { name: 'Start recording', exact: true }).waitFor({ state: 'visible' })
  await page.waitForFunction(() => !document.querySelector('.phone-talk')?.disabled)

  // Discard must stop capture without submitting another turn.
  let extraTurns = 0
  const countTurn = request => { if (request.url().endsWith('/turns')) extraTurns++ }
  page.on('request', countTurn)
  await page.getByRole('button', { name: 'Start recording', exact: true }).click()
  await page.getByRole('button', { name: 'Send recording', exact: true }).waitFor()
  await page.waitForTimeout(650)
  await page.getByRole('button', { name: 'Discard recording', exact: true }).click()
  await page.waitForTimeout(150)
  assert.equal(extraTurns, 0)
  page.off('request', countTurn)

  // The maximum-length auto-stop must send the recording, not silently drop it.
  await page.clock.install()
  await page.getByRole('button', { name: 'Start recording', exact: true }).click()
  await page.getByRole('button', { name: 'Send recording', exact: true }).waitFor()
  await page.waitForTimeout(800)
  const cappedTurn = page.waitForResponse(r => r.url().endsWith('/turns') && r.request().method() === 'POST')
  await page.clock.fastForward(30_000)
  assert.equal((await cappedTurn).status(), 200)
  await page.getByRole('button', { name: 'Call again', exact: true }).waitFor()

  for (const width of [320, 430, 1280]) {
    await page.setViewportSize({ width, height: 900 })
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true, `overflow at ${width}`)
  }
  assert.deepEqual(errors, [])
  // An insecure phone browser gets a visible typed fallback.
  const fallback = await context.newPage()
  await fallback.addInitScript(() => {
    Object.defineProperty(navigator, 'mediaDevices', { value: undefined })
    Object.defineProperty(window, 'isSecureContext', { value: false })
  })
  await fallback.goto(`${base}/phone`)
  await fallback.getByRole('button', { name: 'Start call', exact: true }).click()
  await fallback.getByLabel('Your side of the call').waitFor()
  assert.ok(await fallback.getByText('Voice needs a secure HTTPS link', { exact: false }).isVisible())
  assert.equal(await fallback.getByRole('button', { name: 'Hold to talk' }).isDisabled(), true)
  console.log('PASS: mobile layout, typed screening, family alert, transcript, hang-up, restart, audio upload, discard, recording cap, insecure-browser fallback, no page errors')
} finally { await browser.close() }
