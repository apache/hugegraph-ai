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
 * NodeInfoDrawer: right-side slide-in panel showing a clicked graph node's
 * details — click to inspect, never a page jump.
 *
 * Content is assembled by the parent (it knows the domain): a colour dot +
 * title + subtitle, key/value rows, and an optional footer link for "open the
 * full page". Closes via X or Escape; clicking another node just updates it.
 */
import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useI18n } from '../i18n'
import { useFocusTrap } from '../lib/focus'
import { KeyValue } from './ui'
import { IconX } from './icons'

interface DrawerItem {
  key: string
  value: React.ReactNode
}

export function NodeInfoDrawer({
  open, onClose, title, subtitle, dotColor, items, link, testId = 'node-info-drawer',
}: {
  open: boolean
  onClose: () => void
  title: string
  subtitle?: string
  dotColor?: string
  items: DrawerItem[]
  link?: { to: string; label: string }
  testId?: string
}) {
  const { t } = useI18n()
  const ref = useFocusTrap<HTMLElement>(open)

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  return (
    <aside
      ref={ref}
      data-testid={testId}
      className="ontogeny-drawer fixed inset-y-0 right-0 z-40 flex w-[380px] max-w-[85vw] flex-col"
      style={{
        background: 'var(--surface-card)',
        borderLeft: '1px solid var(--border-subtle)',
        boxShadow: 'var(--shadow-drawer)',
      }}
      role="dialog"
      aria-modal="true"
      aria-label={title}
    >
      <header
        className="flex shrink-0 items-start justify-between gap-3 px-5 pb-3 pt-4"
        style={{ borderBottom: '1px solid var(--border-subtle)' }}
      >
        <div className="flex min-w-0 items-center gap-2.5">
          {dotColor ? (
            <span className="mt-0.5 size-3 shrink-0 rounded-full" style={{ background: dotColor }} />
          ) : null}
          <div className="min-w-0">
            <div className="truncate font-mono text-[14px] font-semibold" title={title}>{title}</div>
            {subtitle ? <div className="mt-0.5 truncate text-[11.5px] muted">{subtitle}</div> : null}
          </div>
        </div>
        <button
          onClick={onClose}
          data-testid="drawer-close"
          aria-label={t('drawer.close')}
          className="grid size-7 shrink-0 place-items-center rounded-lg hover:bg-[var(--surface-hover)]"
          style={{ color: 'var(--text-muted)' }}
        >
          <IconX width={14} height={14} />
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
        {/* the shared key/value list, so a field row is the same shape here as
            on the object page (this panel had its own 128px label column with
            the mono font forced onto every value) */}
        <KeyValue
          labelWidth="w-32"
          items={items.map((item) => ({ key: item.key, value: item.value ?? '—', mono: true }))}
        />
      </div>

      {link ? (
        <div
          className="shrink-0 px-5 py-3"
          style={{ borderTop: '1px solid var(--border-subtle)' }}
        >
          <Link to={link.to} className="ontogeny-btn-ghost w-full justify-center" onClick={onClose}>
            {link.label}
          </Link>
        </div>
      ) : null}
    </aside>
  )
}
