// The notice in the field (docs/design/board-undo.md): a change that leaves your view is said in the place where the field
// stands, and Undo is at its right end. It stays six seconds and the field comes back; Esc, or a click elsewhere, ends it
// sooner. The pointer on it holds the time, so Undo never goes from under the hand. `components/FieldNotice.tsx` draws it;
// this module is its state and its clock, and knows nothing of the board.
import { reactive } from '../reactivity'

/** The line is a few pieces so the goal's title can be cut with “…” and the words around it can't be:
 *  `text` stays whole, `quote` is a title, shown in quotation marks and the one that shrinks. */
export type Segment = { text: string } | { quote: string }

export interface NoticeAction {
  label: string
  run: () => void
}

/** One of the things a question offers: a pill that says what it would take back, and takes it. */
export interface NoticeChoice {
  label: Segment[]
  run: () => void
}

export const NOTICE_MS = 6000
/** Held under the pointer, the time left is never shorter than this when the pointer goes. */
const AFTER_HOLD_MS = 2000

export const notice = reactive({
  open: false,
  segments: [] as Segment[],
  action: null as NoticeAction | null,
  /** A question puts its candidates here, as pills, instead of one action. */
  choices: [] as NoticeChoice[],
  /** A new notice is a new thing even when the words match: the component keys its animation on this. */
  seq: 0,
})

let timer = 0
let startedAt = 0
let left = NOTICE_MS

function arm(ms: number): void {
  window.clearTimeout(timer)
  startedAt = performance.now()
  left = ms
  timer = window.setTimeout(dismiss, ms)
}

/** Says `segments` in the field, with `action` at the right end (none: the line alone). A notice already there is replaced. */
export function say(segments: Segment[], action: NoticeAction | null, choices: NoticeChoice[] = []): void {
  notice.segments = segments
  notice.action = action
  notice.choices = choices
  notice.seq += 1
  notice.open = true
  arm(NOTICE_MS)
  // Said again from its own button, under the pointer: the time stays held until the pointer goes.
  if (document.querySelector('[data-role="field-notice"]:hover')) hold()
}

export function dismiss(): void {
  window.clearTimeout(timer)
  notice.open = false
}

/** The pointer is on the notice: the time stops. */
export function hold(): void {
  if (!notice.open) return
  window.clearTimeout(timer)
  left = Math.max(0, left - (performance.now() - startedAt))
}

/** The pointer left: the rest of the time runs, but not less than two seconds. */
export function release(): void {
  if (notice.open) arm(Math.max(left, AFTER_HOLD_MS))
}

/** The question ⌘Z asks when it cannot tell whose change was meant (docs/design/agent-answer-undo.md): in the field, in the notice's
 *  shape, "Take back" and the candidates as pills. A click takes one; Esc, a click elsewhere and the six seconds drop it with nothing
 *  taken back, as for any notice. */
export function ask(choices: NoticeChoice[]): void {
  say([{ text: 'Take back' }], null, choices)
}
