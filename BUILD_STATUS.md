# BUILD_STATUS

Progress log for CallKind. Newest entry last. Purpose: resume work after a context reset.

Deadline note: build started 2026-09-19 ~16:50 local, ~17 h budget → feature freeze target
2026-09-20 ~06:50, submission by ~09:50. **Reconfirm the real SteelHacks XIII deadline.**

---

## M0 — scaffold + provider access (hour 0–1) — IN PROGRESS

Done:
- `git init`; `.gitignore` excludes `.env`, venvs, `node_modules`, generated audio cache, eval output.
- Build spec preserved verbatim at `docs/BUILD_SPEC.md`.
- `.env.example` written with placeholders only; local `.env` created (git-ignored, empty values).
- Python 3.12 venv at `.venv` via `uv`; backend deps installed (fastapi, httpx, pydantic, pytest…).
- `backend/app/config.py` — settings read from env, missing keys reported as *setup needs*
  rather than import-time crashes.
- Provider request shapes verified against primary docs (2026-09-19):
  - **STT**: `POST https://api.elevenlabs.io/v1/speech-to-text`, `xi-api-key`,
    multipart fields `file` + `model_id`; transcript in response field `text`.
  - **TTS**: `POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}`, `xi-api-key`,
    JSON `{text, model_id, output_format}`, default `mp3_44100_128`; returns raw audio.
  - **ElevenLabs model ids**: STT `scribe_v2` (current; `scribe_v1` deprecated).
    TTS `eleven_flash_v2_5` = fastest, correct choice here (`eleven_turbo_*` deprecated).
  - **NVIDIA**: OpenAI-compatible `POST {base}/chat/completions`, bearer auth. Supports
    `chat_template_kwargs.enable_thinking` — we set it **False** for low-latency classification.
    The build.nvidia.com page renders its model id client-side, so the id was NOT readable from
    the docs; it must come from `GET /v1/models` on Gabriel's own key.
- `backend/scripts/smoke_nvidia.py`, `backend/scripts/smoke_elevenlabs.py` — tiny access checks.
  Both run and fail cleanly with "BLOCKED: key empty" (expected; no keys yet).

