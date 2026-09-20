# Evaluation

Synthetic scenarios only. Nothing here supports a claim about real-world prevention
accuracy. Both systems see identical transcript prefixes, neither ever sees a future
turn, and both are run through the **same** policy layer, so what is compared is the
whole system rather than a lone classifier. No TTS is generated during evaluation.

## How to read the two recall numbers

**Model `high_risk` label recall** is how often Nemotron picked the word `high_risk`.
**System protective recall** is how often WhoDis actually did something protective:
ended the call or raised a review alert. The second is the one that matters, and the
gap between them is the whole architectural point: the backend acts on *verified
evidence*, not on the model's choice of label. On a direct one-time-code request the
model frequently says `needs_review`, yet the system still ends the call, because
`credential_request` plus a re-verified quote is what the policy keys on.

## Status of the held-out test set

**The test set has not been frozen and has not been run.** The build spec requires a
human to review all 24 drafted conversations and their per-prefix labels before the
set is frozen. That review is incomplete: two flagged judgement calls were confirmed
(both as drafted, 0 labels changed), but the full 24 were not signed off.

So every number below is from the **development split**, which is the split tuning was
allowed against. Dev-set numbers are not held-out numbers and should not be presented
as though they were. The prompt has not been tuned against the test set.

## Development set

`12` conversations · `24` prefixes · dataset `dcd379a81d1` (tuning split, freezing does not apply) · run `2026-09-20T02:20:52.338993+00:00`

| Metric | kw-v1 | nvidia/nemotron-3-nano-omni-30b-a3b-reasoning / prompt p7ddae94c |
|---|---|---|
| System protective recall on scams | 5/6 (83%) | 6/6 (100%) |
| Model `high_risk` label recall | 3/6 (50%) | 3/6 (50%) |
| Benign high-risk false alarms | 1/6 (17%) | 0/6 (0%) |
| Benign calls incorrectly ended | 1/6 (17%) | 0/6 (0%) |
| Benign calls sent to review | 2/6 (33%) | 3/6 (50%) |
| Benign handled without review | 4/6 (67%) | 3/6 (50%) |
| Prefix risk within acceptable set | 21/24 (88%) | 24/24 (100%) |
| Forbidden-action violations | 1/24 (4%) | 0/24 (0%) |
| Evidence quotes verified | 13/13 (100%) | 21/21 (100%) |
| Classify latency median | 0.0 ms | 2803.2 ms |
| Classify latency p95 | 0.1 ms | 4208.6 ms |
| Latency sample size | 24 | 22 |
| Provider failures | 0 | 2 |

Scams missed entirely: `none`. First protective turn among detected scams (mean): `1.67`. Mean is over DETECTED scams only; missed calls are listed separately.

### Failure cases: keyword

**dev-08 (bank warning negation): keyword took a forbidden action.**

> Caller: "I'm calling to remind you that we will never ask you to read out a one time code. Never give it to anyone who rings you."

Model said `high_risk`; policy chose `end_simulated_call`. Expected any of ['no_warning_signs', 'needs_review'], and `end_simulated_call` was forbidden here.

## Held-out test set

*Not yet run.*

## Hosted-endpoint reliability and model selection

Measured 2026-09-20T01:03:48.232151+00:00 with a 8 s timeout. Point-in-time measurement of shared hosted endpoints under hackathon load.

| Model | succeeded | p50 | p95 | errors |
|---|---|---|---|---|
| `nemotron-3-super-120b-a12b` | 4/8 | 1615.9 ms | 1950.4 ms | {'HTTP503': 4} |
| `nemotron-3-nano-omni-30b-a3b-reasoning` | 6/8 | 2785.9 ms | 3034.3 ms | {'HTTP503': 2} |
| `nemotron-3.5-lightning-30b-a3b` | 5/8 | 3190.4 ms | 3267.9 ms | {'ReadTimeout': 3} |

Two things to state plainly here.

**Availability is noisy and is not a stable differentiator.** Across two sweeps taken
minutes apart the ranking inverted: one model went 7/8 then 4/8, another 5/8 then
6/8. These are shared endpoints under hackathon load and `503 ResourceExhausted` is
common. No model choice fixes that, which is why the system retries once, then falls
back to a second Nemotron, then degrades to review. Two turns of the latest dev run
hit a 503; both degraded to review, which is the intended behaviour and is counted
in the table above rather than excluded from it.

**Latency is the stable signal**, and it drove the model choice together with dev-set
accuracy. Reasoning mode is explicitly disabled (`enable_thinking: false`); the
endpoint returned no `reasoning_content` under that setting, and output is capped at
260 tokens with temperature 0, because every extra token is user-visible delay.

## Which Nemotron is primary, and why

Primary is `nemotron-3-nano-omni-30b-a3b-reasoning`. `nemotron-3-super-120b-a12b` is
the fallback, called only after the primary returns a transient failure.

The two models differ most on the metric this project argues is not load-bearing.
super-120b labels more scam prefixes `high_risk` (5/6 against nano's 3/6), and system
protective recall is 6/6 on both. The policy ends or escalates the same calls either
way, because it acts on a re-verified credential-bearing quote rather than on the
label. Better label recall bought nothing the family would ever see.

The swap to super-120b looked like it cost benign precision: benign calls sent to the
family for review went 1/6 to 3/6. **That number did not reproduce.** Rerunning nano on
the same twelve conversations also put 3/6 benign calls into review, and one of those
three was a provider 503 degrading to review rather than anything the model decided.
Two runs of the same model on the same data giving 1/6 and 3/6 is the measurement
moving, not the model. With six benign conversations, one conversation is 17 points, so
this split cannot separate the two models on benign precision and that comparison
should not be quoted as though it can.

Tail latency is the one user-visible difference, and it is weak. nano was faster on
both dev runs (p95 3424 ms and 4209 ms against 4722 ms), while the point-in-time
endpoint sweep above had super-120b the faster of the two. Shared hosted endpoints
under load are not stable enough for that gap to be decisive either.

So the ordering is a weak preference, not a result: nano is primary on the dev-run
latency tail, super-120b is the fallback that covers transient failures, and neither
position rests on label recall. The fallback chain matters more than which model is
first in it. False family alerts are the failure mode worth spending effort on, because
alert fatigue is what makes a family stop reading the alerts, but this evaluation is
not powered to measure them at the resolution a model choice would need.

## The keyword baseline

`eval/keyword_baseline.py`, version `kw-v1`, frozen 2026-09-19. Rules are published in
full in that file and were not tuned against results. It matches credential, payment,
urgency, secrecy and authority vocabulary in the caller's words.

Its instructive failure is `dev-08`: a bank calling to warn a customer *never* to read
out a one-time code. The baseline matches the words `one time code`, calls it
`high_risk`, and **hangs up on the warning**. It cannot tell who is asking whom to do
what. That single case is the clearest argument for using a language model here at all.

## What is not measured

- Real callers, real microphones, real rooms. Spoken checks used synthesised speech
  through a fake capture device plus a small number of manual runs.
- Any browser other than Chromium.
- Anything about real-world scam prevalence, prevention or financial loss.
- Fixture replay is a recording of earlier real inference and is excluded from every
  number above.

