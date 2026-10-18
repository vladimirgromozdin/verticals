// Shared prop shapes for the board. Loosely mirrors the eventual core/board.py response
// (ARCHITECTURE.md §2, §3) closely enough that wiring a real fetch in later (WP-22/23) shouldn't
// reshape these components — but WP-12 has no backend, and nothing here is generated from or
// coupled to the DB schema.

import type { RepeatRule } from './lib/api'

export interface GoalCardData {
  id: string
  parentId?: string | null
  title: string
  done?: boolean
  /** One of the six canon hexes (ARCHITECTURE.md §3 color_is_canon), or unset/null for no colour. */
  color?: string | null
  /** Root value colour used only by the card completion affordance. */
  /** Polymorphic per docs/UI_MEASURED.md §6: parent's title at top level, own vertical badge when
   *  nested under an expanded parent. WP-12 renders a flat column, so this is always the
   *  top-level sense here — the nested sense is a later WP's concern. */
  contextLabel?: string
  subgoalCount?: number
  /** `goals.vertical` off the wire (`day`..`life`, or `null` for a Maybe row or a pure subgoal). */
  vertical?: string | null
  repeat?: RepeatRule | null
  tags?: string[]
  projectTags?: string[]
  /** The planned shots off the wire (`size_expected`); only Day and Week goals have them. */
  sizeExpected?: string[] | null
  foil?: boolean
  ghost?: boolean
  ghostUntil?: string | null
  /** Stored anchor and its display label; never the viewing column's period. */
  anchorDate?: string | null
  /** `BoardResponse.progress[id]` — done/total over this card's *descendants*, computed
   *  server-side in the same board query (`core/board.py`). Absent for a leaf, which is exactly
   *  AC-033's "leaves report no progress"; present and rendered as `done/total` otherwise. */
  progress?: { done: number; total: number }
  /** Direct same-vertical children rendered inline. Lower-vertical children render in their own
   *  columns; vertical-null children are ideas and stay off the board (R7). */
  children?: GoalCardData[]
}

/** One way to write a column's name: the big name, and the small kind line above it. */
export interface NameForm {
  name: string
  kind: string
}

export interface BoardColumnData {
  /** vertical_scale enum value (ARCHITECTURE.md §3): day | week | month | quarter | year | decade | life. */
  vertical: string
  /** The column's name, its period, in full: "October", "5–11 Oct", "Today" (docs/design/column-names.md). */
  title: string
  /** The kind, small above the name: "Month"; the year follows it, short, when the period is outside the current year. */
  subLabel?: string
  /** The same name in shorter forms, longest first: the column shows the first form that fits its room, so a name is never
   *  cut with "…" (`lib/fitName.ts`). */
  shorter?: NameForm[]
  /** The accessible name: the full name with full years, whichever form is on screen. */
  label?: string
  active?: boolean
  addPlaceholder?: string
  goals: GoalCardData[]
  /** `BoardColumn.period_key` off the wire, carried straight through (`store.ts::toColumnData`).
   *  `null` only for the Maybe bucket. Column-level drop (`docs/PLANNER_DND.md` §2 — a drop
   *  assigns this column's vertical AND anchors the date to this column's own period start) needs
   *  this to name *which* period of the column's scale to anchor into, the same field
   *  `lib/columnNames.ts::columnNames` already reads to build the header's own name — one field,
   *  read twice, never recomputed independently. */
  periodKey?: string | null
  /** The board is paged away from today and this column's own period no longer holds it, so its sign is the single bar
   *  that brings the board back (docs/design/column-bars.md). False for a column that holds today, and for Life. */
  away?: boolean
}

export interface BoardData {
  columns: BoardColumnData[]
}
