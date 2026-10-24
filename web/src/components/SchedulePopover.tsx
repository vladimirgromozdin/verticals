/* The schedule picker: all seven verticals in one surface on PopoverEngine, one
   click to schedule. Controlled: every label is a prop; it only says what was picked (`onSelect`) and which stepper was
   paged (`onNavigate`). Every assignable target is a `.dropdown__item`, so the engine's arrow keys walk them; the ‹/›
   steppers are not. The `trigger` slot (`{ open, toggle }`) falls back to a "Schedule" button. The grid itself is
   `ScheduleGrid`, which the goal's menu also shows as its Date step (MoveStep.tsx), so a date is picked one way
   everywhere. */
import type { ReactNode } from 'react'
import { periodLabel, type VerticalScale, type WeekRow } from '../lib/periods'
import { cx, fallthrough } from '../bind'
import { tracked } from '../tracked'
import { AppIcon } from './AppIcon'
import { drawsSomething, PopoverEngine, type PopoverTriggerSlot } from './PopoverEngine'
import './schedulePopover.css'

type Stepped = 'decade' | 'year' | 'month'
type Direction = 'prev' | 'next'

export interface ScheduleGridProps {
  life: string
  decade: string
  year: string
  /** Exactly four period keys, Q1..Q4, for the year currently shown. */
  quarters: string[]
  month: string
  /** ISO-week rows, each carrying its own seven day cells (Monday first). */
  weeks: WeekRow[]
  today: string
  tomorrow: string
  thisWeek: string
  onSelect?: (scale: VerticalScale, periodKey: string) => void
  onNavigate?: (scale: Stepped, direction: Direction) => void
}

interface Props extends ScheduleGridProps {
  onOpen?: () => void
  trigger?: ReactNode | ((slot: PopoverTriggerSlot) => ReactNode)
}

const WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

export const SchedulePopover = tracked(function SchedulePopover(raw: Props & Record<string, unknown>) {
  const { onOpen, trigger, ...rest } = raw
  const { life, decade, year, quarters, month, weeks, today, tomorrow, thisWeek, onSelect, onNavigate, ...attrs } = rest
  const grid = { life, decade, year, quarters, month, weeks, today, tomorrow, thisWeek, onSelect, onNavigate }

  function triggerSlot(slot: PopoverTriggerSlot): ReactNode {
    const given = typeof trigger === 'function' ? trigger(slot) : trigger
    if (drawsSomething(given)) return given
    return (
      <button className="button t-subtitle dropdown__trigger" type="button" data-cap="schedule" aria-haspopup="menu"
        aria-expanded={String(slot.open) as 'true' | 'false'}>
        Schedule
      </button>
    )
  }

  return (
    <div {...fallthrough({ className: 'schedule-popover-anchor' }, attrs)}>
      <PopoverEngine className="schedule-popover" onOpen={() => onOpen?.()} trigger={triggerSlot}>
        <ScheduleGrid {...grid} />
      </PopoverEngine>
    </div>
  )
})

/** The rows of the picker: Life, the 3 years, the year and its quarters, the month, its weeks and days, and the shortcuts.
 *  Selection stays a consumer action: a surface that holds the grid closes on the menuitem click itself. */
