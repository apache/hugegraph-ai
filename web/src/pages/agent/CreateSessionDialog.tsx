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
 * CreateSessionDialog — open an agent session with explicit configuration:
 *
 *  - which plugin drives the session (its frozen identity + catalogue apply);
 *  - the task;
 *  - budgets: steps / wall clock / writes-per-session — LEFT EMPTY means
 *    unlimited (sent as 0, which the broker treats as "no ceiling");
 *  - expiry: past this instant the session refuses calls and runs — left
 *    empty means it never expires.
 *
 * Creation does NOT run the session: the detail pane owns the run/re-run
 * button, so one session can be driven many times with separate traces.
 */
import { useState } from 'react'
import { createPortal } from 'react-dom'
import { useFocusTrap } from '../../lib/focus'
import { useI18n } from '../../i18n'
import { apiClient, ApiError } from '../../api/client'
import { useQueryClient } from '@tanstack/react-query'
import { Alert, Button } from '../../components/ui'
import { IconX } from '../../components/icons'
import type { AgentPluginInfo, AgentSession } from '../../api/types'

export function CreateSessionDialog({
  open, plugins, onClose, onCreated,
}: {
  open: boolean
  plugins: AgentPluginInfo[]
  onClose: () => void
  onCreated: (s: AgentSession) => void
}) {
  const { t } = useI18n()
  const qc = useQueryClient()
  const trapRef = useFocusTrap<HTMLDivElement>(open)

  const [plugin, setPlugin] = useState('')
  const [task, setTask] = useState('')
  const [steps, setSteps] = useState('')
  const [wallMs, setWallMs] = useState('')
  const [writes, setWrites] = useState('')
  const [expiresAt, setExpiresAt] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const pluginOk = plugins.some((p) => p.name === plugin)
  const canSubmit = pluginOk && !busy

  const submit = async () => {
    if (!canSubmit) return
    setBusy(true)
    setError(null)
    try {
      // empty budget field = unlimited (sent as 0); empty expiry = never
      const budget = {
        steps: Number(steps) || 0,
        wall_ms: Number(wallMs) || 0,
        writes_per_session: Number(writes) || 0,
      }
      const expires_at = expiresAt ? new Date(expiresAt).toISOString() : null
      const s = await apiClient.agentOpenSession(plugin, task.trim(), { budget, expires_at })
      qc.invalidateQueries({ queryKey: ['agent-sessions'] })
      onCreated(s)
      onClose()
      setTask(''); setSteps(''); setWallMs(''); setWrites(''); setExpiresAt('')
      setPlugin('')
    } catch (e) {
      setError(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e))
    } finally {
      setBusy(false)
    }
  }

  if (!open) return null

  return createPortal(
    <div className="fixed inset-0 z-50 grid place-items-center p-4" style={{ background: 'rgba(0,0,0,.45)' }}>
      <div
        ref={trapRef}
        role="dialog"
        aria-modal="true"
        aria-label={t('agent.create.title')}
        data-testid="create-session-dialog"
        className="ontogeny-card ontogeny-modal flex max-h-[88vh] w-full max-w-xl flex-col overflow-hidden"
      >
        <header className="flex shrink-0 items-start justify-between gap-3 px-5 pb-3 pt-4" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
          <div className="min-w-0">
            <h2 className="text-[14px] font-semibold">{t('agent.create.title')}</h2>
            <p className="mt-0.5 text-[12px] muted">{t('agent.create.subtitle')}</p>
          </div>
          <button onClick={onClose} data-testid="create-session-close" aria-label={t('common.close')}
                  className="grid size-7 shrink-0 place-items-center rounded-lg hover:bg-[var(--surface-hover)]"
                  style={{ color: 'var(--text-muted)' }}>
            <IconX width={14} height={14} />
          </button>
        </header>

        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-5 py-4">
          <label className="block">
            <span className="ontogeny-label">{t('agent.create.plugin')}</span>
            <select className="ontogeny-input" data-testid="create-plugin" value={plugin}
                    onChange={(e) => setPlugin(e.target.value)}>
              <option value="">{t('agent.create.pluginPlaceholder')}</option>
              {plugins.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
            </select>
          </label>

          <label className="block">
            <span className="ontogeny-label">{t('agent.create.task')}</span>
            <textarea className="ontogeny-input min-h-[72px]" data-testid="create-task" value={task}
                      placeholder={t('agent.create.taskPlaceholder')}
                      onChange={(e) => setTask(e.target.value)} />
            <p className="mt-1.5 text-[11px] leading-relaxed muted">{t('agent.create.taskHint')}</p>
          </label>

          <div>
            <span className="ontogeny-label">{t('agent.create.budget')}</span>
            <div className="mt-1 grid gap-3 sm:grid-cols-3">
              <label className="block">
                <span className="text-[11.5px] muted">{t('agent.create.steps')}</span>
                <input type="number" min={0} className="ontogeny-input tnum" value={steps}
                       data-testid="create-steps" placeholder={'∞ · ' + t('agent.create.unlimited')}
                       onChange={(e) => setSteps(e.target.value)} />
              </label>
              <label className="block">
                <span className="text-[11.5px] muted">{t('agent.create.wallMs')}</span>
                <input type="number" min={0} className="ontogeny-input tnum" value={wallMs}
                       data-testid="create-wall" placeholder={'∞ · ' + t('agent.create.unlimited')}
                       onChange={(e) => setWallMs(e.target.value)} />
              </label>
              <label className="block">
                <span className="text-[11.5px] muted">{t('agent.create.writesBudget')}</span>
                <input type="number" min={0} className="ontogeny-input tnum" value={writes}
                       data-testid="create-writes" placeholder={'∞ · ' + t('agent.create.unlimited')}
                       onChange={(e) => setWrites(e.target.value)} />
              </label>
            </div>
            <p className="mt-1.5 text-[11px] leading-relaxed muted">{t('agent.create.budgetHint')}</p>
          </div>

          <label className="block">
            <span className="ontogeny-label">{t('agent.create.expires')}</span>
            <input type="datetime-local" className="ontogeny-input" data-testid="create-expires"
                   value={expiresAt} onChange={(e) => setExpiresAt(e.target.value)} />
            <p className="mt-1.5 text-[11px] leading-relaxed muted">{t('agent.create.expiresHint')}</p>
          </label>

          {error ? <Alert tone="danger" testId="create-session-error">{error}</Alert> : null}
        </div>

        <footer className="flex shrink-0 items-center justify-between gap-3 px-5 py-3" style={{ borderTop: '1px solid var(--border-subtle)' }}>
          <span className="text-[11px] muted">{t('agent.create.note')}</span>
          <div className="flex gap-2">
            <Button onClick={onClose} data-testid="create-session-cancel">{t('common.cancel')}</Button>
            <Button variant="primary" disabled={!canSubmit} onClick={submit} data-testid="create-session-submit">
              {busy ? t('common.loading') : t('agent.create.submit')}
            </Button>
          </div>
        </footer>
      </div>
    </div>,
    document.body,
  )
}
