import { useCallback, useEffect, useRef, useState } from 'react'

export const MAX_RECORDING_MS = 30_000
export const MIN_RECORDING_MS = 500   // shorter than this is an accidental tap

/** Browsers disagree about container/codec support, so ask rather than assume. */
export function pickMimeType(): string | null {
  if (typeof MediaRecorder === 'undefined') return null
  const candidates = [
    'audio/webm;codecs=opus',
    'audio/webm',
    'audio/ogg;codecs=opus',
    'audio/mp4',          // Safari
    'audio/mpeg',
  ]
  for (const t of candidates) {
    if (MediaRecorder.isTypeSupported?.(t)) return t
  }
  return ''                // let the browser choose its own default
}

export function extensionFor(mime: string): string {
  if (mime.includes('webm')) return 'webm'
  if (mime.includes('ogg')) return 'ogg'
  if (mime.includes('mp4')) return 'm4a'
  if (mime.includes('mpeg')) return 'mp3'
  return 'webm'
}

export type RecorderStatus = 'idle' | 'requesting' | 'recording' | 'unsupported' | 'denied'

export interface Recording {
  blob: Blob
  durationMs: number
  filename: string
}

export function useRecorder(onTooShort: () => void, onAutoStop?: (recording: Recording) => void) {
  const [status, setStatus] = useState<RecorderStatus>('idle')
  const [elapsedMs, setElapsedMs] = useState(0)
  const [error, setError] = useState<string | null>(null)

  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const startedAtRef = useRef(0)
  const streamRef = useRef<MediaStream | null>(null)
  const capTimerRef = useRef<number | null>(null)
  const tickRef = useRef<number | null>(null)
  const resolveRef = useRef<((r: Recording | null) => void) | null>(null)
  // True only between press and release. getUserMedia is async, so a quick tap can
  // release before the microphone is even open; without this the recorder would
  // start after the user already let go and keep running.
  const desiredRef = useRef(false)

  const supported =
    typeof MediaRecorder !== 'undefined' &&
    typeof navigator !== 'undefined' &&
    !!navigator.mediaDevices?.getUserMedia

  const cleanup = useCallback(() => {
    if (capTimerRef.current) window.clearTimeout(capTimerRef.current)
    if (tickRef.current) window.clearInterval(tickRef.current)
    capTimerRef.current = null
    tickRef.current = null
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    recorderRef.current = null
    setElapsedMs(0)
  }, [])

  useEffect(() => cleanup, [cleanup])

  const start = useCallback(async () => {
    if (!supported) {
      setStatus('unsupported')
      setError('This browser cannot record audio. Use the typed fallback below.')
      return false
    }
    if (recorderRef.current) return false
    desiredRef.current = true
    setError(null)
    setStatus('requesting')
    let stream: MediaStream
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (e) {
      desiredRef.current = false
      const err = e as DOMException
      setStatus('denied')
      setError(
        err?.name === 'NotAllowedError'
          ? 'Microphone permission was denied. Allow it in your browser, or use the typed fallback below.'
          : `Could not open the microphone (${err?.name ?? 'error'}). Use the typed fallback below.`,
      )
      return false
    }

    if (!desiredRef.current) {
      // Released before the microphone opened: treat it as the accidental tap it was.
      stream.getTracks().forEach((t) => t.stop())
      setStatus('idle')
      onTooShort()
      return false
    }

    const mime = pickMimeType()
    const recorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream)
    chunksRef.current = []
    streamRef.current = stream
    recorderRef.current = recorder

    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data)
    }
    recorder.onstop = () => {
      const durationMs = Date.now() - startedAtRef.current
      const type = recorder.mimeType || mime || 'audio/webm'
      const blob = new Blob(chunksRef.current, { type })
      cleanup()
      setStatus('idle')
      const resolve = resolveRef.current
      resolveRef.current = null
      if (durationMs < MIN_RECORDING_MS || blob.size === 0) {
        onTooShort()
        resolve?.(null)
        return
      }
      const recording = { blob, durationMs, filename: `turn.${extensionFor(type)}` }
      if (resolve) resolve(recording)
      else onAutoStop?.(recording)
    }

    startedAtRef.current = Date.now()
    recorder.start()
    setStatus('recording')
    setElapsedMs(0)
    tickRef.current = window.setInterval(
      () => setElapsedMs(Date.now() - startedAtRef.current),
      100,
    )
    capTimerRef.current = window.setTimeout(() => {
      if (recorderRef.current?.state === 'recording') recorderRef.current.stop()
    }, MAX_RECORDING_MS)
    return true
  }, [cleanup, onTooShort, onAutoStop, supported])

  /** Stop and resolve with the recording, or null if it was too short. */
  const stop = useCallback((): Promise<Recording | null> => {
    desiredRef.current = false
    const recorder = recorderRef.current
    if (!recorder || recorder.state !== 'recording') return Promise.resolve(null)
    return new Promise<Recording | null>((resolve) => {
      resolveRef.current = resolve
      recorder.stop()
    })
  }, [])

  const cancel = useCallback(() => {
    desiredRef.current = false
    const recorder = recorderRef.current
    resolveRef.current = null
    if (recorder) {
      recorder.onstop = null
      if (recorder.state === 'recording') recorder.stop()
    }
    cleanup()
    setStatus('idle')
  }, [cleanup])

  return { status, elapsedMs, error, supported, start, stop, cancel, isRecording: status === 'recording' }
}

/** True when the event came from somewhere the spacebar means "space". */
export function isTypingTarget(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  if (!el) return false
  const tag = el.tagName
  return (
    tag === 'INPUT' ||
    tag === 'TEXTAREA' ||
    tag === 'SELECT' ||
    el.isContentEditable === true
  )
}
