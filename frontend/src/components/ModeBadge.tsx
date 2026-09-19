import type { Health, Mode } from '../types'

const MODE_TEXT: Record<Mode, { label: string; detail: string }> = {
  live_api: {
    label: 'Live API',
    detail: 'Nemotron classification and ElevenLabs speech. Fixed assistant phrases are cached audio.',
  },
  text_fallback: {
    label: 'Text fallback',
    detail: 'Real Nemotron classification; the caller turn was typed, not spoken.',
  },
  fixture_replay: {
    label: 'Fixture replay',
    detail: 'Simulated, pre-written outcome. Not model inference. Excluded from results.',
  },
}

export function ModeBadge({ mode, health }: { mode: Mode; health: Health | null }) {
  const { label, detail } = MODE_TEXT[mode]
  return (
    <div className={`mode-badge mode-${mode}`} title={detail}>
      <span className="mode-label">{label}</span>
      {health?.classifier_model && mode !== 'fixture_replay' && (
        <span className="mode-detail">
          {health.classifier_model.replace(/^nvidia\//, '')}
          {health.prompt_version ? ` · prompt ${health.prompt_version}` : ''}
        </span>
      )}
      <span className="mode-detail">{detail}</span>
    </div>
  )
}
