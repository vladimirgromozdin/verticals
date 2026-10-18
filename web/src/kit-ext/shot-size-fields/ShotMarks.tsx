/* A size drawn as one mark per shot, smallest to largest by shape: a dot, a short bar, a tall bar, a block. Drawn, not
   typed, so every font shows the same shapes. The words go to the tooltip and to screen readers. */
import { SHOT_TOKENS, shotWords, type ShotCounts } from '../../lib/shotSizes'
import './shotMarks.css'

interface Props {
  counts: ShotCounts
  /** Prepended to the words, e.g. "Planned" or "Left today". */
  label?: string
  className?: string
}

export function ShotMarks({ counts, label, className }: Props) {
  const words = shotWords(counts)
  if (!words) return null
  const name = label ? `${label}: ${words}` : words
  return (
    <span className={['shot-marks', className].filter(Boolean).join(' ')} title={name} aria-label={name} role="img">
      {[...counts].reverse().map((count, back) => {
        const index = SHOT_TOKENS.length - 1 - back
        return Array.from({ length: count }, (_, n) => (
          <i key={`${index}-${n}`} className={`shot-marks__mark shot-marks__mark--${index}`} />
        ))
      })}
    </span>
  )
}
