// A goal's planned size, as the server stores it: a list of shots, each one of four tokens (`core/sizes.py`). The
// interface counts them per size instead, so this turns one into the other and spells both for people.

/** The four sizes, smallest first, in the server's own spelling. */
export const SHOT_TOKENS = ['<5m', '10-15m', '45-120m', '240-480m'] as const
export type ShotToken = (typeof SHOT_TOKENS)[number]

/** What each size is called, and how long it is, for labels and tooltips. The name is the token's own span, so a
 *  reader never has to learn what a word like "deep" stands for, and a total never disagrees with the names. */
export const SHOT_NAMES: Record<ShotToken, { name: string; span: string }> = {
  '<5m': { name: '<5 min', span: 'under 5 minutes' },
  '10-15m': { name: '10–15 min', span: '10–15 minutes' },
  '45-120m': { name: '45–120 min', span: '45 minutes – 2 hours' },
  '240-480m': { name: '4–8 h', span: '4–8 hours' },
}

/** How long each size takes, in minutes, shortest and longest, in `SHOT_TOKENS` order. */
const SHOT_MINUTES: readonly (readonly [number, number])[] = [[0, 5], [10, 15], [45, 120], [240, 480]]

/** One count per size, in `SHOT_TOKENS` order. */
export type ShotCounts = [number, number, number, number]

export function countsOf(shots: readonly string[] | null | undefined): ShotCounts {
  const counts: ShotCounts = [0, 0, 0, 0]
  for (const shot of shots ?? []) {
    const index = SHOT_TOKENS.indexOf(shot as ShotToken)
    if (index >= 0) counts[index] += 1
  }
  return counts
}

/** The list the server takes, or `null` for unsized: an empty list is refused, never a second "none". */
export function shotsOf(counts: ShotCounts): string[] | null {
  const shots = counts.flatMap((count, index) => Array<string>(count).fill(SHOT_TOKENS[index]))
  return shots.length ? shots : null
}

/** "2× 45–120 min + 1× 10–15 min", largest first, the way a plan is read aloud. */
export function shotWords(counts: ShotCounts): string {
  return counts
    .map((count, index) => (count ? `${count}× ${SHOT_NAMES[SHOT_TOKENS[index]].name}` : ''))
    .filter(Boolean)
    .reverse()
    .join(' + ')
}

function minuteWords(minutes: number): string {
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  if (!hours) return `${rest} min`
  return rest ? `${hours} h ${rest} min` : `${hours} h`
}

/** How long a plan takes, "1 h 5 min – 2 h 30 min", or `''` for none. */
export function timeWords(counts: ShotCounts): string {
  const low = counts.reduce((sum, count, index) => sum + count * SHOT_MINUTES[index][0], 0)
  const high = counts.reduce((sum, count, index) => sum + count * SHOT_MINUTES[index][1], 0)
  if (!high) return ''
  if (!low) return `up to ${minuteWords(high)}`
  return `${minuteWords(low)} – ${minuteWords(high)}`
}
