import { toast } from '../kit'
import { ApiError, deleteGoal, type BoardResponse, type GoalDetail } from './api'
import { findGoal } from './boardIndex'
import { makeStep } from './boardHistory'
import { deletedStep, takeOut } from './goalSteps'
import { messageForError } from './scheduleFeedback'

/** The tag that marks a goal as part of the sample data a first run shows. */
export const SAMPLE_TAG = 'sample'

/** Deleting a goal from the board. Lifted out of `store.ts` when flow 4 took that module past the 750-line cap again;
 *  same factory seam as `createSearchActions`: the store's one reactive state, no second container. */
export function createGoalDelete(
  state: { board: BoardResponse | null; openGoalId: string | null; openPath: string[]; goalDetail: GoalDetail | null },
  reloadBoard: () => Promise<void>,
  closeGoal: () => void,
) {
  /** `DELETE /api/goals/{id}`, no confirmation dialog — the same shape `removeSample` already ships and the same reason
   *  (§10-D12; a confirm dialog is also a `role="dialog"` node every "this happened without a modal" assertion in the
   *  suite would then see).
   *
   *  A goal with subgoals goes with all of them, at once. The delete is a step of the board's history now, and the notice
   *  that follows it has Undo (`lib/boardHistory.ts`), which the server's trash makes whole again; that replaces the toast
   *  that asked "Delete all" after a 409. The board's own count of what lies under the goal says which write to send. When
   *  it did not carry them all (a subgoal in another period), the server's 409 sends the second write.
   *
   *  A goal deleted while it is open (in a window over the Inbox, or open on the board) closes with it, so the notice and
   *  its Undo are what is left in view. It closes once the click is over: a menu the click closes is drawn closed first,
   *  since what is in a window that starts to leave draws no more (`tracked.ts`) and would stay on screen while it fades. */
  function removeGoal(id: string): Promise<void> {
    const open = state.goalDetail?.id === id ? state.goalDetail : null
    const title = findGoal(state.board, id)?.title ?? open?.title ?? 'a goal'
    const subgoals = state.board?.progress[id]?.total ?? open?.children.length ?? 0
    if (state.openGoalId === id || state.openPath.includes(id)) {
      window.setTimeout(() => {
        if (state.openGoalId === id || state.openPath.includes(id)) closeGoal()
      }, 0)
    }
    return makeStep(async () => {
      for (const cascade of subgoals > 0 ? [true] : [false, true]) {
        const placement = takeOut(state.board, id, cascade)
        try {
          await deleteGoal(id, cascade)
          placement.reconcile()
          return deletedStep(id, title, subgoals)
        } catch (err) {
          placement.rollback()
          if (cascade || !(err instanceof ApiError) || err.status !== 409) {
            toast(messageForError(err))
            return null
          }
        }
      }
      return null
    })
  }

  /** S-62: one gesture, no confirmation (pinned, §10-D12 — a confirm dialog would fail the modal-record assertion outright),
   *  removing only the sample chain. Finds the sample root by content (`tags @> {sample}` and no parent) rather than
   *  hardcoding `SAMPLE01`, then issues one `DELETE ?cascade=true` — `core.goals.delete`'s own body is a single `DELETE ...
   *  WHERE id = $1 OR path LIKE $2` inside one `conn.transaction()` (verified in `verticals/core/goals.py`), which is what
   *  makes this "ordered leaf-first inside one transaction" without this file doing any ordering itself. No-op if no sample
   *  root is on the board (the button should not be visible then — see `hasSampleData` — but a stale click racing a second
   *  removal must not throw). */
  async function removeSample(): Promise<void> {
    if (!state.board) return
    const root = state.board.columns
      .flatMap((c) => c.goals)
      .find((g) => g.parent_id === null && g.tags.includes(SAMPLE_TAG))
    if (!root) return
    try {
      await deleteGoal(root.id, true)
      await reloadBoard()
    } catch (err) {
      toast(messageForError(err))
    }
  }

  return { removeGoal, removeSample }
}
