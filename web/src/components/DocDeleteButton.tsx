import { ref } from '../reactivity'
import { getDoc, type DocDetail } from '../lib/api'
import { closeWindow } from '../lib/windows'
import { loadDesk } from '../lib/docsDesk'
import { store } from '../store'
import { flushPending } from '../lib/beforeQuit'
import { bindRef } from '../bind'
import { tracked } from '../tracked'
import { useSetup } from '../setup'
import { PopoverEngine } from './PopoverEngine'
import './docDeleteButton.css'

export const DocDeleteButton = tracked(function DocDeleteButton({ id }: { id: string }) {
  const s = useSetup({ id }, (props) => {
    const trigger = ref<HTMLButtonElement | null>(null)
    const doc = ref<DocDetail | null>(null)
    const failed = ref(false)
    const busy = ref(false)
    async function load(): Promise<void> {
      doc.value = null
      failed.value = false
      try { doc.value = await getDoc(props.id) } catch { failed.value = true }
    }
    function cancel(): void { trigger.value?.click() }
    async function remove(): Promise<void> {
      if (busy.value || !doc.value) return
      busy.value = true
      try {
        await flushPending()
        if (await store.deleteCurrentDoc(props.id, true)) {
          cancel()
          closeWindow(`doc:${props.id}`)
          await loadDesk()
        }
      } finally { busy.value = false }
    }
    return { trigger, doc, failed, busy, load, cancel, remove }
  })
  const doc = s.doc.value
  const links = new Set(doc?.linked_goals.map((goal) => goal.goal_id)).size
  return (
    <PopoverEngine
      placement="bottom-end"
      fixedWidth={280}
      inline={false}
      onOpen={() => void s.load()}
      surfaceClass="doc-delete-menu"
      surfaceAttrs={{ 'data-role': 'doc-delete-confirmation' }}
      trigger={<button ref={bindRef(s.trigger)} type="button" className="doc-delete-trigger" data-role="doc-delete">Delete</button>}
    >
      <p><b>{doc?.title || doc?.path || (s.failed.value ? 'Could not read the document' : 'Reading document…')}</b></p>
      <p>{links ? `This also removes its links from ${links} ${links === 1 ? 'task' : 'tasks'}. The tasks stay.` : 'Delete this document and its version history?'}</p>
      {links ? <p>Its text and version history will be deleted.</p> : null}
      <div className="doc-delete-menu__actions">
        <button type="button" disabled={s.busy.value} onClick={s.cancel}>Cancel</button>
        <button type="button" disabled={!doc || s.busy.value} onClick={() => void s.remove()}>{s.busy.value ? 'Deleting…' : 'Delete document'}</button>
      </div>
    </PopoverEngine>
  )
})
