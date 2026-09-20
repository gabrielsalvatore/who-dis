import { useCallback, useEffect, useRef, useState } from 'react'
import { useCall } from '../useCall'
import { useRecorder } from '../useRecorder'
import { getReplays, type ReplayMeta } from '../api'
import { SCENARIOS } from '../scenarios'
import './phone.css'

type IconName = 'phone' | 'mic' | 'text' | 'transcript' | 'replay' | 'shield'
function Icon({ name }: { name: IconName }) {
  const paths: Record<IconName, React.ReactNode> = {
    phone: <path d="m5 3 4 1 1 5-3 2a15 15 0 0 0 6 6l2-3 5 1 1 4c0 1-1 2-2 2C10 21 3 14 3 5c0-1 1-2 2-2Z" />,
    mic: <><rect x="9" y="2" width="6" height="13" rx="3" /><path d="M5 10v2a7 7 0 0 0 14 0v-2M12 19v3m-4 0h8" /></>,
    text: <><rect x="2" y="5" width="20" height="14" rx="3" /><path d="M6 9h1m4 0h1m4 0h1M6 13h1m4 0h1m4 0h1M8 16h8" /></>,
    transcript: <><path d="M5 3h14v18H5zM8 8h8M8 12h8M8 16h5" /></>,
    replay: <><path d="M3 10a9 9 0 1 1 2 9M3 4v6h6" /><path d="m11 8 5 4-5 4Z" /></>,
    shield: <><path d="m12 2 8 3v6c0 5-4 9-8 11-4-2-8-6-8-11V5Z" /><path d="m8 12 3 3 5-6" /></>,
  }
  return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>
}

