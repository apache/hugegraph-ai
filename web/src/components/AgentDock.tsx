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
 * AgentDock — the assistant, as a floating button in the bottom-right corner.
 *
 * The agent used to be a page in the sidebar, which made it a destination you
 * had to leave your work to visit. It is the opposite: a conversation you want
 * *beside* whatever you are doing. So it is a dock — one round button pinned to
 * the viewport's bottom-right corner, opening the console in a wide, tall
 * dialog over the current page. Nothing navigates away; the page underneath
 * keeps its state (an open detail panel, a half-typed filter).
 *
 * The dialog is deliberately near-full-screen: the console's transcript, step
 * traces and mutation diffs need width, and a small popover would only show the
 * composer. Escape, the backdrop, the close button and ⌘J all close it.
 *
 * The console body is the same component the /agent route renders, so the two
 * frames can never drift apart.
 */
import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useI18n } from '../i18n'
import { useFocusTrap } from '../lib/focus'
import { apiClient } from '../api/client'
import { keys } from '../api/queries'
import { Badge, Skeleton } from './ui'
import { IconRefresh, IconRoute, IconX } from './icons'
import { RobotArmMark } from './RobotArmMark'

/** The console is a whole page's worth of code (transcript, step timeline,
 *  mutation diff). The dock is on every page, so loading it with the entry
 *  chunk would tax first paint for a conversation most sessions never open. */
const AgentConsoleBody = lazy(() =>
  import('../pages/AgentConsole').then((m) => ({ default: m.AgentConsoleBody })))

export function AgentDock() {
  const { t } = useI18n()
  const qc = useQueryClient()
  // direction 1: the gray toolbar row moved INTO this header -- the counts and
  // refresh live here now (same query keys as the console, one shared cache)
  const plugins = useQuery({ queryKey: ['agent-plugins'], queryFn: apiClient.agentPlugins })
  const declared = plugins.data?.plugins ?? []
  const [open, setOpen] = useState(false)
  // a page may summon the dock WITH a session to look at ("Agent 运行示例"
  // does): the console then auto-selects it in the composer
  const [presetSessionId, setPresetSessionId] = useState<number | null>(null)
  const ref = useFocusTrap<HTMLDivElement>(open)
  const buttonRef = useRef<HTMLButtonElement>(null)

  // ⌘J / Ctrl-J toggles the dock from anywhere (⌘K is the global search)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.key.toLowerCase() !== 'j') return
      e.preventDefault()
      setOpen((o) => !o)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // Any page can summon the dock (the agent console lives behind the floating
  // button, so "run this against the agent" buttons dispatch the event instead
  // of each page owning a second console).
  useEffect(() => {
    const onOpen = (e: Event) => {
      const id = (e as CustomEvent).detail?.sessionId
      setPresetSessionId(typeof id === 'number' ? id : null)
      setOpen(true)
    }
    window.addEventListener('ontogeny:agent-dock-open', onOpen)
    return () => window.removeEventListener('ontogeny:agent-dock-open', onOpen)
  }, [])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open])

  // focus goes back to the button that opened the dialog, not to <body>
  useEffect(() => {
    if (!open) buttonRef.current?.focus({ preventScroll: true })
  }, [open])

  return (
    <>
      <button
        ref={buttonRef}
        type="button"
        data-testid="agent-dock"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={t('agent.dock.open')}
        title={`${t('agent.dock.open')} · ⌘J`}
        onClick={() => setOpen(true)}
        // Frosted glass over whatever is underneath — more transparent than the
        // shared ontogeny-glass, so on the canvas it reads as a floating lens rather
        // than a pasted chip — plus a slow float and a lift on hover. The larger
        // 58px target gives the robot-arm mark room to read clearly.
        className="ontogeny-dock-glass ontogeny-float group fixed bottom-5 right-5 z-40 grid size-[58px] place-items-center rounded-full text-[var(--brand-fg)] transition-[transform,box-shadow] duration-200 hover:scale-[1.06] hover:shadow-[0_10px_28px_rgba(15,23,42,.22)] active:scale-95 max-md:bottom-4 max-md:right-4"
        style={{ animationPlayState: 'running' }}
      >
        <RobotArmMark size={32} />
      </button>

      {open ? createPortal(
        <div
          className="fixed inset-0 z-50 grid place-items-center p-4 max-md:p-0"
          style={{ background: 'rgba(0,0,0,.5)' }}
          onClick={() => setOpen(false)}
          data-testid="agent-dock-backdrop"
        >
          <div
            ref={ref}
            role="dialog"
            aria-modal="true"
            aria-label={t('agent.title')}
            data-testid="agent-dock-dialog"
            onClick={(e) => e.stopPropagation()}
            className="ontogeny-card ontogeny-modal flex h-[min(88vh,900px)] w-full max-w-[1180px] flex-col overflow-hidden max-md:h-full max-md:max-h-none max-md:rounded-none"
          >
            <header
              className="flex shrink-0 items-center gap-2.5 px-5 py-3"
              style={{ borderBottom: '1px solid var(--border-subtle)' }}
            >
              <span
                className="grid size-8 shrink-0 place-items-center rounded-lg"
                style={{ background: 'var(--brand-tint)', color: 'var(--brand-fg)' }}
              >
                <RobotArmMark size={20} />
              </span>
              <h2 className="min-w-0 truncate text-[13.5px] font-semibold">{t('agent.title')}</h2>
              <Badge tone={declared.length ? 'brand' : 'neutral'}>
                {t('agent.plugins')}: {declared.length}
              </Badge>
              <Link
                className="ontogeny-btn-ghost ontogeny-btn-sm"
                to="/agent/manage"
                onClick={() => setOpen(false)}
                data-testid="agent-dock-sessions"
              >
                <IconRoute width={13} height={13} />
                {t('agent.sessions')}
              </Link>
              <button
                type="button"
                data-testid="agent-dock-refresh"
                title={t('common.refresh')}
                aria-label={t('common.refresh')}
                onClick={() => {
                  qc.invalidateQueries({ queryKey: ['agent-plugins'] })
                  qc.invalidateQueries({ queryKey: ['agent-sessions'] })
                  qc.invalidateQueries({ queryKey: keys.agentSessions('') })
                }}
                className="grid size-7 shrink-0 place-items-center rounded-lg transition-colors hover:bg-[var(--surface-hover)]"
                style={{ color: 'var(--text-muted)' }}
              >
                <IconRefresh width={14} height={14} />
              </button>
              <span className="ml-auto hidden truncate text-[11.5px] muted lg:block">
                {t('agent.dock.subtitle')}
              </span>
              <button
                type="button"
                data-testid="agent-dock-close"
                aria-label={t('common.close')}
                title={`${t('common.close')} · Esc`}
                onClick={() => setOpen(false)}
                className="grid size-7 shrink-0 place-items-center rounded-lg transition-colors hover:bg-[var(--surface-hover)]"
                style={{ color: 'var(--text-muted)' }}
              >
                <IconX width={15} height={15} />
              </button>
            </header>

            <div className="min-h-0 flex-1">
              <Suspense fallback={<Skeleton rows={6} className="p-4" />}>
                <AgentConsoleBody flush presetSessionId={presetSessionId} />
              </Suspense>
            </div>
          </div>
        </div>,
        document.body,
      ) : null}
    </>
  )
}
