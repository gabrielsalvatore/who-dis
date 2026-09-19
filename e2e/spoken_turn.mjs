/**
 * Drives the real browser path: microphone capture -> MediaRecorder -> upload ->
 * ElevenLabs STT -> Nemotron -> policy -> spoken reply, with the family window
 * open alongside.
 *
 * Chrome's fake capture device is fed a WAV of synthesised caller speech, so this
 * exercises every real API. It is NOT a substitute for a human speaking into a
 * real microphone in a noisy room - that check stays on the manual list.
 *
 *   node e2e/spoken_turn.mjs <fixture-name> [holdSeconds]
 */
import { chromium } from 'playwright'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const here = path.dirname(fileURLToPath(import.meta.url))
const fixture = process.argv[2] ?? 'otp_request'
const holdMs = Number(process.argv[3] ?? 13) * 1000
const wav = path.resolve(here, '..', 'eval', 'audio_fixtures', `${fixture}.wav`)
const BASE = 'http://localhost:8000'

const log = (...a) => console.log(...a)

const browser = await chromium.launch({
  channel: 'chromium',
  headless: true,
  args: [
    '--use-fake-ui-for-media-stream',
    '--use-fake-device-for-media-stream',
    `--use-file-for-fake-audio-capture=${wav}`,
    '--autoplay-policy=no-user-gesture-required',
  ],
})
const context = await browser.newContext({ permissions: ['microphone'] })

const page = await context.newPage()
page.on('console', (m) => { if (m.type() === 'error') log('  [browser error]', m.text()) })
page.on('pageerror', (e) => log('  [page error]', e.message))

await page.goto(BASE, { waitUntil: 'networkidle' })
await page.waitForSelector('.ptt')
log(`fixture: ${fixture}  (holding ${holdMs / 1000}s)`)

// --- family window, opened separately, following the active call -----------
const family = await context.newPage()
await family.goto(`${BASE}/family`, { waitUntil: 'networkidle' })
await family.waitForSelector('.family-panel')
log('family window open')

// --- accidental tap must be discarded, not sent ----------------------------
const ptt = page.locator('.ptt')
await ptt.hover()
await page.mouse.down()
await page.waitForTimeout(150)
await page.mouse.up()
await page.waitForTimeout(600)
const hint = await page.locator('.caller-panel .notice.quiet').first().textContent().catch(() => '')
log(`accidental tap (150ms): ${/too short/i.test(hint ?? '') ? 'PASS - discarded with a hint' : `CHECK - hint was: ${hint}`}`)

// --- spacebar must be ignored while typing ---------------------------------
await page.locator('#typed').fill('hello ')
await page.locator('#typed').press('Space')
await page.waitForTimeout(300)
const recordingWhileTyping = await page.locator('.ptt.recording').count()
log(`spacebar while typing: ${recordingWhileTyping === 0 ? 'PASS - did not start recording' : 'FAIL - started recording'}`)
await page.locator('#typed').fill('')

// --- the real spoken turn ---------------------------------------------------
const t0 = Date.now()
await ptt.hover()
await page.mouse.down()
await page.waitForSelector('.ptt.recording', { timeout: 3000 })
log('recording…')
await page.waitForTimeout(holdMs)
await page.mouse.up()
log(`released after ${((Date.now() - t0) / 1000).toFixed(1)}s, waiting for the pipeline…`)

await page.waitForSelector('.last-turn', { timeout: 90_000 })
await page.waitForFunction(() => !document.querySelector('.processing'), null, { timeout: 90_000 })

const heard = (await page.locator('.last-turn .heard').textContent()) ?? ''
const said = (await page.locator('.last-turn .said').textContent()) ?? ''
const fine = (await page.locator('.last-turn .fine').textContent()) ?? ''
log('\n--- caller page ---')
log(heard.trim())
log(said.trim())
log(fine.trim())

// --- family window state ----------------------------------------------------
await family.waitForTimeout(1600)   // one poll cycle
const alertCount = await family.locator('.alert-card').count()
const alertTag = alertCount ? await family.locator('.alert-tag').first().textContent() : '(none)'
const headline = alertCount ? await family.locator('.alert-card h3').first().textContent() : '(none)'
const marks = await family.locator('mark').allTextContents()
const outcome = await family.locator('.outcome-action').textContent().catch(() => '(none)')
const status = await family.locator('.status-pill').textContent().catch(() => '')
log('\n--- family window ---')
log(`status      : ${status?.trim()}`)
log(`outcome     : ${outcome?.trim()}`)
log(`alerts      : ${alertCount} — [${alertTag?.trim()}] ${headline?.trim()}`)
log(`highlighted : ${marks.length ? marks.map((m) => JSON.stringify(m)).join(', ') : '(none)'}`)

await page.screenshot({ path: `eval/results/shot_${fixture}_caller.png`, fullPage: true })
await family.screenshot({ path: `eval/results/shot_${fixture}_family.png`, fullPage: true })

// --- reset must be followed by the separately-opened family window ---------
await page.locator('button.secondary', { hasText: /Restart call/ }).click()
await page.waitForTimeout(2000)
const afterReset = await family.locator('.alert-card').count()
const afterStatus = await family.locator('.status-pill').textContent().catch(() => '(none)')
log(`\nafter reset : family window shows ${afterReset} alerts, status "${afterStatus?.trim()}" (should be a fresh call)`)

await browser.close()
