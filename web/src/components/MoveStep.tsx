/* A step of the goal's menu (web/src/components/MoveStep.tsx, docs/design-handoff S5.P5): it takes the menu's place, with
   ‹ and its name at the top, and is never a window of its own. Date shows the same grid as the date under an open goal's
   title (ScheduleGrid in SchedulePopover.tsx), so a date is picked one way everywhere; Into a goal finds the goal to sit
   under and makes this one its last step. */
import { Fragment, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent } from 'react'
import { computed, nextTick, onMounted, ref, watch } from '../reactivity'
import { AppIcon } from './AppIcon'
import { ScheduleGrid } from './SchedulePopover'
import { store } from '../store'
import { findGoals, type GoalCard } from '../lib/api'
import { findGoal } from '../lib/boardIndex'
import { VERTICAL_SCALES, verticalRank, type VerticalScale } from '../lib/periods'
import { bindRef, fallthrough, model } from '../bind'
import { tracked } from '../tracked'
import { useSetup } from '../setup'
import './moveStep.css'

export type MoveStepName = 'date' | 'under'

interface Props {
  id: string
  step: MoveStepName
  onGo?: (step: MoveStepName | null) => void
  onDone?: () => void
}

const TITLES: Record<MoveStepName, string> = { date: 'Move to a date', under: 'Into a goal' }

