/* Documents: the desk of stacks (DocsDesk). A document opened by its address or a link,
   and its history, take the whole view; the desk comes back when they close.

   DocDetail is keyed by the current document's id on purpose: a fresh instance per document, not one following a
   changing prop, is what keeps its debounced body-save safe across a switch (see DocDetail's header). */
import { AppIcon } from './AppIcon'
import { DocDetail } from './DocDetail'
import { SourceStrip } from './SourceStrip'
import { isSourcePath } from '../lib/sources'
import { DocsDesk } from './DocsDesk'
import { DocsHistory } from './DocsHistory'
import { store } from '../store'
import { fallthrough } from '../bind'
import { tracked } from '../tracked'
import './docsView.css'

export const DocsView = tracked(function DocsView(attrs: Record<string, unknown>) {
  const docs = store.state.docs
  return (
    <div {...fallthrough({ className: 'docs-view', 'data-cap': 'docs' }, attrs)}>
      {docs.historyOpen || docs.current || docs.currentLoading ? (
        <section className="docs-view__panel">
          <button type="button" className="docs-view__back" data-role="docs-back" onClick={() => store.closeDoc()}>
            <AppIcon name="chevron-left" size={16} />Documents
          </button>
          {docs.historyOpen ? (
            <DocsHistory />
          ) : docs.current ? (
            <>
              {isSourcePath(docs.current.path) ? <SourceStrip key={docs.current.id} id={docs.current.id} /> : null}
              <DocDetail key={docs.currentId ?? undefined} doc={docs.current} />
            </>
          ) : (
            <p className="t-caption t-muted docs-view__loading">Loading…</p>
          )}
        </section>
      ) : (
        <DocsDesk />
      )}
    </div>
  )
})
