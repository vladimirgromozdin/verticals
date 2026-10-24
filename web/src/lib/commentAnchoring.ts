/** The component-facing half of anchored comments (docs/COMMENTS_SPEC.md WP-B) — `commentAnchor.ts`'s
 *  pure DOM functions, wired to `store` and to one component's own body ref/editing flag. Shared
 *  between `GoalDetail.tsx` and `DocDetail.tsx` (both render markdown into the same
 *  contenteditable-toggle node and both need the identical selection affordance, highlight repaint,
 *  and highlight-click-through) rather than duplicated per component — the two call sites differ
 *  only in target type/id and which ref is their body. Imports `store` directly, the same way the
 *  two components themselves already do (`import { store } from '../store'`); this is a composable
 *  consumed BY components, not a slice `store.ts` itself spreads in, so there is no circularity the
 *  way there would be if `lib/comments.ts` imported this back. */
import { computed, onBeforeUnmount, onMounted, ref, watch, type Ref } from '../reactivity'
import { store } from '../store'
import {
  applyAnchorHighlights, captureSelectionAnchor, clearHighlights, type AnchoredThread, type AnchorContext,
} from './commentAnchor'
import type { CommentTargetType } from './comments'

/** The words being commented, marked while the comment is written (`store.state.comments.pendingAnchor`); a thread's id
 *  is never this. */
export const DRAFT_ID = 'draft'

export interface CommentAnchoringOptions {
  bodyEl: Ref<HTMLElement | null>
  editing: Ref<boolean>
  targetType: CommentTargetType
  /** A document's comments stand on their words and open over them (docs/design/doc-comments-inline.md): a selection
   *  opens the field to write in under it, a press on marked words opens their comment there, and a resolved comment's
   *  words are plain text again. A goal's comments open the docked panel. */
  inline?: boolean
  /** A getter, not a plain id — `GoalDetail.tsx` keeps ONE instance across goal switches (the
   *  inline-detail host is reused per D226/D248), so the target id changes under this composable's
   *  feet; a getter reads the current one on every call instead of closing over a stale id. */
  targetId: () => string | null
}

