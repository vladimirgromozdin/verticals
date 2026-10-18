/* A goal's shot size: one line saying the plan and what it took, and a popover with one counter per size. The counters
   change only the popover's own draft, so nothing is redrawn but the number that moved. Enter saves it and a click away
   keeps it; Escape drops it. Enter and Escape hand the focus back to the summary, inside the goal, where a second Escape
   closes the goal as before. */
import type { KeyboardEvent } from 'react'
import { computed, onBeforeUnmount, ref, watch } from '../../reactivity'
import { fallthrough } from '../../bind'
import { tracked } from '../../tracked'
import { useSetup } from '../../setup'
import { PopoverEngine, type PopoverControl } from '../../components/PopoverEngine'
import {
  SHOT_NAMES, SHOT_TOKENS, countsOf, isEmpty, shotWords, shotsOf, type ShotCounts,
} from '../../lib/shotSizes'
import { ShotMarks } from './ShotMarks'
import './shotSizeFields.css'

interface Props {
  expected: string[] | null
  actual: string[] | null
  /** The new plan as the server's shot list, or `null` for unsized. */
  onChangeExpected?: (value: string[] | null) => void
}

const MAX_COUNT = 9
const same = (a: ShotCounts, b: ShotCounts) => a.every((count, index) => count === b[index])

export const ShotSizeFields = tracked(function ShotSizeFields(raw: Props & Record<string, unknown>) {
  const { expected, actual, onChangeExpected, ...attrs } = raw
  const s = useSetup({ expected, actual, onChangeExpected }, (props) => {
    const saved = computed(() => countsOf(props.expected))
    const draft = ref<ShotCounts>(countsOf(props.expected))
    const selected = ref(2)
    const opened = ref(false)
    const group = ref<HTMLDivElement | null>(null)
    const popover = ref<PopoverControl | null>(null)
    watch(() => props.expected, () => { if (!opened.value) draft.value = countsOf(props.expected) })

    const summary = computed(() => {
      const plan = shotWords(saved.value)
      const took = shotWords(countsOf(props.actual))
      if (!plan && !took) return 'Set shot size…'
      if (!plan) return `Actual ${took}`
      return took ? `${plan}, actual ${took}` : plan
    })

    function set(index: number, count: number): void {
      const next = [...draft.value] as ShotCounts
      next[index] = Math.max(0, Math.min(MAX_COUNT, count))
      draft.value = next
      selected.value = index
    }
    function commit(): void {
      if (!same(draft.value, saved.value)) props.onChangeExpected?.(shotsOf(draft.value))
    }
    function onOpen(): void {
      opened.value = true
      draft.value = countsOf(props.expected)
      const largest = [3, 2, 1, 0].find((index) => draft.value[index] > 0)
      selected.value = largest ?? 2
      requestAnimationFrame(() => group.value?.focus())
    }
    function onClose(): void {
      opened.value = false
      commit()
    }
    function onCancel(): void {
      draft.value = saved.value
    }
    // A goal closed with the popover still open keeps what was counted.
    onBeforeUnmount(() => { if (opened.value) commit() })

    function onKeyDown(event: KeyboardEvent<HTMLDivElement>): void {
      const at = selected.value
      const count = draft.value[at]
      const keys: Record<string, () => void> = {
        ArrowLeft: () => { selected.value = (at + SHOT_TOKENS.length - 1) % SHOT_TOKENS.length },
        ArrowRight: () => { selected.value = (at + 1) % SHOT_TOKENS.length },
        ArrowUp: () => set(at, count + 1),
        ArrowDown: () => set(at, count - 1),
        '+': () => set(at, count + 1),
        '=': () => set(at, count + 1),
        '-': () => set(at, count - 1),
        Backspace: () => { draft.value = [0, 0, 0, 0] },
        Delete: () => { draft.value = [0, 0, 0, 0] },
        Enter: () => popover.value?.close(),
      }
      const run = /^[0-9]$/.test(event.key) ? () => set(at, Number(event.key)) : keys[event.key]
      if (!run) return
      event.preventDefault()
      event.stopPropagation()
      run()
    }
    return { saved, draft, selected, group, popover, summary, set, onOpen, onClose, onCancel, onKeyDown }
  })

  const draft = s.draft.value
  return (
    <section {...fallthrough({ className: 'shot-size-fields', 'data-role': 'size-fields' }, attrs)}>
      <PopoverEngine
        placement="top-start"
        fixedWidth={300}
        surfaceClass="shot-size-fields__popover"
        onOpen={s.onOpen}
        onClose={s.onClose}
        onCancel={s.onCancel}
        expose={s.popover}
        trigger={({ open }) => (
          <button
            type="button"
            className="shot-size-fields__summary"
            data-role="size-summary"
            aria-label="Edit shot size"
            aria-expanded={String(open) as 'true' | 'false'}
          >
            {!isEmpty(s.saved.value) ? <ShotMarks className="shot-size-fields__marks" counts={s.saved.value} /> : null}
            <span>{s.summary.value}</span>
          </button>
        )}
      >
        <div
          ref={(node) => { s.group.value = node }}
          className="shot-size-fields__counters"
          data-role="size-expected"
          role="group"
          aria-label="Planned shots"
          tabIndex={0}
          onKeyDown={s.onKeyDown}
        >
          {SHOT_TOKENS.map((token, index) => (
            <div
              key={token}
              className="shot-size-fields__counter"
              data-role="size-counter"
              data-size={token}
              data-selected={s.selected.value === index || undefined}
            >
              <span className="shot-size-fields__mark" aria-hidden="true">
                <ShotMarks counts={[index === 0 ? 1 : 0, index === 1 ? 1 : 0, index === 2 ? 1 : 0, index === 3 ? 1 : 0]} />
              </span>
              <span className="shot-size-fields__name" title={SHOT_NAMES[token].span}>{SHOT_NAMES[token].name}</span>
              <span className="shot-size-fields__stepper">
                <button
                  type="button"
                  tabIndex={-1}
                  aria-label={`One less ${SHOT_NAMES[token].name} shot`}
                  disabled={draft[index] === 0}
                  onClick={() => s.set(index, draft[index] - 1)}
                >−</button>
                <output className="shot-size-fields__count" data-role="size-count" aria-live="polite">{draft[index]}</output>
                <button
                  type="button"
                  tabIndex={-1}
                  aria-label={`One more ${SHOT_NAMES[token].name} shot`}
                  disabled={draft[index] === MAX_COUNT}
                  onClick={() => s.set(index, draft[index] + 1)}
                >+</button>
              </span>
            </div>
          ))}
        </div>
        <p className="shot-size-fields__hint">
          <kbd>←</kbd><kbd>→</kbd> size · <kbd>↑</kbd><kbd>↓</kbd> or a digit, count · <kbd>⌫</kbd> clear · <kbd>Enter</kbd> save · <kbd>Esc</kbd> cancel
        </p>
        {actual?.length ? (
          <p className="shot-size-fields__actual" data-role="size-actual">
            <span>Actual</span>
            <strong>{shotWords(countsOf(actual))}</strong>
          </p>
        ) : null}
      </PopoverEngine>
    </section>
  )
})
