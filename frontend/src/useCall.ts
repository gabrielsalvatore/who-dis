import { useCallback, useEffect, useRef, useState } from 'react'
import * as api from './api'
import type { CallView, Health, TurnResult } from './types'

/** Delay before the filler starts. If the pipeline beats this, the filler is skipped. */
const FILLER_DELAY_MS = 250
/**
 * A second cached phrase for the long tail. Hosted-endpoint p95 is ~4.5 s and the
 * worst observed single classification was 14 s; one "One moment." does not cover
 * that, and silence on a phone call reads as a dropped line.
 */
const SECOND_FILLER_DELAY_MS = 4000

export interface TurnTiming {
  timeToFillerMs: number | null        // null when the filler was skipped
  timeToSecondFillerMs: number | null  // null when the second filler was not needed
  timeToResponseMs: number             // wall time until the assistant's real answer
}

function newRequestId() {
  return (crypto.randomUUID?.() ?? `${Date.now()}-${Math.random()}`).toString()
}

export function useCall() {
  const [health, setHealth] = useState<Health | null>(null)
  const [call, setCall] = useState<CallView | null>(null)
  const [lastResult, setLastResult] = useState<TurnResult | null>(null)
  const [processing, setProcessing] = useState(false)
  const [processingMs, setProcessingMs] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [timing, setTiming] = useState<TurnTiming | null>(null)

  const audioRef = useRef<HTMLAudioElement | null>(null)
  const fillerTimerRef = useRef<number | null>(null)
  const secondFillerTimerRef = useRef<number | null>(null)
  const respondedRef = useRef(false)
  const tickRef = useRef<number | null>(null)

  useEffect(() => {
    api.getHealth().then(setHealth).catch((e) => setError(String(e.message ?? e)))
  }, [])

  const clearFillerTimers = useCallback(() => {
    if (fillerTimerRef.current) window.clearTimeout(fillerTimerRef.current)
    if (secondFillerTimerRef.current) window.clearTimeout(secondFillerTimerRef.current)
    fillerTimerRef.current = null
    secondFillerTimerRef.current = null
  }, [])

  const stopAudio = useCallback(() => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current = null
    }
    setPlaying(false)
  }, [])

  /** Play one clip and resolve when it finishes (or fails). */
  const playClip = useCallback((src: string): Promise<void> => {
    return new Promise((resolve) => {
      const audio = new Audio(src)
      audioRef.current = audio
      setPlaying(true)
      const done = () => {
        if (audioRef.current === audio) {
          audioRef.current = null
          setPlaying(false)
        }
        resolve()
      }
      audio.onended = done
      audio.onerror = done
      audio.play().catch(() => {
        // Autoplay blocked: surface it, do not hang the turn.
        setError('Your browser blocked audio playback. Click anywhere, then use Replay.')
        done()
      })
    })
  }, [])

  const startCall = useCallback(async (replayScenario?: string) => {
    setError(null)
    stopAudio()
    try {
      const view = await api.createCall(replayScenario)
      setCall(view)
      setLastResult(null)
      setTiming(null)
      return view
    } catch (e) {
      setError(String((e as Error).message ?? e))
      return null
    }
  }, [stopAudio])

  const reset = useCallback(async (replayScenario?: string) => {
    stopAudio()
    if (call) await api.deleteCall(call.call_id).catch(() => undefined)
    setCall(null)
    setLastResult(null)
    setTiming(null)
    setError(null)
    return startCall(replayScenario)
  }, [call, startCall, stopAudio])

  const refresh = useCallback(async () => {
    if (!call) return
    try {
      setCall(await api.getCall(call.call_id))
    } catch { /* a deleted call is not an error worth surfacing here */ }
  }, [call])

  const endCall = useCallback(async () => {
    if (!call || processing) return
    stopAudio()
    setError(null)
    try {
      setCall(await api.endCall(call.call_id))
    } catch (e) {
      setError(String((e as Error).message ?? e))
    }
  }, [call, processing, stopAudio])

  const submit = useCallback(
    async (payload: { text?: string; audio?: Blob; filename?: string }) => {
      if (!call || processing) return
      setError(null)
      setProcessing(true)
      setProcessingMs(0)
      setTiming(null)

      const t0 = performance.now()
      let fillerAt: number | null = null
      let secondFillerAt: number | null = null
      let fillerPlayback: Promise<void> = Promise.resolve()
      respondedRef.current = false

      tickRef.current = window.setInterval(
        () => setProcessingMs(performance.now() - t0),
        100,
      )

      // Fillers cover provider latency. Both are cached fixed phrases that say
      // nothing about the outcome, so they can play before any decision exists.
      // They are queued rather than overlapped, so we never talk over ourselves.
      if (health?.speech_configured) {
        fillerTimerRef.current = window.setTimeout(() => {
          fillerAt = performance.now() - t0
          fillerPlayback = fillerPlayback.then(() => playClip('/api/audio/phrase/filler'))
        }, FILLER_DELAY_MS)

        secondFillerTimerRef.current = window.setTimeout(() => {
          if (respondedRef.current) return
          secondFillerAt = performance.now() - t0
          fillerPlayback = fillerPlayback.then(() =>
            respondedRef.current
              ? Promise.resolve()
              : playClip('/api/audio/phrase/filler_second'),
          )
        }, SECOND_FILLER_DELAY_MS)
      }

      try {
        const result = await api.sendTurn(call.call_id, newRequestId(), payload)
        const responseAt = performance.now() - t0
        respondedRef.current = true

        clearFillerTimers()
        setLastResult(result)
        setTiming({
          timeToFillerMs: fillerAt,
          timeToSecondFillerMs: secondFillerAt,
          timeToResponseMs: responseAt,
        })
        await api.getCall(call.call_id).then(setCall).catch(() => undefined)

        await fillerPlayback            // never talk over the filler
        if (result.audio_url) await playClip(result.audio_url)
      } catch (e) {
        respondedRef.current = true
        clearFillerTimers()
        setError(String((e as Error).message ?? e))
        await refresh()
      } finally {
        if (tickRef.current) window.clearInterval(tickRef.current)
        tickRef.current = null
        setProcessing(false)
        setProcessingMs(0)
      }
    },
    [call, processing, health, playClip, refresh, clearFillerTimers],
  )

  const replay = useCallback(async () => {
    if (lastResult?.audio_url) await playClip(lastResult.audio_url)
  }, [lastResult, playClip])

  const retryAudio = useCallback(async () => {
    if (!call || !lastResult) return
    const assistantTurn = [...(call.turns ?? [])].reverse().find((t) => t.role === 'assistant')
    if (!assistantTurn) return
    try {
      const { audio_url } = await api.retryAudio(call.call_id, assistantTurn.turn_id)
      setLastResult({ ...lastResult, audio_url, audio_error: null })
      await playClip(audio_url)
    } catch (e) {
      setError(String((e as Error).message ?? e))
    }
  }, [call, lastResult, playClip])

  useEffect(() => () => {
    clearFillerTimers()
    if (tickRef.current) window.clearInterval(tickRef.current)
  }, [clearFillerTimers])

  return {
    health, call, lastResult, processing, processingMs, playing, error, timing,
    startCall, reset, submit, replay, retryAudio, refresh, stopAudio, setError, endCall,
  }
}

/**
 * Family-view data source. Follows whichever call is current, so the window keeps
 * working across a reset without being reopened. Simple polling; no websockets.
 */
export function useFamilyFeed(pollMs = 1000, fixedCallId?: string) {
  const [call, setCall] = useState<CallView | null>(null)
  const [health, setHealth] = useState<Health | null>(null)
  const [offline, setOffline] = useState(false)

  useEffect(() => {
    api.getHealth().then(setHealth).catch(() => undefined)
  }, [])

  useEffect(() => {
    let cancelled = false
    let timer: number

    const tick = async () => {
      try {
        let id = fixedCallId
        if (!id) {
          const current = await api.getCurrentCall()
          id = current.call_id ?? undefined
        }
        if (cancelled) return
        if (!id) {
          setCall(null)
        } else {
          setCall(await api.getCall(id))
        }
        setOffline(false)
      } catch {
        if (!cancelled) setOffline(true)
      } finally {
        if (!cancelled) timer = window.setTimeout(tick, pollMs)
      }
    }
    tick()
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [pollMs, fixedCallId])

  return { call, health, offline }
}
