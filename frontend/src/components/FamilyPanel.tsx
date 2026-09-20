import { useEffect, useMemo, useRef, useState } from 'react'
import { ACTION_LABEL, RISK_LABEL } from '../types'
import type { Alert, Assessment, CallView, Health, PolicyDecision, Turn } from '../types'
import { ModeBadge } from './ModeBadge'

/** Short WebAudio chime. Avoids shipping an audio asset for one notification. */
function chime() {
  try {
    const Ctx = window.AudioContext ?? (window as any).webkitAudioContext
    if (!Ctx) return
    const ctx = new Ctx()
    const osc = ctx.createOscillator()
    const gain = ctx.createGain()
    osc.connect(gain)
    gain.connect(ctx.destination)
    osc.frequency.setValueAtTime(880, ctx.currentTime)
    osc.frequency.setValueAtTime(1170, ctx.currentTime + 0.12)
    gain.gain.setValueAtTime(0.0001, ctx.currentTime)
    gain.gain.exponentialRampToValueAtTime(0.25, ctx.currentTime + 0.02)
    gain.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.4)
    osc.start()
    osc.stop(ctx.currentTime + 0.42)
    setTimeout(() => ctx.close().catch(() => undefined), 700)
  } catch { /* a missing chime is never worth an error */ }
}

/** Wraps each verified evidence quote found in a caller turn with a <mark>. */
function HighlightedText({ text, quotes }: { text: string; quotes: string[] }) {
  const segments = useMemo(() => {
    if (quotes.length === 0) return [{ text, hit: false }]
    const ranges: Array<[number, number]> = []
    const haystack = text.toLowerCase()
    for (const q of quotes) {
      const needle = q.toLowerCase().trim()
      if (!needle) continue
      const at = haystack.indexOf(needle)
      if (at >= 0) ranges.push([at, at + needle.length])
    }
    if (ranges.length === 0) return [{ text, hit: false }]
    ranges.sort((a, b) => a[0] - b[0])
    const merged: Array<[number, number]> = []
    for (const r of ranges) {
      const last = merged[merged.length - 1]
      if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1])
      else merged.push([...r] as [number, number])
    }
    const out: Array<{ text: string; hit: boolean }> = []
    let cursor = 0
    for (const [s, e] of merged) {
      if (s > cursor) out.push({ text: text.slice(cursor, s), hit: false })
      out.push({ text: text.slice(s, e), hit: true })
      cursor = e
    }
    if (cursor < text.length) out.push({ text: text.slice(cursor), hit: false })
    return out
  }, [text, quotes])

  return (
    <>
      {segments.map((s, i) =>
        s.hit ? <mark key={i}>{s.text}</mark> : <span key={i}>{s.text}</span>,
      )}
    </>
  )
}

function AlertCard({ alert }: { alert: Alert }) {
  const urgent = alert.level === 'urgent'
  return (
    <article className={`alert-card ${urgent ? 'alert-urgent' : 'alert-review'}`}>
      <header>
        {/* Text label, never colour alone. */}
        <span className="alert-tag">{urgent ? 'Urgent, action needed' : 'Please review'}</span>
        <h3>{alert.headline}</h3>
      </header>
      <p className="alert-summary">{alert.summary}</p>
      {alert.evidence.length > 0 && (
        <ul className="evidence-list">
          {alert.evidence.map((e, i) => (
            <li key={i}>
              <span className="signal-tag">{e.signal.replace(/_/g, ' ')}</span>
              <q>{e.quote}</q>
              <span className="turn-ref">{e.turn_id}</span>
            </li>
          ))}
        </ul>
      )}
      {alert.recommended_action && (
        <p className="alert-advice">
          <strong>What to do:</strong> {alert.recommended_action}
        </p>
      )}
      <footer className="alert-foot">
        <span>Model said: <strong>{alert.model_risk ? RISK_LABEL[alert.model_risk] : 'n/a'}</strong></span>
        <span>WhoDis did: <strong>{alert.policy_action ? ACTION_LABEL[alert.policy_action] : 'n/a'}</strong></span>
      </footer>
    </article>
  )
}

function TurnRow({ turn, assessment }: { turn: Turn; assessment?: Assessment }) {
  const quotes =
    turn.role === 'caller' && assessment
      ? assessment.evidence.filter((e) => e.verified && e.turn_id === turn.turn_id).map((e) => e.quote)
      : []
  return (
    <li className={`turn turn-${turn.role}`}>
      <div className="turn-meta">
        <span className="turn-who">{turn.role === 'caller' ? 'Caller' : 'WhoDis'}</span>
        <span className="turn-id">{turn.turn_id}</span>
        {turn.source === 'speech' && <span className="turn-src">spoken</span>}
        {turn.source === 'text' && <span className="turn-src">typed</span>}
      </div>
      <p className="turn-text">
        <HighlightedText text={turn.text} quotes={quotes} />
      </p>
    </li>
  )
}

