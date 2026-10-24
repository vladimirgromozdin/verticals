/* The dev panels: \ shows and hides them while dev tuning is on. */
import { DevColorPanel } from './DevColorPanel'
import { DevDeckPanel } from './DevDeckPanel'
import { DevIconPanel } from './DevIconPanel'
import { DevGoalLayoutPanel } from './DevGoalLayoutPanel'
import { DevTuningPanel } from './DevTuningPanel'
import { DevZoomPanel } from './DevZoomPanel'
import { DEV_TUNING_ENABLED } from '../lib/devTuning'
import { onMounted, onUnmounted, ref } from '../reactivity'
import { tracked } from '../tracked'
import { useSetup } from '../setup'

export const DevPanelContainer = tracked(function DevPanelContainer() {
  const s = useSetup({}, () => {
    const visible = ref(false)

    function onKeyDown(event: KeyboardEvent) {
      const target = event.target instanceof HTMLElement ? event.target : null
      const editing = target?.closest('input, textarea, select, [contenteditable="true"]') !== null
      if (editing || event.repeat || event.altKey || event.ctrlKey || event.metaKey) return
      if (event.code !== 'Backslash' && event.key !== '\\' && event.key !== 'Backslash') return
      visible.value = !visible.value
      event.preventDefault()
    }
    onMounted(() => {
      if (DEV_TUNING_ENABLED) window.addEventListener('keydown', onKeyDown)
    })
    onUnmounted(() => {
      window.removeEventListener('keydown', onKeyDown)
    })
    return { visible }
  })
  if (!DEV_TUNING_ENABLED || !s.visible.value) return null
  return (
    <>
      <DevColorPanel />
      <DevDeckPanel />
      <DevIconPanel />
      <DevGoalLayoutPanel />
      <DevTuningPanel />
      <DevZoomPanel />
    </>
  )
})
