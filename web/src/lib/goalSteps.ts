// The steps of the board's history that make a goal go or come (docs/design/board-undo.md): a delete and a creation are
// the same two writes read the other way round. Both rest on the server's trash (`core/trash.py`): a goal that goes waits
// there with its subgoals, so the write that brings it back puts the same ids back, and the one that sends it away again
// leaves it there for the next time.
import { toast } from '../kit'
import { ApiError, deleteGoal, restoreGoal, type BoardResponse } from './api'
import { historyPorts, type Step } from './boardHistory'
import { removePlacement } from './boardPlacement'
import type { Outcome } from './boardRestore'
import { addedWords, deleteWords, putBackWords, removedWords } from './historyWords'
import { messageForError } from './scheduleFeedback'

/** What a refused or lost write does to a step: told once, and a step the server will never take is let go. */
function failed(err: unknown, gone: string): Outcome {
  if (err instanceof ApiError && (err.status === 404 || err.status === 422)) {
    toast(gone)
    return 'drop'
  }
  toast(messageForError(err))
  return 'retry'
}

/** A list that shows goals the board doesn't (the Inbox) takes one out at once when it goes, and hands back what puts it
 *  back if the server refuses. `lib/inbox.ts` binds its own. */
export type Lift = (id: string) => (() => void) | null
let lift: Lift = () => null
export function bindLift(own: Lift): void {
  lift = own
}

/** Takes the goal out of the board and of the lists off it, at once: `reconcile` once the server took the delete,
 *  `rollback` if it refused. */
export function takeOut(board: BoardResponse | null, id: string, cascade: boolean): { reconcile(): void; rollback(): void } {
  const placement = removePlacement(board, id, cascade)
  const putBack = lift(id)
  return {
    reconcile: () => placement?.reconcile(),
    rollback: () => {
      placement?.rollback()
      putBack?.()
    },
  }
}

/** Sends the goal and what is under it to the trash: the rows close up at once, and come back if the server refuses. */
export async function sendAway(id: string, title: string): Promise<Outcome> {
  const placement = takeOut(historyPorts().board(), id, true)
  try {
    await deleteGoal(id, true)
    placement.reconcile()
    return 'done'
  } catch (err) {
    placement.rollback()
    return failed(err, `“${title}” is gone already.`)
  }
}

/** Brings the goal back from the trash with its subgoals under the same ids, and reads the board again. `count` is how many
 *  goals came back, the goal included. */
async function bringBack(id: string, title: string): Promise<{ outcome: Outcome; count: number }> {
  try {
    const back = await restoreGoal(id)
    await historyPorts().reloadBoard()
    return { outcome: 'done', count: back.restored }
  } catch (err) {
    return { outcome: failed(err, `“${title}” can’t be put back any more.`), count: 0 }
  }
}

/** A goal deleted with `known` subgoals under it (what the board counted). Undo brings them back; redo deletes them again. */
export function deletedStep(id: string, title: string, known: number): Step {
  let subgoals = known
  return {
    id,
    // The rows close up when the goal goes, and open to take it when it comes back.
    glides: () => true,
    words: (direction) => (direction === 'undo' ? putBackWords(title) : deleteWords(title, subgoals)),
    async undo(): Promise<Outcome> {
      const { outcome, count } = await bringBack(id, title)
      if (outcome === 'done') subgoals = Math.max(0, count - 1)
      return outcome
    },
    redo: () => sendAway(id, title),
  }
}

/** A goal made by the person (an inline add, a step added in an open goal, words written in the Inbox). Undo sends it to the
 *  trash; redo brings it back under the same id. */
export function createdStep(id: string, title: string): Step {
  return {
    id,
    glides: () => true,
    words: (direction) => (direction === 'undo' ? removedWords(title) : addedWords(title)),
    undo: () => sendAway(id, title),
    redo: async () => (await bringBack(id, title)).outcome,
  }
}