export function FamilyPanel({
  call,
  health,
  standalone = false,
  offline = false,
}: {
  call: CallView | null
  health: Health | null
  standalone?: boolean
  offline?: boolean
}) {
  const [muted, setMuted] = useState(() => localStorage.getItem('ck-muted') === '1')
  const seenAlerts = useRef<Set<string>>(new Set())
  const [flash, setFlash] = useState(false)

  const alerts = call?.alerts ?? []

  useEffect(() => {
    let isNew = false
    for (const a of alerts) {
      if (!seenAlerts.current.has(a.alert_id)) {
        seenAlerts.current.add(a.alert_id)
        isNew = true
      }
    }
    if (isNew && seenAlerts.current.size > 0) {
      setFlash(true)
      if (!muted) chime()
      const t = setTimeout(() => setFlash(false), 1600)
      return () => clearTimeout(t)
    }
  }, [alerts, muted])

  const toggleMute = () => {
    setMuted((m) => {
      localStorage.setItem('ck-muted', m ? '0' : '1')
      return !m
    })
  }

  // Assessment i corresponds to caller turn i+1.
  const assessmentForCallerTurn = (turnId: string): Assessment | undefined => {
    const n = Number(turnId.split('-')[1])
    return call?.assessments[n - 1]
  }

  const latestDecision: PolicyDecision | undefined = call?.decisions[call.decisions.length - 1]
  const latestAssessment: Assessment | undefined = call?.assessments[call.assessments.length - 1]

  return (
    <section className={`panel family-panel ${flash ? 'flash' : ''}`} aria-live="polite">
      <header className="panel-head">
        <div>
          <h2>Family view</h2>
          <p className="panel-sub">
            What a trusted family member sees. {standalone ? 'Following the active call.' : ''}
          </p>
        </div>
        <button className="ghost small" onClick={toggleMute} aria-pressed={muted}>
          {muted ? 'Sound off' : 'Sound on'}
        </button>
      </header>

      {call && <ModeBadge mode={call.mode} health={health} />}

      {offline && <p className="notice">Cannot reach the WhoDis server. Retrying…</p>}

      {!call && !offline && (
        <p className="notice">
          No active call. Start one in the caller window and it will appear here.
        </p>
      )}

      {call && (
        <>
          <div className="status-row">
            <span className={`status-pill status-${call.status}`}>
              {call.status === 'active' ? 'Call in progress' : 'Call ended'}
            </span>
            {latestAssessment && (
              <span className={`risk-pill risk-${latestAssessment.risk}`}>
                {RISK_LABEL[latestAssessment.risk]}
              </span>
            )}
            {latestAssessment?.status === 'degraded' && (
              <span className="risk-pill risk-degraded">Screening degraded</span>
            )}
          </div>

          {latestDecision && (
            <div className="outcome">
              <h3>What WhoDis did</h3>
              <p className="outcome-action">{ACTION_LABEL[latestDecision.action]}</p>
              <p className="outcome-reason">{latestDecision.reason}</p>
              {latestAssessment && (
                <p className="outcome-split">
                  The model reported <strong>{RISK_LABEL[latestAssessment.risk]}</strong>
                  {latestAssessment.scam_type !== 'unknown' &&
                    ` (${latestAssessment.scam_type.replace(/_/g, ' ')})`}
                  . The decision above was made by WhoDis's policy, not by the model.
                </p>
              )}
            </div>
          )}

          {alerts.length > 0 ? (
            <div className="alerts">
              {[...alerts].reverse().map((a) => (
                <AlertCard key={a.alert_id} alert={a} />
              ))}
            </div>
          ) : (
            <p className="notice quiet">No alerts raised for this call.</p>
          )}

          <h3 className="transcript-head">Transcript</h3>
          <p className="fine masking-note">
            Numbers that look like codes, PINs or account details are masked.
          </p>
          <ul className="transcript">
            {call.turns.map((t) => (
              <TurnRow
                key={t.turn_id}
                turn={t}
                assessment={t.role === 'caller' ? assessmentForCallerTurn(t.turn_id) : undefined}
              />
            ))}
          </ul>
          <p className="disclaimer">
            WhoDis never confirms a caller's identity and never connects an unverified
            caller. "No warning signs" means nothing alarming was said, not that the caller
            is who they claim to be. To check who someone is, call them back on a number you
            already have.
          </p>
        </>
      )}
    </section>
  )
}