export const ScheduleGrid = tracked(function ScheduleGrid(props: ScheduleGridProps) {
  const { decade, year, quarters, month, weeks, today, tomorrow, thisWeek, onSelect, onNavigate } = props
  const pick = (scale: VerticalScale, periodKey: string) => onSelect?.(scale, periodKey)
  const step = (scale: Stepped, direction: Direction) => onNavigate?.(scale, direction)
  const nav = (scale: Stepped, direction: Direction, label: string) => (
    <button className="schedule-popover__nav" type="button" aria-label={label} onClick={() => step(scale, direction)}>
      <AppIcon name={direction === 'prev' ? 'chevron-left' : 'chevron-right'} size={14} />
    </button>
  )

  return (
    <>
      <div className="schedule-popover__row" data-scale="life">
        <button className="dropdown__item" role="menuitem" type="button" data-period-key="life" onClick={() => pick('life', 'life')}>
          Life
        </button>
      </div>

      <div className="schedule-popover__row schedule-popover__stepper" data-scale="decade">
        {nav('decade', 'prev', 'Previous 3-year window')}
        <button className="dropdown__item schedule-popover__stepper-label" role="menuitem" type="button" data-period-key={decade}
          onClick={() => pick('decade', decade)}>
          {`3 years ${periodLabel('decade', decade)}`}
        </button>
        {nav('decade', 'next', 'Next 3-year window')}
      </div>

      <div className="schedule-popover__row schedule-popover__stepper" data-scale="year">
        {nav('year', 'prev', 'Previous year')}
        <button className="dropdown__item schedule-popover__stepper-label" role="menuitem" type="button" data-period-key={year}
          onClick={() => pick('year', year)}>
          {periodLabel('year', year)}
        </button>
        {quarters.map((q) => (
          <button key={q} className="dropdown__item schedule-popover__quarter" role="menuitem" type="button" data-scale="quarter"
            data-period-key={q} onClick={() => pick('quarter', q)}>
            {periodLabel('quarter', q)}
          </button>
        ))}
        {nav('year', 'next', 'Next year')}
      </div>

      <div className="schedule-popover__row schedule-popover__stepper" data-scale="month">
        {nav('month', 'prev', 'Previous month')}
        <button className="dropdown__item schedule-popover__stepper-label" role="menuitem" type="button" data-period-key={month}
          onClick={() => pick('month', month)}>
          {periodLabel('month', month)}
        </button>
        {nav('month', 'next', 'Next month')}
      </div>

      <div className="schedule-popover__weekday">
        <div className="schedule-popover__weekday-col schedule-popover__weekday-col--weeks">
          <p className="schedule-popover__weekday-caption" aria-hidden="true">Weeks</p>
          <div data-scale="week" className="schedule-popover__weeks">
            {weeks.map((week) => (
              <button key={week.periodKey} className="dropdown__item schedule-popover__week" role="menuitem" type="button"
                data-period-key={week.periodKey} onClick={() => pick('week', week.periodKey)}>
                {periodLabel('week', week.periodKey)}
              </button>
            ))}
          </div>
        </div>
        <div className="schedule-popover__weekday-col schedule-popover__weekday-col--days">
          <div className="schedule-popover__weekday-caption schedule-popover__weekday-dow" aria-hidden="true">
            {WEEKDAY_LABELS.map((label) => <span key={label}>{label}</span>)}
          </div>
          <div data-scale="day" className="schedule-popover__days">
            {weeks.flatMap((week) => week.days.map((cell, i) => cell === null ? (
              <span key={`${week.periodKey}-${i}`} className="schedule-popover__day schedule-popover__day--blank" aria-hidden="true"></span>
            ) : (
              <button key={`${week.periodKey}-${i}`} className={cx('dropdown__item schedule-popover__day', { 'schedule-popover__day--today': cell.isToday })}
                role="menuitem" type="button" data-period-key={cell.periodKey} aria-current={cell.isToday ? 'date' : undefined}
                onClick={() => pick('day', cell.periodKey)}>
                {periodLabel('day', cell.periodKey)}
              </button>
            )))}
          </div>
        </div>
      </div>

      <div className="schedule-popover__row schedule-popover__footer" data-role="schedule-footer">
        <button className="dropdown__item" role="menuitem" type="button" data-period-key={today} onClick={() => pick('day', today)}>
          Today
        </button>
        <button className="dropdown__item" role="menuitem" type="button" data-period-key={tomorrow} onClick={() => pick('day', tomorrow)}>
          Tomorrow
        </button>
        <button className="dropdown__item" role="menuitem" type="button" data-period-key={thisWeek} onClick={() => pick('week', thisWeek)}>
          This week
        </button>
      </div>
    </>
  )
})