export function useCommentAnchoring(opts: CommentAnchoringOptions) {
  const pendingSelection = ref<AnchorContext | null>(null)
  const selectionButtonPos = ref<{ x: number; y: number }>({ x: 0, y: 0 })
  /** Counts the marks painted, so what stands on the words (the comment's card) knows when they were drawn again. */
  const paints = ref(0)

  /** This target's own anchored threads, in the `{id, quote, prefix, suffix}` shape
   *  `applyAnchorHighlights` wants. Empty (not stale data from a previous target) whenever
   *  `store.state.comments` is not currently loaded for `(targetType, targetId)` — the same guard
   *  `lib/comments.ts::unresolvedCommentCount` applies for the identical reason. */
  const anchoredThreads = computed(() => {
    const c = store.state.comments
    if (c.targetType !== opts.targetType || c.targetId !== opts.targetId()) return []
    const marks: AnchoredThread[] = c.threads
      .filter((t) => t.anchor !== null)
      .map((t) => ({
        id: t.id, quote: t.anchor!.quote, prefix: t.anchor!.prefix, suffix: t.anchor!.suffix,
        ...(opts.inline ? { resolved: t.resolved_at !== null } : {}),
      }))
    // The words a comment is being written on stay marked while its field is open.
    if (opts.inline && c.pendingAnchor) marks.push({ id: DRAFT_ID, ...c.pendingAnchor })
    return marks
  })

  /** Called after every markdown (re)render, read-mode only — `bodyMarkdown.ts::renderBodyElement`
   *  fully replaces the body's children each time (`root.replaceChildren`), so there is never stale
   *  mark state to fight; `applyAnchorHighlights` itself still clears defensively (its own doc
   *  comment) for the case this runs twice with no render between (a threads-only update, below). */
  function paintHighlights(): void {
    const el = opts.bodyEl.value
    if (!el || opts.editing.value) return
    applyAnchorHighlights(el, anchoredThreads.value)
    paints.value += 1
  }

  // A threads change with NO body re-render in between (a reply landed, a resolve toggled) still
  // needs a repaint — `paintHighlights` is idempotent and cheap (one DOM walk), so just re-running
  // it here rather than threading a "did threads change" flag through every render call site.
  watch(anchoredThreads, () => paintHighlights())

  /** Strips this component's own highlight marks before contenteditable turns on — a mark left in
   *  place is harmless to `serializeBodyElement` (unknown tags fall through to their text content,
   *  `bodyMarkdown.ts::serializeInlineNode`'s own default case), but leaving it would highlight text
   *  the user is actively editing, which reads as a stray artifact, not a feature. Call from each
   *  component's own "start editing" function. */
  function clearForEdit(): void {
    const el = opts.bodyEl.value
    if (el) clearHighlights(el)
  }

  /** A fresh mousedown always retires whatever "Comment" affordance the LAST selection raised —
   *  starting a new selection (or just clicking to place a caret) means the old one is no longer
   *  what the reader is looking at. */
  function onBodyMouseDown(): void {
    pendingSelection.value = null
  }

  /** Documents allow comments while editing too, with the button below the selection's right edge. */
  function onBodyMouseUp(): void {
    if (opts.editing.value && !opts.inline) return
    const el = opts.bodyEl.value
    const selection = window.getSelection()
    if (!el || !selection) {
      pendingSelection.value = null
      return
    }
    const anchor = captureSelectionAnchor(el, selection)
    if (!anchor) {
      pendingSelection.value = null
      return
    }
    const rect = selection.getRangeAt(0).getBoundingClientRect()
    pendingSelection.value = anchor
    selectionButtonPos.value = opts.inline
      ? { x: rect.right, y: rect.bottom }
      : { x: rect.left + rect.width / 2, y: rect.top }
  }

  function onSelectionChange(): void {
    if (document.activeElement?.closest('[data-cap="comment-selection"]')) return
    onBodyMouseUp()
  }

  function onPointerDown(event: PointerEvent): void {
    const target = event.target
    if (target instanceof Element && target.closest('[data-cap="comment-selection"]')) return
    pendingSelection.value = null
  }

  onMounted(() => {
    if (!opts.inline) return
    document.addEventListener('selectionchange', onSelectionChange)
    document.addEventListener('pointerdown', onPointerDown, true)
    document.addEventListener('scroll', onBodyMouseDown, true)
    window.addEventListener('resize', onBodyMouseDown)
  })
  onBeforeUnmount(() => {
    if (!opts.inline) return
    document.removeEventListener('selectionchange', onSelectionChange)
    document.removeEventListener('pointerdown', onPointerDown, true)
    document.removeEventListener('scroll', onBodyMouseDown, true)
    window.removeEventListener('resize', onBodyMouseDown)
  })

  /** The floating "Comment" button's own click — stages the anchor, opens the panel armed with it
   *  (COMMENTS_SPEC.md WP-B: "creating captures quote/prefix/suffix from the selection"), and
   *  releases the browser's own text selection so it does not linger, visually competing with the
   *  panel that is about to open. */
  function commitSelectionToComment(): void {
    const id = opts.targetId()
    const anchor = pendingSelection.value
    if (!id || !anchor) return
    window.getSelection()?.removeAllRanges()
    pendingSelection.value = null
    if (opts.inline) {
      store.openComposer(id, anchor)
      return
    }
    // `openCommentsPanel` BEFORE `stageAnchor`, not after: `openCommentsPanel` -> `loadCommentsFor`
    // resets `state.comments.pendingAnchor` to null the moment it (re)establishes the current
    // target (`lib/comments.ts::loadCommentsFor`'s own "switching target" branch) — which fires
    // here whenever this is the first real commit against this target, not only on an actual
    // target SWITCH, because the goal/doc-open auto-fetch that seeds the badge count
    // (`GoalDetail.tsx`'s own `watch` on `goal.value?.id`) can still be in flight when a fast
    // reader selects text and clicks Comment before it settles. Staging the anchor AFTER the
    // open call, rather than before, means it always lands on top of whatever that reset did,
    // synchronously, in the same tick `openCommentsPanel` returns in (its own `loadCommentsFor`
    // call is fire-and-forget past the first `await`, but the reset itself is the SYNCHRONOUS
    // half of that function, already complete by the time this line runs).
    store.openCommentsPanel(opts.targetType, id)
    store.stageAnchor(anchor)
  }

  /** Highlight click-through — called from each component's own existing body click handler,
   *  BEFORE that handler's own read/edit-mode dispatch, so a highlight always opens its thread
   *  rather than also starting a body edit. Returns whether it handled the click, so the caller
   *  knows to stop (`GoalDetail.tsx`'s own link-click carve-out is the precedent for this shape). */
  function onBodyClick(event: MouseEvent): boolean {
    if (opts.inline && pendingSelection.value) return true
    const target = event.target as HTMLElement | null
    const mark = target?.closest?.('.comment-highlight')
    if (!mark) return false
    const threadId = mark.getAttribute('data-thread-id')
    const id = opts.targetId()
    if (!threadId || !id) return false
    if (opts.inline) {
      // A resolved comment's words are plain text: a press on them is the press it would be anywhere else in the text.
      if (mark.hasAttribute('data-resolved')) return false
      event.preventDefault()
      if (threadId !== DRAFT_ID) store.toggleCard(threadId)
      return true
    }
    event.preventDefault()
    store.openCommentsPanel(opts.targetType, id, threadId)
    return true
  }

  return {
    pendingSelection,
    selectionButtonPos,
    anchoredThreads,
    paints,
    paintHighlights,
    clearForEdit,
    onBodyMouseDown,
    onBodyMouseUp,
    commitSelectionToComment,
    onBodyClick,
  }
}
