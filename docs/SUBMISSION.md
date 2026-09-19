# Submission notes

## One-liner

CallKind screens suspicious conversations and gives a trusted family member the evidence to
review.

## What was built

A turn-based browser voice prototype. The presenter plays a caller and speaks one turn at a
time with push-to-talk; the assistant answers aloud; a family window shows the transcript,
the exact quotes that caused concern, and the action taken. Local only, one process.

**Not** a phone-network integration, not continuous live-call monitoring, no call
forwarding, no identity verification. All scenarios are synthetic.

## Differentiation

Google already ships live scam detection on calls. The difference in one sentence:

> Google warns the person already on the call; CallKind answers so the vulnerable person
> never talks to the scammer, and gives the family the evidence.

The angle is **delegated screening plus understandable family review**, not inventing
content-based scam detection.

## Track fit

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

**PNC / Compound.** The detection targets behaviours associated with financial scams —
credential requests, payment pressure, secrecy, manufactured urgency, authority
impersonation — rather than any specific institution. All financial examples are invented.

## Measured results

See `docs/EVALUATION.md`. Report counts and denominators, never bare percentages, and never
present fixture replay as a model result.

## Attendee survey (to be filled in by Gabriel, not by Claude Code)

Time-boxed to 30 minutes, only after the vertical slice works. Two questions, raw counts
only, no extrapolation to market size, willingness to pay, or real-world demand.

- Date: ____________  Setting: SteelHacks XIII attendees  Sample size: n = ____
- "Has an older relative or someone you know been targeted by a phone scam?" — ____ of ____ said yes
- "Would you set something like this up for them?" — ____ of ____ said yes

*Leave blank if the survey was not run.*

## Disclosures and eligibility

- [ ] Confirm current submission requirements with organisers.
- [ ] Confirm code-reuse disclosure requirements with organisers.
- **Do not** enter *No Wrapper* — Nemotron is used in the product.
- **Do not** claim *Beginner* eligibility — Gabriel is a professional engineer.
- Built solo during SteelHacks XIII. Scaffolding and implementation assisted by Claude Code;
  disclose per event rules.

## Limitations to state out loud

1. Synthetic scenarios only; no claim about real-world prevention accuracy.
2. Turn-based browser prototype, not telephony.
3. Hosted-endpoint latency is variable (0.9 s – 14.3 s observed for one classification).
4. Chromium only; Safari and Firefox untested.
5. The narrow end-call policy can still make mistakes — the measured cases are published
   rather than hidden.
