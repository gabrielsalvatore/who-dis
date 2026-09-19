// Mirrors backend/app/schemas.py. Kept hand-written and small rather than generated.

export type Risk = 'no_warning_signs' | 'needs_review' | 'high_risk'
export type Action = 'continue' | 'take_message' | 'request_family_review' | 'end_simulated_call'
export type CallStatus = 'active' | 'ended'
export type Mode = 'live_api' | 'text_fallback' | 'fixture_replay'

export interface Evidence {
  turn_id: string
  quote: string
  signal: string
  verified: boolean
}

export interface Assessment {
  risk: Risk
  scam_type: string
  emergency_claimed: boolean
  credential_request: boolean
  evidence: Evidence[]
  summary: string
  question_id: string | null
  status: 'ok' | 'degraded'
  degraded_reason: string | null
  model_id: string | null
  prompt_version: string | null
  latency_ms: number | null
  used_fallback_model: boolean
}

export interface PolicyDecision {
  action: Action
  assistant_text: string
  reason: string
  ends_call: boolean
  alert_level: 'review' | 'urgent' | null
}

export interface Turn {
  turn_id: string
  role: 'caller' | 'assistant'
  text: string
  source: 'speech' | 'text' | 'opening' | 'fixture'
  ts: number
}

export interface Alert {
  alert_id: string
  level: 'review' | 'urgent'
  headline: string
  summary: string
  evidence: Evidence[]
  caller_turn_id: string | null
  created_at: number
  model_risk: Risk | null
  policy_action: Action | null
}

export interface StageTimings {
  transcribe_ms: number | null
  classify_ms: number | null
  tts_ms: number | null
  total_ms: number | null
}

export interface TurnResult {
  call_id: string
  turn_id: string
  caller_text: string
  assistant_text: string
  assessment: Assessment
  decision: PolicyDecision
  alert: Alert | null
  call_status: CallStatus
  mode: Mode
  audio_url: string | null
  audio_error: string | null
  audio_cached: boolean
  timings: StageTimings
  cached: boolean
}

export interface CallView {
  call_id: string
  status: CallStatus
  mode: Mode
  created_at: number
  scenario_label: string | null
  turns: Turn[]
  assessments: Assessment[]
  decisions: PolicyDecision[]
  alerts: Alert[]
  timings: StageTimings[]
  version: number
}

export interface Health {
  status: string
  app_mode: string
  classifier_configured: boolean
  speech_configured: boolean
  stt_configured: boolean
  classifier_model: string | null
  tts_model: string | null
  stt_model: string | null
  prompt_version: string | null
  filler_cached: boolean
  setup_needs: string[]
}

export const RISK_LABEL: Record<Risk, string> = {
  no_warning_signs: 'No warning signs',
  needs_review: 'Needs review',
  high_risk: 'High risk',
}

export const ACTION_LABEL: Record<Action, string> = {
  continue: 'Asked a follow-up question',
  take_message: 'Took a message',
  request_family_review: 'Sent to family for review',
  end_simulated_call: 'Ended the call',
}
