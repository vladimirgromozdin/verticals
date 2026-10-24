/* The tags above the field: the agent's (its slot, `agent`), the docs and the Inbox.
   A view's tag pressed again goes back to the board. */
import type { MouseEvent, ReactNode } from 'react'
import { AppIcon } from './AppIcon'
import { store } from '../store'
import { cx, fallthrough } from '../bind'
import { tracked } from '../tracked'
import './circleTags.css'

const VIEWS = [
  { key: 'docs', name: 'Documents', label: 'Docs', icon: 'file' },
  { key: 'inbox', name: 'Inbox', label: 'Inbox', icon: 'inbox' },
] as const

function open(view: 'docs' | 'inbox'): void {
  store.closeGoal()
  store.setView(store.state.activeView === view ? 'verticals' : view)
}

/* A press on a tag keeps the caret in the field, so an open field stays open while its tag works. */
function keepCaret(event: MouseEvent): void {
  event.preventDefault()
}

interface Props {
  shown: boolean
  agent?: ReactNode
}

export const CircleTags = tracked(function CircleTags({ shown, agent, ...attrs }: Props & Record<string, unknown>) {
  return (
    <div {...fallthrough({ className: cx('circle-tags', { 'is-shown': shown }), 'data-role': 'circle-tags' }, attrs)} onMouseDown={keepCaret}>
      {agent}
      {VIEWS.map((view) => (
        <button
          key={view.key}
          type="button"
          className={cx('circle-tag', { 'is-current': store.state.activeView === view.key })}
          data-tag={view.key}
          aria-label={view.name}
          aria-pressed={String(store.state.activeView === view.key) as 'true' | 'false'}
          onClick={() => open(view.key)}
        >
          <AppIcon name={view.icon} size={16} stroke={2.2} />
          <span className="circle-tag__name">{view.label}</span>
        </button>
      ))}
    </div>
  )
})
