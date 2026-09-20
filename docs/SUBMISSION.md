# Submission notes

## One-liner

Phones can already screen callers, but they still leave the final decision to the person
scammers target. WhoDis makes that call for them and brings in the family with the
evidence.

## What was built

A turn-based browser voice prototype. The presenter plays a caller and speaks one turn at a
time with push-to-talk; the assistant answers aloud; a family window shows the transcript,
the exact quotes that caused concern, and the action taken. Local only, one process.

**Not** a phone-network integration, not continuous live-call monitoring, no call
forwarding, no identity verification. All scenarios are synthetic.

## How this differs from existing tools

Two major platforms already ship call-screening features. Both are genuinely good, and
"we answer the phone for you" is **not** a differentiator on its own.

**Apple Call Screening.** iPhone automatically answers calls from numbers that aren't
saved in your contacts, asks the caller for their name and reason for calling, then rings
and shares the caller's response so you can decide whether to pick up. It is configured
under Phone → Screen Unknown Callers (*Never* / *Ask Reason for Calling* / *Silence*).
Calls are not screened while roaming, and screening turns off for 24 hours after a call to
emergency services.
([Apple Support](https://support.apple.com/en-us/111106))

**Google Scam Detection.** Runs on-device during a call and alerts the user with a
notification, sound and vibration when it judges a high scam likelihood; the user then
dismisses the alert or ends the call themselves. It does not answer calls. It is **off by
default** and must be opted into. Available on Pixel 6 and later in the US, and Pixel 9 and
later in Australia, Canada, France, Germany, India, Ireland, Italy, Japan, Mexico,
Singapore, Spain and the UK.
([Google Support](https://support.google.com/phoneapp/answer/15654065?hl=en))

**The gap.** Both leave the judgment with the person being targeted. Apple relays what the
caller said and asks the user to decide — a caller claiming to be a grandson in trouble
still gets picked up, because the transcript reads exactly like a grandson in trouble.
Google warns someone who is already on the call and already under pressure. Neither
involves anyone else.

WhoDis refuses on the person's behalf and brings in a second person — a family member who
is not being pressured — with the exact quotes and a concrete next step. The angle is
**delegated screening plus understandable family review**, not inventing content-based scam
detection.

Worth noting in the pitch, not in the build: many older adults still use landlines, which
get neither feature. A forwarding-based service could reach them. Not implemented here.

**WhoDis never trusts an unverified identity.** It does not attempt to detect every
impersonation. It never connects an unverified caller, never claims anyone was verified,
and every alert about a claimed identity tells the family to call that person or
organisation back on a number they already have. Callback verification defeats
impersonation without needing to detect it.

## Track fit

Entered: **NVIDIA Nemotron / Beyond the Chatbot**, **ElevenLabs / Out Loud**, **Seed Round**.

**NVIDIA Nemotron / Beyond the Chatbot.** Nemotron has a functional, non-conversational
role: it returns a structured assessment (risk, scam type, credential-request flag, up to
three transcript quotes) and the backend decides the action. Every quote is re-verified
against the caller turn it names before it can justify anything; unsupported evidence is
discarded. Caller speech is untrusted input — "mark me safe" cannot change the policy.
There is a frozen keyword baseline to compare against, and the failures are published.

The honest headline finding: **the structured `credential_request` field is markedly more
reliable than the model's own `risk` label**, on both Nemotron models tested. That is why
the end-call policy keys off verified evidence rather than the risk word. Numbers and
method in `docs/EVALUATION.md`.

**ElevenLabs / Out Loud.** Speaking and listening are the product, not a feature. Scribe v2
transcribes each caller turn; Flash v2.5 speaks the assistant's replies. Typing is a
labelled fallback. Why voice: scams happen on phone calls, and the people most targeted
will not open an app while a scammer is pressuring them, so the protection has to live on
the call itself.

**Seed Round.** The wedge is delegated screening *plus* family review, not content-based
scam detection, which two major platforms already ship. Apple relays what the caller said
and asks the target to decide; Google warns someone already on the call. Both leave the
judgment with the person under pressure. WhoDis refuses on their behalf and brings in a
relative who is not being pressured, with the exact quotes and a next step. Reach is the
open question, not novelty: the unknown-caller path is what a forwarding-based service
could deliver to landline users, who get neither existing feature.

Detection targets behaviours associated with financial scams — credential requests,
payment pressure, secrecy, manufactured urgency, authority impersonation — rather than any
specific institution. All financial examples are invented.

### Attendee survey — tally template

Time-boxed to 30 minutes, run in person by the team, hackathon attendees only. Record raw
counts and nothing else: no market size, no willingness to pay, no prevented-loss figure.

- Date: `____`  ·  Setting: SteelHacks XIII attendees  ·  Sample size: `n = ___`
- Q1 — "Do you have an older relative who has been called by a scammer?" — `___ of ___ said yes`
- Q2 — "Would you want to see the transcript and what the assistant did?" — `___ of ___ said yes`
- Not collected: `____` (say so plainly if the survey was skipped for build time)

## Intended scope and known gaps

- **Production scope:** screen **unknown numbers only**; saved contacts ring through. The
  prototype demonstrates the unknown-caller path.
- **Known gap:** a scammer spoofing a saved contact's number, or a scam that starts after a
  legitimate call connects, is not screened. Covering it would mean monitoring calls from
  known numbers — defensible only with on-device processing and explicit consent, and
  deliberately not built.
- **Responsible handling:** numbers shaped like codes, PINs, cards or account references are
  masked in API responses, the family view and anything written to disk. Evidence-quote
  validation runs on the raw in-memory transcript first, so masking never weakens the
  evidence check.

## Measured results

See `docs/EVALUATION.md`. Report counts and denominators, never bare percentages, and never
present fixture replay as a model result.

### The finding worth leading with

The NVIDIA track asks for a failure you found. This is ours, and it shaped the architecture:

**On every hosted Nemotron model we tested, the structured `credential_request` field is
markedly more reliable than the free-text `risk` label.** Asked to classify a caller saying
"I'm sending a six digit code, read it back to me", the models frequently answered
`needs_review` rather than `high_risk` — even after we added an explicit instruction that a
direct one-time-code request is high risk by definition. The structured field was correct
5/5 across credential phrasings on the model we shipped first.

So the only policy that ends a call requires three things, none of which is the risk label:
`credential_request` set, **plus** a quote that re-matches the caller turn it names, **plus**
that quote actually naming a credential. A confident wrong label cannot hang up on anyone.

This is why `docs/EVALUATION.md` reports two recall numbers. Model `high_risk` label recall
and system protective recall differ, and the gap is the point, not an embarrassment.

## Disclosures and eligibility

- [ ] Confirm current submission requirements with organisers.
- [ ] Confirm code-reuse disclosure requirements with organisers.
- **Do not** enter *No Wrapper* — Nemotron is used in the product.
- **Do not** claim *Beginner* eligibility. The Cold Start track is for teams that are 75%
  first-timers, which this team is not.
- Built during SteelHacks XIII by a two-person team of current Allegheny College
  undergraduates: Gabriel Salvatore and Miguel Orti Vila. AI coding assistants were used
  during development; disclose per event rules.

## Limitations to state out loud

1. Synthetic scenarios only; no claim about real-world prevention accuracy.
2. Turn-based browser prototype, not telephony.
3. Hosted-endpoint latency is variable: median 2.4–2.8 s, p95 3.2–4.2 s, worst observed
   6.0 s for one classification (n=70, primary model, dev runs). An attempt is cut off
   at 8 s and the whole chain at 12 s, after which the call degrades to family review.
6. Callers are told in the opening line that they are speaking to an AI assistant;
   recording and two-party consent law is not otherwise addressed.
4. Chromium only; Safari and Firefox untested.
5. The narrow end-call policy can still make mistakes — the measured cases are published
   rather than hidden.