Blocked on Gabriel (does not block other work):
- `NVIDIA_API_KEY` + `NVIDIA_MODEL` (nemotron id from the smoke script's catalogue listing)
- `ELEVENLABS_API_KEY` + `ELEVENLABS_VOICE_ID` (stock voice id from the smoke script's listing)

## M1 — text-turn vertical slice (next)
Not started.

## M0 — COMPLETE (2026-09-19 ~19:45)

Credentials supplied by Gabriel and verified working:
- **NVIDIA**: key valid, 82 models visible, 17 Nemotron. Chose
  `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` as primary (see decision below),
  `nvidia/nemotron-3.5-lightning-30b-a3b` as transient-failure fallback.
- **ElevenLabs**: key valid but scoped WITHOUT `user_read`, so `/v1/user/subscription`
  returns 401. Not fatal — STT/TTS work. Quota must be checked in the dashboard by hand.
  Voice `uKGPYP2uuyRQv8SeFre0` = "Chris Anthony" (category: **professional**, not premade).
- TTS first call 5.4 s (cold), warm 176–403 ms. `eleven_flash_v2_5` confirmed.

### Model choice, measured not assumed
Benchmarked both candidates on 8 discrimination cases + 5 credential phrasings:

| | nano-omni-reasoning | 3.5-lightning |
|---|---|---|
| `credential_request` correct | **5/5** | 4/5 (missed a PIN request entirely) |
| evidence quotes verified | high | high |
| `risk` label on direct OTP ask | wobbles (4× needs_review) | wobbles (2× needs_review) |
| median classify latency | ~2.9 s | ~2.8 s |
| transient 503s seen | yes (2) | none |

**Finding that shaped the architecture:** the structured `credential_request` field is
markedly more reliable than the free-text `risk` label on *both* models. Neither model
reliably says `high_risk` for a direct one-time-code request even when told to explicitly.
So the narrow end-call policy keys off `credential_request` + a re-verified,
credential-bearing quote — never off the model's chosen risk word. This is exactly the
separation §5 asks for, and it is now load-bearing rather than decorative.

### Built
- `schemas.py`, `classifier.py`, `policy.py`, `providers.py`, `sessions.py`, `main.py`.
- Prompt `p7ddae94c`, reasoning disabled, 260 output-token budget, `response_format=json_object`.
- Fixed-phrase audio cache: 13 phrases, 992 KB, generated in 4.4 s. Every assistant
  response in the demo is a cache hit → no per-turn TTS cost or latency.
- 34 backend tests passing (policy + API, providers mocked, no network).

### Live end-to-end verification (text input, real Nemotron, real ElevenLabs audio)
All three required scenarios verified against the running server:
1. Bank impersonation → `end_simulated_call` + URGENT alert, quote verified. ✅
2. Routine delivery → `take_message`, no verified-identity claim. ✅
3. Claimed family emergency → URGENT `request_family_review`, call NOT ended, model never
   authenticates the caller. ✅

### Defects found and fixed during live verification
- **Benign calls looped on one question.** `purpose_asked` was only set when the model
  picked `ask_purpose`; it picked `ask_organisation`, so the delivery call asked the same
  question forever and never reached `take_message`. Fixed: any neutral follow-up counts,
  and a question already asked is never repeated. Regression tests added.
- **Duplicate urgent alerts.** A caller repeating an emergency claim raised a fresh alert
  every turn. Fixed with per-call headline de-duplication; the refusal still stands.

### Known issues / honest notes
- Hosted-endpoint latency is highly variable: observed 0.9 s – 14.3 s for one classify.
  Mitigations: filler phrase, one retry, fallback model. Not solvable from our side.
- The 20-word quote limit is a prompt hint the model sometimes ignores on long turns.
- `CREDENTIAL_TERMS` is a support guard, **not** a negation detector: the phrase
  "we will never ask you to read out a one time code" matches it. Safety comes from the
  conjunction with `credential_request`, which the model gets right on negations. Must be
  measured in eval rather than assumed.
- NOT YET VERIFIED: microphone capture, real STT on spoken audio, push-to-talk, browser UI.

## M1 — frontend (next)

## M1 — frontend + verified spoken loop — COMPLETE (2026-09-19 ~20:10)

Built: Vite + React + TS, no router (pathname switch), no UI component library.
- `useRecorder.ts` — MIME detection, push-to-talk, 30 s cap, 0.5 s minimum, permission
  and unsupported-browser handling.
- `useCall.ts` — turn submission, filler scheduling, time-to-filler vs time-to-response
  measured separately, plus `useFamilyFeed` (1 s polling, follows `/api/calls/current`).
- `CallerPanel` / `FamilyPanel` / `ModeBadge`. Side-by-side on `/`, family alone on `/family`.
- Typecheck clean, production build clean, served single-process by FastAPI from `dist/`.

### Browser E2E with a real microphone path
`e2e/spoken_turn.mjs` drives headless Chromium with `--use-file-for-fake-audio-capture`,
fed WAVs of synthesised caller speech (a different ElevenLabs voice from the assistant).
This exercises getUserMedia → MediaRecorder → upload → **real ElevenLabs STT** → **real
Nemotron** → policy → cached speech, with the family window open in a second tab.

**Bank impersonation, spoken:** transcribe 816 ms, classify 1290 ms, time-to-filler 251 ms,
time-to-response 2117 ms. Ended the call, raised the URGENT alert, and the family window
highlighted exactly `"Read it back to me so I can verify you"`. ✅
**Routine delivery, spoken:** transcribe 531 ms, classify 2178 ms. No alert, asked a
neutral follow-up. No false alarm. ✅
Reset verified: the separately-opened family window picked up the new call by itself.

### Two real frontend defects found by the E2E run and fixed
- **Async start race.** `getUserMedia` is async, so a quick tap released *before* the mic
  opened: `stop()` found no recorder, returned, and then the recorder started anyway and
  kept running. Fixed with a `desiredRef` press/release flag; an aborted start now reports
  the "too short" hint. This is the accidental-tap case §6 asks for.
- **`pointerleave` auto-sent the turn.** Drifting the pointer off the button mid-sentence
  submitted early. Replaced with pointer capture + `pointercancel`.

Verified in-browser: accidental tap discarded with a hint; spacebar ignored while typing;
filler played then the reply; family window updated on turn completion and after reset.
Screenshots in `eval/results/`.

### Still unverified
- A **human** speaking into a **real** microphone, and venue-like background noise.
  Synthesised speech through a fake device is a weaker test. Gabriel must do this.
- Safari / Firefox. Only Chromium was exercised.

## M2 — evaluation (next): datasets, keyword baseline, runner, label review

## M2 — evaluation harness + dev results — COMPLETE (2026-09-19 ~20:40)

Built: `eval/build_datasets.py` (12 dev + 24 test conversations, 73 prefixes),
`eval/keyword_baseline.py` (frozen `kw-v1`), `eval/run_eval.py`, `eval/make_review.py`.
Both systems are fed identical prefixes and run through the **same** policy layer, with
policy state carried forward across a conversation. No TTS is generated during eval.

### Dev-set results (12 conversations, 24 prefixes, dataset `dcd379a81d1`)

| | Nemotron pipeline | keyword `kw-v1` |
|---|---|---|
| system protective recall on scams | **6/6** | 5/6 |
| benign high-risk false alarms | **0/6** | 1/6 |
| benign calls incorrectly ended | **0/6** | 1/6 (`dev-08`) |
| benign sent to review | 1/6 | 2/6 |
| prefix risk within acceptable set | **24/24** | 21/24 |
| forbidden-action violations | **0/24** | 1/24 |
| evidence quotes verified | 26/26 | — |
| classify latency median / p95 | 2362 ms / 3195 ms | ~0 ms |
| provider failures | 0 | — |

The baseline's failure is the headline comparison: `kw-v1` **hangs up on `dev-08`**, a bank
calling to warn the customer never to share a one-time code. It matches the words and
cannot read who is asking whom to do what.

### Third policy defect found by the dev set, and fixed
`needs_review` plus a strong verified signal (a wire-transfer demand, an attempt to
override the screening rules) previously just asked another neutral question, twice, and
the conversation ended with **no alert ever raised** — `dev-05` and `dev-06` both slipped
through. Added `SEVERE_SIGNALS`: a verified quote carrying payment / secrecy / manipulation
/ remote-access / threat / emergency escalates to review immediately, the same way a
claimed emergency already did. `authority_impersonation` is deliberately excluded — naming
a bank is not evidence of anything. Four regression tests added; dev recall went 4/6 → 6/6
with benign false alarms still 0/6.

38 backend tests passing.

### Docs written
`README.md` (replaced), `docs/DEMO.md`, `docs/SUBMISSION.md` (survey left blank, as required).

## M3 — BLOCKED on Gabriel: test-set label review

`eval/test_review.md` generated: 24 conversations, 49 prefixes, dataset hash `d4f1cac323d`,
`frozen: false`. Per the build spec the test set must be reviewed by Gabriel before it is
frozen, and the classifier prompt must not be tuned against it beforehand.

- Prompt has been at `p7ddae94c` since before the test set was written. Tuning to date used
  only ad-hoc examples and the dev split.
- Review status: **PENDING** — awaiting Gabriel. Labels changed so far: 0.
- Nothing from the test set has been run.

## M3a — offline replay + report generator — COMPLETE (2026-09-20 ~00:10)

- `eval/record_replay.py` recorded **real** live runs of all three demo scenarios to
  `backend/app/fixtures/replay.json`, carrying the model id, prompt version and timestamp.
  The replay is a recording of genuine inference, never invented output.
- `backend/app/fixtures.py` + `/api/replays`. Replay is entered **only** on explicit
  request (`POST /api/calls {"replay_scenario": ...}`) or `APP_MODE=fixture`. There is no
  code path from a provider failure into replay — a failure degrades to review. Two tests
  assert this.
- UI: collapsed "Offline replay — no live inference" control listing the recorded
  scenarios, showing when they were captured. Both panels show the **Fixture replay** mode
  badge; verified in-browser (`e2e/replay_check.mjs`) that typed input is ignored during
  replay and the badge reads correctly in the caller *and* family panels.
- `eval/make_report.py` generates `docs/EVALUATION.md` straight from the results JSON, so
  no number in the write-up is hand-copied.

42 backend tests passing.

### Gabriel's label-review decisions (2026-09-20)
Asked about the two genuine judgement calls in the draft test labels:
- test-04 / test-12 (family emergency, romance): confirmed `end_simulated_call` stays
  **forbidden** — alert the family, never hang up on a possible real emergency.
- test-21 (no-pressure charity call): confirmed calm *or* review both acceptable.
**Labels changed: 0.** Full 24-conversation review still outstanding; test set remains
`frozen: false` and has NOT been run.
