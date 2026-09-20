import { useEffect, useState } from 'react'
import { getBaseline } from '../api'
import { ACTION_LABEL, type Action, type BaselineComparison, type TurnResult } from '../types'

// Colour follows the action's severity, but the action is always spelled out in
// words too, the same as everywhere else in this UI.
const SEVERITY: Record<Action, 'calm' | 'review' | 'urgent'> = {
  continue: 'calm',
  take_message: 'calm',
  request_family_review: 'review',
  end_simulated_call: 'urgent',
}

/** What the frozen keyword baseline would have done with the same transcript.
 *
 * Fetched after the turn is already answered and rendered, so it is never on the
 * critical path, and it is labelled as a comparison because CallKind does not
 * read it, act on it, or weigh it against its own decision.
 */
export function BaselineCompare({ result }: { result: TurnResult }) {
  const [data, setData] = useState<BaselineComparison | null>(null)

  useEffect(() => {
    let live = true
    getBaseline(result.call_id)
      .then((d) => { if (live) setData(d) })
      .catch(() => undefined)   // the comparison is optional; never break the call
    return () => { live = false }
  }, [result.call_id, result.turn_id])

  if (!data) return null

  const row = data.turns.find((t) => t.turn_id === result.turn_id)
  // No row and the baseline already ended the call means this turn is one the
  // baseline would never have heard.
  if (!row && data.ended_at_turn_id === null) return null

  const ours = result.decision.action
  const differs = row ? row.action !== ours : true

  return (
    <div className={`baseline${differs ? ' baseline-differs' : ''}`}>
      <p className="baseline-caption">
        Beside the frozen keyword baseline <strong>{data.baseline_version}</strong>, run on the
        same words. A comparison only: CallKind does not act on it.
      </p>

      <div className="baseline-grid">
        <div>
          <span className="baseline-who">CallKind</span>
          <span className={`baseline-verdict v-${SEVERITY[ours]}`}>{ACTION_LABEL[ours]}</span>
        </div>
        <div>
          <span className="baseline-who">Keyword matching</span>
          {row ? (
            <span className={`baseline-verdict v-${SEVERITY[row.action]}`}>
              {ACTION_LABEL[row.action]}
            </span>
          ) : (
            <span className="baseline-verdict v-urgent">Had already hung up</span>
          )}
          {row && row.matched.length > 0 && (
            <span className="baseline-matched">on "{row.matched[0]}"</span>
          )}
        </div>
      </div>

      <p className="baseline-note">
        {differs ? 'The two disagree on this turn.' : 'Both reach the same action here.'}
      </p>
    </div>
  )
}
