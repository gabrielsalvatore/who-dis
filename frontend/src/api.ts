import type { CallView, Health, TurnResult } from './types'

async function json<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (body?.detail) detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
    } catch { /* keep the status line */ }
    throw new Error(detail)
  }
  return res.json() as Promise<T>
}

export const getHealth = () => fetch('/api/health').then(json<Health>)

export const createCall = () =>
  fetch('/api/calls', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: '{}',
  }).then(json<CallView>)

export const getCall = (id: string) => fetch(`/api/calls/${id}`).then(json<CallView>)

export const getCurrentCall = () =>
  fetch('/api/calls/current').then(
    json<{ call_id: string | null; status: string | null; version: number }>,
  )

export const deleteCall = (id: string) =>
  fetch(`/api/calls/${id}`, { method: 'DELETE' }).then((r) => r.ok)

export function sendTurn(
  callId: string,
  requestId: string,
  payload: { text?: string; audio?: Blob; filename?: string },
): Promise<TurnResult> {
  const form = new FormData()
  form.append('request_id', requestId)
  if (payload.audio) form.append('audio', payload.audio, payload.filename ?? 'turn.webm')
  else form.append('text', payload.text ?? '')
  return fetch(`/api/calls/${callId}/turns`, { method: 'POST', body: form }).then(json<TurnResult>)
}

export const retryAudio = (callId: string, turnId: string) =>
  fetch(`/api/calls/${callId}/audio/${turnId}/retry`, { method: 'POST' }).then(
    json<{ audio_url: string; cached: boolean }>,
  )