export function PhoneRoute() {
  const ctl = useCall()
  const { call, health, lastResult, processing, playing } = ctl
  const [starting, setStarting] = useState(false)
  const [ending, setEnding] = useState(false)
  const [typed, setTyped] = useState('')
  const [drawer, setDrawer] = useState<'text' | 'transcript' | null>(null)
  const [hint, setHint] = useState<string | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [tapMode, setTapMode] = useState(false)
  const [replays, setReplays] = useState<ReplayMeta | null>(null)
  const sending = useRef(false)
  const startingRef = useRef(false)
  const recorder = useRecorder(
    useCallback(() => setHint('Hold a little longer while you speak.'), []),
    recording => { void ctl.submit({ audio: recording.blob, filename: recording.filename }) },
  )
  const ended = call?.status === 'ended'
  const busy = processing || playing || starting || ending
  const canSubmit = !!call && !ended && !busy && !recorder.isRecording && recorder.status !== 'requesting'
  const canRecord = !!call && !ended && !busy && recorder.supported
  const mode = lastResult?.mode ?? call?.mode
  const modeLabel = mode === 'fixture_replay' || health?.app_mode === 'fixture' ? 'Offline replay' : mode === 'text_fallback' ? 'Typed call demo' : 'Voice call demo'
  const createdAt = call?.created_at
  const cancelRecording = recorder.cancel

  useEffect(() => { getReplays().then(setReplays).catch(() => undefined) }, [])
  useEffect(() => {
    if (createdAt == null || ended) return
    const tick = () => setElapsed(Math.max(0, Math.floor(Date.now() / 1000 - createdAt)))
    tick()
    const timer = window.setInterval(tick, 1000)
    return () => window.clearInterval(timer)
  }, [createdAt, ended])

  // Leave a call's evidence in the backend, but never leave its microphone running.
  useEffect(() => {
    const cancelOnHide = () => { if (document.hidden) cancelRecording() }
    document.addEventListener('visibilitychange', cancelOnHide)
    return () => document.removeEventListener('visibilitychange', cancelOnHide)
  }, [cancelRecording])

  const start = async (scenario?: string) => {
    if (startingRef.current || busy) return
    startingRef.current = true
    setStarting(true)
    setHint(null)
    recorder.cancel()
    setTyped('')
    setElapsed(0)
    try { await ctl.reset(scenario) }
    finally { setStarting(false); startingRef.current = false }
  }

  const sendRecording = async () => {
    if (sending.current) return
    sending.current = true
    try {
      const recording = await recorder.stop()
      if (recording) await ctl.submit({ audio: recording.blob, filename: recording.filename })
    } finally { sending.current = false }
  }

  const beginRecording = () => {
    if (!canRecord || recorder.isRecording || recorder.status === 'requesting') return
    setHint(null)
    void recorder.start()
  }

  const hangUp = async () => {
    if (busy) return
    recorder.cancel()
    setEnding(true)
    try { await ctl.endCall() }
    finally { setEnding(false) }
  }

  const clock = `${Math.floor(elapsed / 60).toString().padStart(2, '0')}:${(elapsed % 60).toString().padStart(2, '0')}`
  const status = starting ? 'Connecting…' : ending ? 'Ending call…' : playing ? 'WhoDis is speaking'
    : processing ? 'Screening your words…' : ended ? 'Call ended'
      : recorder.isRecording ? 'Listening to you' : recorder.status === 'requesting' ? 'Allow microphone access'
        : call ? clock : 'Safe calls. Peace of mind.'
  const reply = lastResult?.assistant_text ?? call?.turns.find(t => t.source === 'opening')?.text
  const showText = drawer === 'text' || (!!call && !recorder.supported && !ended)

  return (
    <main className="phone-page">
      <div className="phone-screen">
        <nav className="phone-nav" aria-label="Demo navigation">
          <a href="/">‹ Demo</a>
          <span>{modeLabel}</span>
          <a href="/family" target="_blank" rel="noopener noreferrer">Family ↗</a>
        </nav>

        <header className="phone-contact">
          <div className="phone-avatar"><Icon name="shield" /></div>
          <p className="phone-eyebrow">CALL SCREENING ASSISTANT</p>
          <h1>WhoDis</h1>
          <p className={`phone-status ${ended ? 'phone-ended' : ''}`} role="status">{status}</p>
        </header>

        <section className="phone-conversation" aria-label="Current response">
          {reply ? <>
            <span className="phone-caption-label">WHODIS</span>
            <p aria-live="polite">{reply}</p>
            {lastResult?.alert && <span className="phone-review-note">Family notified · {lastResult.alert.level === 'urgent' ? 'urgent review' : 'needs review'}</span>}
          </> : <p className="phone-welcome">You play the caller.<br />WhoDis answers for the family.</p>}
        </section>

        {(ctl.error || recorder.error || hint) && <div className="phone-notice" role="alert">
          {ctl.error || recorder.error || hint}
          {ctl.error && <button onClick={() => ctl.setError(null)}>Dismiss</button>}
        </div>}
        {health && health.setup_needs.length > 0 && <details className="phone-notice"><summary>Demo setup needed</summary><ul>{health.setup_needs.map(n => <li key={n}>{n}</li>)}</ul></details>}
        {!recorder.supported && <p className="phone-notice">{!window.isSecureContext ? 'Voice needs a secure HTTPS link on your phone. You can type your side of the call below.' : 'Microphone recording is unavailable. Use Type to continue the call.'}</p>}

        <div className="phone-tools">
          <button aria-expanded={showText} aria-controls="phone-typed-form" onClick={() => setDrawer(drawer === 'text' ? null : 'text')}><span><Icon name="text" /></span>Type</button>
          <button aria-expanded={drawer === 'transcript'} aria-controls="phone-transcript" onClick={() => setDrawer(drawer === 'transcript' ? null : 'transcript')}><span><Icon name="transcript" /></span>Transcript</button>
          <button disabled={!lastResult?.audio_url || busy || recorder.isRecording || recorder.status === 'requesting'} onClick={() => void ctl.replay()}><span><Icon name="replay" /></span>Replay</button>
        </div>

        {showText && <form id="phone-typed-form" className="phone-drawer" onSubmit={e => {
          e.preventDefault()
          if (!canSubmit || !typed.trim()) return
          void ctl.submit({ text: typed.trim() })
          setTyped('')
        }}>
          <label htmlFor="phone-typed">Your side of the call</label>
          <div className="phone-type-row"><input id="phone-typed" value={typed} onChange={e => setTyped(e.target.value)} placeholder="Type what you would say…" disabled={!canSubmit} /><button type="submit" disabled={!canSubmit || !typed.trim()}>Send</button></div>
          <p>Typed fallback uses the same screening policy.</p>
        </form>}

        {drawer === 'transcript' && <section id="phone-transcript" className="phone-drawer phone-transcript" aria-label="Call transcript">
          <h2>Transcript</h2>
          {call?.turns.map(turn => <p key={turn.turn_id}><strong>{turn.role === 'caller' ? 'You' : 'WhoDis'}</strong>{turn.text}</p>)}
          {!call && <p>Your conversation will appear here.</p>}
        </section>}

        {lastResult?.audio_error && <div className="phone-notice">The spoken reply is unavailable. You can read it above. <button disabled={busy || recorder.isRecording} onClick={() => void ctl.retryAudio()}>Retry audio</button></div>}

        <div className="phone-actions">
          {!call || (ended && !processing && !playing) ? <button className="phone-connect" disabled={starting} onClick={() => void start()}><Icon name="phone" />{starting ? 'Connecting…' : ended ? 'Call again' : 'Start call'}</button> : <>
            <div className="phone-talk-wrap">
              <button className={`phone-talk ${recorder.isRecording ? 'is-recording' : ''}`}
                disabled={!canRecord}
                aria-label={recorder.isRecording ? (tapMode ? 'Send recording' : 'Recording, release to send') : tapMode ? 'Start recording' : 'Hold to talk'}
                onPointerDown={e => {
                  if (tapMode) return
                  e.preventDefault()
                  e.currentTarget.setPointerCapture(e.pointerId)
                  beginRecording()
                }}
                onPointerUp={e => {
                  if (tapMode) return
                  e.preventDefault()
                  void sendRecording()
                  if (e.currentTarget.hasPointerCapture(e.pointerId)) e.currentTarget.releasePointerCapture(e.pointerId)
                }}
                onPointerCancel={() => recorder.cancel()}
                onLostPointerCapture={() => { if (!sending.current && !tapMode) recorder.cancel() }}
                onClick={() => { if (tapMode) { if (recorder.isRecording) void sendRecording(); else beginRecording() } }}
                onKeyDown={e => { if (!tapMode && (e.key === ' ' || e.key === 'Enter')) { e.preventDefault(); if (!e.repeat) beginRecording() } }}
                onKeyUp={e => { if (!tapMode && (e.key === ' ' || e.key === 'Enter')) { e.preventDefault(); void sendRecording() } }}
                onContextMenu={e => e.preventDefault()}
              ><Icon name="mic" /><span>{recorder.isRecording ? `${(recorder.elapsedMs / 1000).toFixed(1)}s · ${tapMode ? 'Tap to send' : 'Release to send'}` : tapMode ? 'Tap to record' : 'Hold to talk'}</span></button>
              <p>{recorder.isRecording ? '30 seconds maximum' : 'One turn at a time. WhoDis replies out loud.'}</p>
            </div>
            <button className="phone-hangup" aria-label="End call" disabled={busy} onClick={() => void hangUp()}><Icon name="phone" /></button>
            <span className="phone-hangup-label">End call</span>
          </>}
        </div>

        <details className="phone-demo-options">
          <summary>Demo options</summary>
          <label className="phone-tap-option"><input type="checkbox" checked={tapMode} disabled={busy || recorder.isRecording || recorder.status === 'requesting'} onChange={e => setTapMode(e.target.checked)} /> Tap to record, then tap to send</label>
          {(recorder.isRecording || recorder.status === 'requesting') && <button onClick={recorder.cancel}>Discard recording</button>}
          <h2>Try a conversation</h2>
          {SCENARIOS.map(s => <details key={s.name}><summary>{s.name}</summary><ol>{s.lines.map(line => <li key={line}>{line}</li>)}</ol></details>)}
          {replays && replays.scenarios.length > 0 && <details><summary>Offline replay</summary><p>Recorded run; no live inference. Your submitted words are ignored.</p>{replays.scenarios.map(name => <button key={name} disabled={busy || recorder.isRecording || recorder.status === 'requesting'} onClick={() => void start(name)}>{name.replaceAll('_', ' ')}</button>)}</details>}
        </details>
        <footer className="phone-footer">Browser demo · Fictional calls · Not a real phone call</footer>
        <div className="phone-home-indicator" aria-hidden="true" />
      </div>
    </main>
  )
}
