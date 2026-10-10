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
 * ObjectsDialog — one type's rows, in a modal.
 *
 * "Open the browser" used to be a link, which meant leaving the model you were
 * reading to go and look at its data. The two are the same subject seen twice,
 * so the rows open *over* the page instead: the panel behind keeps its
 * selection, and closing the dialog puts you back exactly where you were.
 *
 * The table is the route's own component (ObjectsBrowserBody) — one
 * implementation, two frames. A row click navigates, so the dialog closes
 * first rather than stacking a page on top of itself.
 */
import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { useI18n } from '../i18n'
import { useFocusTrap } from '../lib/focus'
import { Button } from './ui'
import { ObjectsBrowserBody } from '../pages/ObjectsBrowser'
import { IconX } from './icons'

export function ObjectsDialog({ type, onClose }: {
  /** The object type to browse; `null` closes the dialog. */
  type: string | null
  onClose: () => void
}) {
  const { t } = useI18n()
  const nav = useNavigate()
  const ref = useFocusTrap<HTMLDivElement>(Boolean(type))

  useEffect(() => {
    if (!type) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [type, onClose])

  if (!type) return null

  return createPortal(
    <div
      className="fixed inset-0 z-50 grid place-items-center p-4"
      style={{ background: 'rgba(0,0,0,.45)' }}
      onClick={onClose}
      data-testid="objects-dialog"
    >
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={`${t('data.openBrowser')}: ${type}`}
        className="ontogeny-card ontogeny-modal flex max-h-[90vh] w-full max-w-6xl flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <header
          className="flex shrink-0 items-center gap-2.5 px-5 py-3"
          style={{ borderBottom: '1px solid var(--border-subtle)' }}
        >
          <span className="min-w-0 flex-1 truncate font-mono text-[13px] font-semibold">{type}</span>
          <Button
            size="sm"
            square
            data-testid="objects-dialog-close"
            title={t('common.close')}
            aria-label={t('common.close')}
            onClick={onClose}
            icon={<IconX width={14} height={14} />}
          />
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          <ObjectsBrowserBody
            type={type}
            onNavigate={(to) => { onClose(); nav(to) }}
          />
        </div>
      </div>
    </div>,
    document.body,
  )
}
