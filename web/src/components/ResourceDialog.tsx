/*
 * Copyright 2026 Apache HugeGraph Authors
 * 
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 * 
 *     http://www.apache.org/licenses/LICENSE-2.0
 * 
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */
/**
 * ResourceDialog — one resource's full form, in a modal.
 *
 * The ontology workbench's right panel is 360px wide: enough for a detail
 * summary and the list of what hangs off a type, not enough for a property
 * table with four columns, a parameter list and a row of effect assignments.
 * So editing opens here, wide, over the canvas — the panel-first, modal-when-it-
 * does-not-fit rule the page follows.
 *
 * The dialog owns no state of its own beyond "is this open": every keystroke
 * goes straight into the shared draft through `update`, which is what makes the
 * page's single save button the only thing that reaches the server.
 */
import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../i18n'
import { useFocusTrap } from '../lib/focus'
import { Button } from './ui'
import { IconX } from './icons'
import {
  ActionEditor, FunctionEditor, LinkTypeEditor, ObjectTypeEditor, PolicySetEditor,
} from '../pages/ontology/editors'
import type { ResourceKind } from '../api/resources'
import type { OntologyResource } from '../api/types'

export function ResourceDialog({ open, kind, resource, objectNames, policyNames, onClose, onRename, update }: {
  open: boolean
  kind: ResourceKind
  resource: OntologyResource
  objectNames: string[]
  policyNames: string[]
  onClose: () => void
  onRename: (to: string) => void
  update: (next: (res: OntologyResource) => OntologyResource) => void
}) {
  const { t } = useI18n()
  const ref = useFocusTrap<HTMLDivElement>(open)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  const props = { resource, update, rename: onRename, objectNames, policyNames }

  return createPortal(
    <div
      className="fixed inset-0 z-50 grid place-items-center p-4"
      style={{ background: 'rgba(0,0,0,.45)' }}
      onClick={onClose}
      data-testid="resource-dialog"
    >
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={t(`ontology.edit.${kind}`)}
        className="ontogeny-card ontogeny-modal flex max-h-[88vh] w-full max-w-3xl flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <header
          className="flex shrink-0 items-center justify-between gap-3 px-5 py-3.5"
          style={{ borderBottom: '1px solid var(--border-subtle)' }}
        >
          <div className="min-w-0">
            <h2 className="text-[14px] font-semibold">{t(`ontology.edit.${kind}`)}</h2>
            <div className="mt-0.5 truncate font-mono text-[12px] muted">{resource.metadata.name}</div>
          </div>
          <Button size="sm" onClick={onClose} data-testid="resource-dialog-close" icon={<IconX width={13} height={13} />}>
            {t('common.close')}
          </Button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {kind === 'ObjectType' ? <ObjectTypeEditor {...props} /> : null}
          {kind === 'LinkType' ? <LinkTypeEditor {...props} /> : null}
          {kind === 'Action' ? <ActionEditor {...props} /> : null}
          {kind === 'Function' ? <FunctionEditor {...props} /> : null}
          {kind === 'PolicySet' ? <PolicySetEditor {...props} /> : null}
        </div>

        <footer
          className="flex shrink-0 items-center gap-3 px-5 py-3"
          style={{ borderTop: '1px solid var(--border-subtle)' }}
        >
          <span className="min-w-0 flex-1 truncate text-[11.5px] muted">{t('ontology.dialogHint')}</span>
          <Button variant="primary" size="sm" onClick={onClose} data-testid="resource-dialog-done">
            {t('settings.done')}
          </Button>
        </footer>
      </div>
    </div>,
    document.body,
  )
}
