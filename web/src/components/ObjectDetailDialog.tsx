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
 * ObjectDetailDialog — one object's full detail view in a large dialog.
 *
 * Governance surfaces (audit, and anywhere a row names a target object) used
 * to navigate to /objects/:type/:id, yanking the user off the page they were
 * working on. This dialog keeps them in place: the SAME body the detail route
 * renders (fields, links, ego graph, timeline) in a near-fullscreen frame.
 * Following a linked object swaps the dialog's object in place instead of
 * navigating. Escape, the backdrop and the close button all dismiss it.
 */
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useI18n } from '../i18n'
import { useFocusTrap } from '../lib/focus'
import { useMeta } from '../api/queries'
import { IconX } from './icons'
import { ObjectDetailBody } from '../pages/ObjectDetail'

export function ObjectDetailDialog({ type, id, onClose }: {
  type: string | null
  id: string | null
  onClose: () => void
}) {
  const { t } = useI18n()
  const meta = useMeta()
  const ref = useFocusTrap<HTMLDivElement>(type != null && id != null)
  // following a linked object swaps the inspected object in place, so the
  // dialog reads as one continuous inspection session
  const [current, setCurrent] = useState<{ type: string; id: string } | null>(null)

  useEffect(() => {
    setCurrent(type != null && id != null ? { type, id } : null)
  }, [type, id])

  useEffect(() => {
    if (type == null || id == null) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [type, id, onClose])

  if (type == null || id == null || current == null) return null

  const display = meta.data?.objects[current.type]?.display

  return createPortal(
    <div
      className="fixed inset-0 z-50 grid place-items-center p-4 max-md:p-0"
      style={{ background: 'rgba(0,0,0,.5)' }}
      onClick={onClose}
      data-testid="object-detail-backdrop"
    >
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={`${current.type} / ${current.id}`}
        data-testid="object-detail-dialog"
        onClick={(e) => e.stopPropagation()}
        className="ontogeny-card ontogeny-modal flex h-[min(88vh,920px)] w-full max-w-[1180px] flex-col overflow-hidden max-md:h-full max-md:max-h-none max-md:rounded-none"
      >
        <header
          className="flex shrink-0 items-center gap-2.5 px-5 py-3"
          style={{ borderBottom: '1px solid var(--border-subtle)' }}
        >
          <span
            className="grid size-8 shrink-0 place-items-center rounded-lg font-mono text-[11px] font-bold"
            style={{ background: 'var(--brand-tint)', color: 'var(--brand-fg)' }}
          >
            {current.type.slice(0, 2).toUpperCase()}
          </span>
          <div className="min-w-0">
            <h2 className="truncate text-[13.5px] font-semibold font-mono">{current.id}</h2>
            <div className="truncate text-[11px] muted">
              {display ? `${display} · ` : ''}{current.type}
            </div>
          </div>
          <button
            type="button"
            data-testid="object-detail-close"
            aria-label={t('common.close')}
            title={`${t('common.close')} · Esc`}
            onClick={onClose}
            className="ml-auto grid size-7 shrink-0 place-items-center rounded-lg transition-colors hover:bg-[var(--surface-hover)]"
            style={{ color: 'var(--text-muted)' }}
          >
            <IconX width={15} height={15} />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto p-5">
          <ObjectDetailBody
            type={current.type}
            id={current.id}
            embedded
            onSelectObject={(nextType, nextId) => setCurrent({ type: nextType, id: nextId })}
          />
        </div>
      </div>
    </div>,
    document.body,
  )
}
