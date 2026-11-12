/*
Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements.  See the NOTICE file
distributed with this work for additional information
regarding copyright ownership.  The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License.  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.
*/
/** Edit a task's extraction subgraph and Skill, then optionally re-extract.
 *
 * A confirmed task is immutable; saving opens the next revision. That is
 * deliberately visible in the copy, not hidden behind a generic "save". */
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ApiError, apiClient } from '../../api/client'
import { documentSchemaQuery, documentSkillsQuery } from '../../api/queries'
import type { DocumentScopeObject, DocumentSkillInput, DocumentTaskDetail } from '../../api/types'
import { useI18n } from '../../i18n'
import { Button } from '../../components/ui'
import { ErrorBanner } from '../../components/ErrorBanner'
import { IconX } from '../../components/icons'

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <div>
        <div className="text-[11px] font-semibold uppercase tracking-[0.07em]" style={{ color: 'var(--text-secondary)' }}>{title}</div>
        {hint ? <p className="mt-0.5 text-[11.5px] muted">{hint}</p> : null}
      </div>
      {children}
    </section>
  )
}

export function TaskConfigDialog({
  store,
  task,
  onClose,
  onSaved,
}: {
  store: string
  task: DocumentTaskDetail
  onClose: () => void
  onSaved: (task: DocumentTaskDetail) => Promise<void>
}) {
  const { t } = useI18n()
  const schemaQ = useQuery(documentSchemaQuery(store))
  const skillsQ = useQuery(documentSkillsQuery())
  const [selected, setSelected] = useState<Record<string, Set<string>>>({})
  const [links, setLinks] = useState<Set<string>>(new Set())
  const [skillId, setSkillId] = useState('graph-extract')
  const [addendum, setAddendum] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    if (ready || !schemaQ.data) return
    setReady(true)
    const hasScope = task.scope != null
    const next: Record<string, Set<string>> = {}
    for (const obj of schemaQ.data.objects) {
      const configured = task.scope?.objects?.[obj.name]
      next[obj.name] = new Set(configured ?? (hasScope ? [] : obj.properties.map((p) => p.name)))
    }
    setSelected(next)
    setLinks(new Set(hasScope ? (task.scope?.links ?? []) : schemaQ.data.links.map((l) => l.name)))
    const skill = task.skill ?? {}
    setSkillId(String(skill.id ?? skill.name ?? 'graph-extract'))
    setAddendum(String(skill.addendum ?? ''))
  }, [ready, schemaQ.data, task])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = previous
    }
  }, [onClose])

  const toggleProp = (object: string, prop: string) => {
    setSelected((prev) => {
      const next = { ...prev }
      const set = new Set(next[object] ?? [])
      if (set.has(prop)) set.delete(prop)
      else set.add(prop)
      next[object] = set
      return next
    })
  }
  const toggleObject = (obj: DocumentScopeObject) => {
    setError(null)
    setSelected((prev) => {
      const next = { ...prev }
      next[obj.name] = new Set(next[obj.name]?.size ? [] : obj.properties.map((p) => p.name))
      return next
    })
  }
  const toggleLink = (name: string) => {
    setLinks((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  const selectedObjectCount = Object.values(selected).filter((props) => props.size > 0).length
  const validation = selectedObjectCount === 0 ? t('documents.task.needObject') : null

  const reconfigure = useMutation({
    mutationFn: async () => {
      const objects: Record<string, string[]> = {}
      for (const [name, props] of Object.entries(selected)) if (props.size) objects[name] = Array.from(props)
      const skill: DocumentSkillInput = { id: skillId, addendum, examples: [], language: 'en' }
      return apiClient.reconfigureDocumentTask(task.id, { objects, links: Array.from(links) }, skill)
    },
  })

  const save = async (run: boolean) => {
    if (validation) { setError(validation); return }
    setError(null)
    try {
      const updated = await reconfigure.mutateAsync()
      if (run) {
        const detail = await apiClient.runDocumentTask(updated.id)
        await onSaved(detail)
      } else {
        await onSaved(updated)
      }
    } catch (e) {
      setError(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e))
    }
  }

  const busy = reconfigure.isPending
  const dialog = (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-3 sm:p-4"
      style={{ background: 'rgba(15, 23, 42, 0.38)' }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="documents-task-config-title"
      data-testid="documents-task-config-dialog"
      onMouseDown={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        className="flex w-full max-w-[780px] flex-col overflow-hidden rounded-2xl"
        style={{
          height: 'min(760px, calc(100dvh - 32px))',
          maxHeight: 'calc(100dvh - 32px)',
          background: 'var(--surface-card)',
          border: '1px solid var(--border-subtle)',
          boxShadow: '0 24px 80px rgba(15, 23, 42, 0.28)',
        }}
      >
        <header className="flex shrink-0 items-start gap-3 border-b px-5 py-4 sm:px-6" style={{ borderColor: 'var(--border-subtle)' }}>
          <div className="min-w-0">
            <div className="text-[10px] font-semibold uppercase tracking-[0.12em]" style={{ color: 'var(--color-brand-500)' }}>{t('documents.title')}</div>
            <h2 id="documents-task-config-title" className="mt-0.5 text-[18px] font-semibold" style={{ color: 'var(--text-primary)' }}>{t('documents.task.config')}</h2>
            <p className="mt-1 text-[12px] leading-relaxed muted">{t('documents.task.configHint')}</p>
            <p className="mt-1 text-[11px] muted">{task.name} · rev {task.revision}</p>
          </div>
          <button type="button" className="ml-auto grid size-8 shrink-0 place-items-center rounded-lg" style={{ color: 'var(--text-muted)' }} onClick={onClose} aria-label={t('documents.task.cancel')}>
            <IconX width={16} height={16} />
          </button>
        </header>

        <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-5 py-4 sm:px-6">
          {error ? <ErrorBanner error={error} /> : null}
          {schemaQ.isLoading ? <p className="text-[11.5px] muted">{t('common.loading')}</p> : null}
          <Section title={`${t('documents.task.scope')} · ${t('documents.task.objects')}`} hint={t('documents.task.scopeHint')}>
            <div className="grid gap-2.5">
              {(schemaQ.data?.objects ?? []).map((obj) => {
                const active = (selected[obj.name]?.size ?? 0) > 0
                return (
                  <div key={obj.name} className="rounded-xl border p-3" style={{ borderColor: active ? 'var(--color-brand-500)' : 'var(--border-subtle)', background: active ? 'var(--brand-tint)' : 'var(--surface-card)' }}>
                    <label className="flex items-start gap-2.5">
                      <input type="checkbox" className="mt-0.5" checked={active} onChange={() => toggleObject(obj)} aria-label={obj.display} />
                      <span className="min-w-0 flex-1">
                        <span className="flex flex-wrap items-center gap-x-2 gap-y-0.5">
                          <span className="text-[12.5px] font-semibold" style={{ color: 'var(--text-primary)' }}>{obj.display}</span>
                          <span className="font-mono text-[10px] muted">{obj.name}</span>
                          {obj.identity.length ? <span className="rounded px-1.5 py-0.5 text-[9.5px]" style={{ background: 'var(--surface-sunken)', color: 'var(--text-muted)' }}>{t('documents.task.identity')}: {obj.identity.join(' + ')}</span> : null}
                        </span>
                      </span>
                    </label>
                    <div className="mt-2.5 flex flex-wrap gap-1.5">
                      {obj.properties.map((prop) => {
                        const on = selected[obj.name]?.has(prop.name) ?? false
                        return (
                          <label key={prop.name} className="flex cursor-pointer items-center gap-1 rounded-md border px-2 py-1 text-[10.5px]" style={{ borderColor: on ? 'var(--border-strong)' : 'var(--border-subtle)', background: on ? 'var(--surface-card)' : 'transparent', color: on ? 'var(--text-primary)' : 'var(--text-muted)', opacity: active ? 1 : 0.55 }}>
                            <input type="checkbox" className="size-3" checked={on} onChange={() => toggleProp(obj.name, prop.name)} data-testid={`documents-task-config-prop-${obj.name}-${prop.name}`} />
                            <span className="font-mono">{prop.name}</span>
                            {prop.required ? <span style={{ color: 'var(--tone-warning-fg)' }} title={t('documents.task.required')}>*</span> : null}
                          </label>
                        )
                      })}
                    </div>
                  </div>
                )
              })}
            </div>
          </Section>

          <Section title={t('documents.task.links')} hint={t('documents.task.linksHint')}>
            <div className="flex flex-col gap-1.5">
              {(schemaQ.data?.links ?? []).map((link) => (
                <label key={link.name} className="flex items-center gap-2 rounded-lg border px-3 py-2" style={{ borderColor: links.has(link.name) ? 'var(--border-strong)' : 'var(--border-subtle)' }}>
                  <input type="checkbox" checked={links.has(link.name)} onChange={() => toggleLink(link.name)} />
                  <span className="text-[12px] font-medium" style={{ color: 'var(--text-primary)' }}>{link.display}</span>
                  <span className="font-mono text-[10px] muted">{link.name}</span>
                  <span className="ml-auto text-[10px] muted">{link.source} → {link.target}</span>
                </label>
              ))}
              {!(schemaQ.data?.links ?? []).length ? <p className="text-[11px] muted">{t('documents.task.noLinks')}</p> : null}
            </div>
          </Section>

          <Section title={t('documents.task.skill')}>
            <select className="ontogeny-input" value={skillId} onChange={(e) => setSkillId(e.target.value)} data-testid="documents-task-config-skill">
              {(skillsQ.data?.skills ?? [{ id: 'graph-extract', display: '通用图抽取', name: 'graph-extract', version: 1, body: '', examples: [] }]).map((s) => (
                <option key={s.id} value={s.id}>{s.display || s.name} · v{s.version}</option>
              ))}
            </select>
            <label className="flex flex-col gap-1">
              <span className="text-[11px] muted">{t('documents.task.skillAddendum')}</span>
              <textarea className="ontogeny-input min-h-[84px] resize-y" value={addendum} onChange={(e) => setAddendum(e.target.value)} placeholder={t('documents.task.skillPlaceholder')} data-testid="documents-task-config-addendum" />
            </label>
          </Section>
        </div>

        <footer className="flex shrink-0 flex-wrap items-center gap-2 border-t px-5 py-3 sm:px-6" style={{ borderColor: 'var(--border-subtle)', background: 'var(--surface-sunken)' }}>
          <span className="text-[11px]" style={{ color: validation ? 'var(--tone-warning-fg)' : 'var(--text-muted)' }}>{validation ?? t('documents.task.footerHint')}</span>
          <div className="ml-auto flex items-center gap-2">
            <Button size="sm" variant="subtle" onClick={onClose} disabled={busy}>{t('documents.task.cancel')}</Button>
            <Button size="sm" variant="ghost" onClick={() => void save(false)} disabled={busy} data-testid="documents-task-config-save">
              {t('documents.task.saveConfig')}
            </Button>
            <Button size="sm" onClick={() => void save(true)} disabled={busy} data-testid="documents-task-config-save-run">
              {t('documents.task.saveAndRun')}
            </Button>
          </div>
        </footer>
      </div>
    </div>
  )
  return createPortal(dialog, document.body)
}