export const MoveStep = tracked(function MoveStep(raw: Props & Record<string, unknown>) {
  const { id, step, onGo, onDone, ...attrs } = raw
  const s = useSetup({ id, step, onGo, onDone }, (props) => {
    const root = ref<HTMLElement | null>(null)
    const goal = computed(() => findGoal(store.state.board, props.id) ?? null)

    function back(): void {
      props.onGo?.(null)
    }
    /* The grid opens on today, as it does under an open goal's title. */
    watch(() => props.step, (step) => { if (step === 'date') store.resetScheduleView() }, { immediate: true })
    function schedule(scale: VerticalScale, periodKey: string): void {
      void store.scheduleGoalQuick(props.id, scale, periodKey)
      props.onDone?.()
    }

    /* Under: the goal it sits under now first, then the goals of each vertical from the nearest; typing narrows it to the
       names that match, each with its vertical (S5.P5.010-.012, .027). */
    const query = ref('')
    const found = ref<GoalCard[] | null>(null)
    let findVersion = 0
    watch(query, async (q) => {
      const version = ++findVersion
      // The search starts at three letters; before that the board's own goals are narrowed here.
      if (q.trim().length < 3) { found.value = null; return }
      const result = await findGoals(q.trim()).catch(() => null)
      if (version === findVersion) found.value = result ? result.goals : []
    })
    function subtree(): Set<string> {
      const out = new Set<string>([props.id])
      const board = store.state.board
      const walk = (id: string) => {
        for (const kid of board?.children[id] ?? []) { out.add(kid.id); walk(kid.id) }
      }
      walk(props.id)
      return out
    }
    const candidates = computed(() => {
      const own = goal.value
      const skip = subtree()
      const pool = found.value ?? (store.state.board?.columns.flatMap((c) => c.goals) ?? [])
      const seen = new Set<string>()
      const q = query.value.trim().toLowerCase()
      const list = pool.filter((g) => {
        if (skip.has(g.id) || g.id === own?.parent_id || seen.has(g.id) || g.done_at) return false
        if (q && !found.value && !g.title.toLowerCase().includes(q)) return false
        seen.add(g.id)
        return true
      })
      const rank = (g: GoalCard) => (g.vertical ? VERTICAL_SCALES.indexOf(g.vertical as VerticalScale) : 99)
      const from = own?.vertical ? verticalRank(own.vertical as VerticalScale) : 0
      return found.value ? list : [...list].sort((a, b) => Math.abs(rank(a) - from) - Math.abs(rank(b) - from))
    })
    const nowUnder = computed(() => {
      const parentId = goal.value?.parent_id
      return parentId ? findGoal(store.state.board, parentId) ?? null : null
    })
    function parts(title: string): Array<{ text: string; match: boolean }> {
      const q = query.value.trim()
      if (!q) return [{ text: title, match: false }]
      const at = title.toLowerCase().indexOf(q.toLowerCase())
      if (at < 0) return [{ text: title, match: false }]
      return [
        { text: title.slice(0, at), match: false },
        { text: title.slice(at, at + q.length), match: true },
        { text: title.slice(at + q.length), match: false },
      ].filter((p) => p.text)
    }
    function under(target: GoalCard): void {
      // Under a smaller vertical's goal it takes that goal's period first (S5.P6.002); otherwise it keeps its own dates.
      const own = goal.value?.vertical
      const smaller = !!own && !!target.vertical && verticalRank(own as VerticalScale) > verticalRank(target.vertical as VerticalScale)
      void (smaller ? store.combineInto(props.id, target.id) : store.reparentQuick(props.id, target.id))
      props.onDone?.()
    }
    function out(): void {
      void store.reparentQuick(props.id, null)
      props.onDone?.()
    }
    function verticalName(h: string | null): string {
      return h ? h === 'decade' ? '3 years' : h[0]!.toUpperCase() + h.slice(1) : 'Inbox'
    }
    function onSearchKey(event: ReactKeyboardEvent): void {
      if (event.key === 'Enter' && candidates.value[0]) {
        event.preventDefault()
        under(candidates.value[0])
      }
    }
    function onKey(event: ReactKeyboardEvent): void {
      const inField = (event.target as HTMLElement).matches('input')
      if (event.key === 'ArrowLeft' && !inField) {
        event.preventDefault()
        back()
      }
    }

    /* Each step takes the focus, so ↑ ↓ ↵ and ← work at once (S5.P5.021). */
    async function focusFirst(): Promise<void> {
      await nextTick()
      root.value?.querySelector<HTMLElement>('input, [role="menuitem"]:not([data-back])')?.focus()
    }
    onMounted(focusFirst)
    watch(() => props.step, focusFirst)

    return {
      root, back, schedule, query, candidates, nowUnder, parts, under, out, verticalName,
      onSearchKey, onKey,
    }
  })

  const stop = (fn: () => void) => (event: ReactMouseEvent) => {
    event.stopPropagation()
    fn()
  }
  const nowUnder = s.nowUnder.value
  const query = s.query.value

  return (
    <div {...fallthrough({
      ref: bindRef(s.root), className: 'move-step', 'data-step': step, 'data-role': 'move-step', onKeyDown: s.onKey,
    }, attrs)}>
      <div className="move-step__head">
        <button type="button" className="move-step__back" data-back="" role="menuitem" aria-label={`Back from ${TITLES[step]}`} onClick={stop(s.back)}>
          <AppIcon name="chevron-left" size={14} /><span className="move-step__title">{TITLES[step]}</span>
        </button>
      </div>

      {step === 'date' ? (
        <ScheduleGrid {...store.scheduleGrid.value.props} onSelect={s.schedule} onNavigate={store.navigateSchedule} />
      ) : step === 'under' ? (
        <>
          <label className="move-step__search">
            <AppIcon name="search" size={16} />
            <input {...model(s.query)} type="text" placeholder="Find a goal" aria-label="Find the goal to move under" data-role="move-under-search"
              onKeyDown={s.onSearchKey} />
            {query ? (
              <button type="button" className="move-step__clear" aria-label="Clear" onClick={stop(() => { s.query.value = '' })}><AppIcon name="x-circle" size={16} /></button>
            ) : null}
          </label>
          {nowUnder && !query ? (
            <>
              <p className="move-step__label">Now under</p>
              <div className="move-step__goal move-step__goal--now" data-color={nowUnder.color ?? undefined}>
                <span className="move-step__square" style={{ background: nowUnder.color ?? '#d9d9dc' }}></span>
                <span className="move-step__goal-title">{nowUnder.title}</span>
                <span className="move-step__vertical">{s.verticalName(nowUnder.vertical)}</span>
              </div>
              <button type="button" role="menuitem" className="move-step__goal move-step__goal--out" data-parent-id="" onClick={stop(s.out)}>
                <span></span><span className="move-step__goal-title">Not under any goal</span><span></span>
              </button>
              <hr />
            </>
          ) : null}
          <div className="move-step__list">
            {s.candidates.value.slice(0, 60).map((target) => (
              <button key={target.id} type="button" role="menuitem" className="move-step__goal" data-parent-id={target.id}
                onClick={stop(() => s.under(target))}>
                <span className="move-step__square" style={{ background: target.color ?? '#d9d9dc' }}></span>
                <span className="move-step__goal-title">
                  {s.parts(target.title).map((part, i) => (part.match ? <strong key={i}>{part.text}</strong> : <Fragment key={i}>{part.text}</Fragment>))}
                </span>
                <span className="move-step__vertical">{s.verticalName(target.vertical)}</span>
              </button>
            ))}
          </div>
        </>
      ) : null}
    </div>
  )
})
