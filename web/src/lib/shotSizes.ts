// A goal's planned size, as the server stores it: a list of shots, each one of four tokens (`core/sizes.py`). The
// interface counts them per size instead, so this turns one into the other and spells both for people.

import type { GoalCardData } from '../types'

/** The four sizes, smallest first, in the server's own spelling. */
export const SHOT_TOKENS = ['<5m', '10-15m', '45-120m', '240-480m'] as const
export type ShotToken = (typeof SHOT_TOKENS)[number]

/** What each size is called, and how long it is, for labels and tooltips. */
export const SHOT_NAMES: Record<ShotToken, { name: string; span: string }> = {
  '<5m': { name: '5-min', span: 'under 5 minutes' },
  '10-15m': { name: '15-min', span: '10–15 minutes' },
  '45-120m': { name: 'long', span: '45 minutes – 2 hours' },
  '240-480m': { name: 'deep', span: '4–8 hours' },
}

/** One count per size, in `SHOT_TOKENS` order. */
export type ShotCounts = [number, number, number, number]

export const NO_SHOTS: ShotCounts = [0, 0, 0, 0]

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

export function addCounts(a: ShotCounts, b: ShotCounts): ShotCounts {
  return [a[0] + b[0], a[1] + b[1], a[2] + b[2], a[3] + b[3]]
}

export function isEmpty(counts: ShotCounts): boolean {
  return counts.every((count) => count === 0)
}

/** "2× long + 1× 15-min", largest first, the way a plan is read aloud. */
export function shotWords(counts: ShotCounts): string {
  return counts
    .map((count, index) => (count ? `${count}× ${SHOT_NAMES[SHOT_TOKENS[index]].name}` : ''))
    .filter(Boolean)
    .reverse()
    .join(' + ')
}

/** Only Day and Week goals have a size (`core/sizes.py`'s sized verticals). */
export function isSized(vertical: string | null | undefined): boolean {
  return vertical === 'day' || vertical === 'week'
}

/** What a column still has to do: the goals not done, each counted once. A goal whose own steps carry sizes is counted
 *  by its steps, not by its own size as well, so a planned parent and its planned steps never add up twice. */
export function remainingCounts(goals: readonly GoalCardData[]): ShotCounts {
  let total = NO_SHOTS
  for (const goal of goals) {
    if (goal.done || goal.ghost) continue
    const steps = remainingCounts(goal.children ?? [])
    total = addCounts(total, isEmpty(steps) ? countsOf(goal.sizeExpected) : steps)
  }
  return total
}
