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
 * DataOverviewDialog — a wide modal frame for a full-width table view.
 *
 * The "all object types and their rows" view is a *view of a page*, not a page
 * of its own: it used to be `/data`, a route that duplicated the model already
 * living on /knowledge and /action. This is the frame it opens in now — wide,
 * scrollable, dismissed with Escape or the backdrop.
 */
import { useEffect, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../i18n'
import { useFocusTrap } from '../lib/focus'
import { Button } from './ui'
import { IconX } from './icons'

export function DataOverviewDialog({ open, onClose, title, children }: {
  open: boolean
  onClose: () => void
  title?: string
  children: ReactNode
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

  return createPortal(
    <div
      className="fixed inset-0 z-50 grid place-items-center p-4"
      style={{ background: 'rgba(0,0,0,.45)' }}
      onClick={onClose}
      data-testid="data-overview-dialog"
    >
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={title ?? t('knowledge.overview')}
        className="ontogeny-card ontogeny-modal flex max-h-[90vh] w-full max-w-6xl flex-col overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <header
          className="flex shrink-0 items-center gap-2.5 px-5 py-3"
          style={{ borderBottom: '1px solid var(--border-subtle)' }}
        >
          <h2 className="min-w-0 flex-1 truncate text-[13.5px] font-semibold">
            {title ?? t('knowledge.overview')}
          </h2>
          <Button
            size="sm"
            square
            data-testid="data-overview-close"
            title={t('common.close')}
            aria-label={t('common.close')}
            onClick={onClose}
            icon={<IconX width={14} height={14} />}
          />
        </header>
        <div className="min-h-0 flex-1 overflow-y-auto p-5">{children}</div>
      </div>
    </div>,
    document.body,
  )
}
