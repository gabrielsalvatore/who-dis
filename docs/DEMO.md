# Demo script (~90 seconds)

## Before you start

```bash
cd backend && ../.venv/bin/python -m uvicorn app.main:app --port 8000
../.venv/bin/python backend/scripts/warm_cache.py     # once; then it is instant
curl -s localhost:8000/api/health                     # setup_needs must be []
```

**Run one warm-up turn immediately before you present.** Cold hosted endpoints are slower,
and the first classification of a session is routinely the slowest. Start a call, send one
typed turn, then hit **Restart call**. It costs ten seconds and removes the worst outlier
from your actual demo.

**Have the offline replay open in a second tab** before you start, so the fallback is one
click away rather than something you go looking for under pressure.

- Open <http://localhost:8000>, click **Open family view**, drag that window so judges see
  it. Angle it toward them — the point is that *someone other than the person on the call*
  gets the alert.
- Check the mode badge reads **Live API**. If it says Fixture replay, say so out loud.
- Headphones or low volume: the assistant speaks, and the mic will pick it up otherwise.
  Push-to-talk is disabled while the assistant is speaking, but feedback is still unpleasant.
- Have the typed fallback ready. If the room is loud, use it and **say** you are using it.

## The run

**1. Frame it (15s).** "If someone's grandmother gets a scam call, the scammer talks to
*her*. CallKind answers instead. She never meets the scammer, and her family gets the
evidence." Point at the family window.

**2. Bank impersonation (30s).** Hold spacebar:

> "Hello, this is Dan calling from the fraud team at Northbridge Bank."

CallKind asks a neutral follow-up. Hold again:

> "We've blocked a suspicious charge. I'm sending a six digit code to your phone right now
> — read it back to me so I can verify you."

The filler phrase plays while it thinks. Then the refusal, and the call ends.

**Point at the family window and say the three things that matter:**
- the exact quote is highlighted in the transcript — *"Read it back to me so I can verify you"*
- the alert says **URGENT — ACTION NEEDED**, in words, not just colour
- the card shows **Model said: Needs review** / **CallKind did: Ended the call**

That last line is the whole pitch: *"The model didn't decide to hang up. The backend did,
because it re-checked that quote against the transcript. A confident wrong label can't end
a call on its own."*

**3. Reset, routine delivery (20s).** Click **Restart call**. The family window follows by
itself — don't reopen it.

> "Hi there, it's Marcus from Lakeside Parcel. I've got a package that needs a signature,
> I'll try again tomorrow between nine and eleven."

No alert. It takes a message. "It doesn't just flag everything — and notice it never says
the caller is *verified*, only that nothing alarming was said."

**4. Claimed family emergency (15s), if time.**

> "Grandma, it's me, I had an accident and I need three thousand dollars for bail right
> now. Please don't tell mum and dad."

Urgent alert, **call not ended**. "It won't hang up on what might be a real emergency, and
it won't authenticate him either. It hands it to a person."

**5. Close (10s).** Use these, in this order:

- *"Phones can already screen callers — an iPhone will answer an unknown number and ask
  who's calling. But it hands the transcript back to the person scammers are targeting and
  asks them to decide. CallKind makes that call for them, and brings in the family with the
  evidence."*
- The measured finding, in one line: *"The model's own risk label was right 5 times out of
  6 on our dev set. We don't trust it anyway — the only thing that can end a call is a quote
  we re-checked against the transcript."*
- The measured numbers from `docs/EVALUATION.md` — with denominators, out loud.
- One limitation. Suggested: *"This is a browser prototype, not a phone integration, and
  every scenario is synthetic. We can't claim a real-world prevention rate."*

## If something breaks

| What | Do this |
|---|---|
| Mic denied / no input | Use the typed fallback and **say** you're using it. Classification is still real. |
| A classification hangs | Filler covers ~2–3 s. Past that, say "hosted endpoint is under load" and keep talking. It falls back to the second Nemotron automatically. |
| Provider fails entirely | It degrades to **needs review** with a visible degraded badge. Show that — never concluding "safe" on failure is a feature, not an excuse. |
| Speech fails but text is fine | The assessment survives; click **Retry audio**. |
| Call ended, want to continue | **Restart call**. Turns are rejected after a call ends, on purpose. |

## Never do this

- Never present a fixture replay or a recorded run as live inference. If you demo offline,
  say "this is a recorded replay" before it starts.
- Never read out a real code, card number or account number, even as a joke.
- Don't claim the caller was "verified" — CallKind never verifies identity, and the UI is
  careful about this. Don't undo that in the narration.
