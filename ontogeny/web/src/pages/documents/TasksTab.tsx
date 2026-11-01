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
/** Document intelligence tasks: scope+skill at creation, staged runs, human
 *  review, explicit confirmation. Nothing here writes object rows until
 *  "Confirm into graph". */
import { useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, apiClient } from '../../api/client'
import {
  documentSchemaQuery,
  documentSkillsQuery,
  documentTaskQuery,
  documentTasksQuery,
  documentsQuery,
} from '../../api/queries'
import type {
  DocumentScope,
  DocumentScopeObject,
  DocumentSkillInput,
  DocumentTaskDetail,
  DocumentTaskSummary,
  ExtractedGraph,
} from '../../api/types'
import { useI18n } from '../../i18n'
import { Alert, Badge, Button, EmptyState, Panel, Split, toneForStatus } from '../../components/ui'
import { ErrorBanner } from '../../components/ErrorBanner'
import { IconCheck, IconPencil, IconPlay, IconUpload, IconX } from '../../components/icons'
import { ExtractionGraph } from '../../components/ExtractionGraph'
import { TaskConfigDialog } from './TaskConfigDialog'

async function fileToBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer())
  let binary = ''
  const chunk = 0x8000
  for (let i = 0; i < bytes.length; i += chunk) binary += String.fromCharCode(...bytes.subarray(i, i + chunk))
  return btoa(binary)
}

function emptyGraph(): ExtractedGraph {
  return { vertices: [], edges: [] }
}

export function DocumentWorkspace({
  store,
  stores,
  onStoreChange,
  extractor,
  onInvalidate,
}: {
  store: string
  stores: Array<{ name: string; display: string }>
  onStoreChange: (store: string) => void
  extractor?: string
  onInvalidate: () => Promise<void>
}) {
  const { t } = useI18n()
  const qc = useQueryClient()
  const tasksQ = useQuery({ ...documentTasksQuery(store), enabled: Boolean(store) })
  const docsQ = useQuery({ ...documentsQuery(store), enabled: Boolean(store) })
  const [docId, setDocId] = useState<string | null>(null)
  const [dialog, setDialog] = useState(false)
  const [dialogDocs, setDialogDocs] = useState<string[]>([])
  const [configOpen, setConfigOpen] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [json, setJson] = useState('')
  const tasks = tasksQ.data?.tasks ?? []
  const docs = (docsQ.data?.documents ?? []).filter((doc) => doc.status === 'active')
  const taskByDoc = useMemo(() => {
    const byDoc = new Map<string, DocumentTaskSummary>()
    for (const task of [...tasks].sort((a, b) => b.id - a.id)) {
      if (!byDoc.has(task.doc_id)) byDoc.set(task.doc_id, task)
    }
    return byDoc
  }, [tasks])
  const selectedDoc = docs.find((doc) => doc.id === docId) ?? null
  const selectedTask = docId ? taskByDoc.get(docId) ?? null : null
  const taskId = selectedTask?.id ?? null

  useEffect(() => { setDocId(null) }, [store])

  useEffect(() => {
    if (docId !== null || !docs.length) return
    const withTask = docs.find((doc) => taskByDoc.has(doc.id))
    setDocId((withTask ?? docs[0]).id)
  }, [docs, docId, taskByDoc])

  const detailQ = useQuery({ ...documentTaskQuery(taskId), enabled: taskId !== null })
  const detail = detailQ.data
  const attempt = detail?.attempt ?? null
  useEffect(() => {
    const graph = attempt?.graph ?? emptyGraph()
    setJson(JSON.stringify(graph, null, 2))
  }, [attempt?.id, attempt?.graph])

  const parsed = useMemo<{ graph: ExtractedGraph | null; error: string | null }>(() => {
    try {
      const value = JSON.parse(json) as ExtractedGraph
      if (!value || !Array.isArray(value.vertices) || !Array.isArray(value.edges)) {
        return { graph: null, error: t('documents.task.invalidJson') }
      }
      return { graph: value, error: null }
    } catch {
      return { graph: null, error: t('documents.task.invalidJson') }
    }
  }, [json, t])

  const invalidate = async () => {
    await Promise.all([
      qc.invalidateQueries({ queryKey: ['document-tasks'] }),
      qc.invalidateQueries({ queryKey: ['document-task'] }),
      qc.invalidateQueries({ queryKey: ['document-stores'] }),
      qc.invalidateQueries({ queryKey: ['storage'] }),
    ])
    await onInvalidate()
  }

  const run = useMutation({
    mutationFn: () => apiClient.runDocumentTask(Number(taskId)),
    onSuccess: async () => { setError(null); await invalidate() },
    onError: (e) => setError(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e)),
  })
  const save = useMutation({
    mutationFn: () => apiClient.saveDocumentTask(Number(taskId), (parsed.graph ?? {}) as Record<string, unknown>),
    onSuccess: async () => { setError(null); await invalidate() },
    onError: (e) => setError(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e)),
  })
  const confirm = useMutation({
    mutationFn: () => apiClient.confirmDocumentTask(Number(taskId)),
    onSuccess: async () => { setError(null); await invalidate() },
    onError: (e) => setError(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e)),
  })
  const rerun = useMutation({
    mutationFn: () => apiClient.rerunDocumentTask(Number(taskId)),
    onSuccess: async (result) => {
      setError(null)
      setDocId(result.task.doc_id)
      await invalidate()
    },
    onError: (e) => setError(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e)),
  })

  const blockers = attempt?.validation?.blockers ?? []
  const warnings = attempt?.validation?.warnings ?? []
  const graph = parsed.graph ?? attempt?.graph ?? emptyGraph()
  const dirty = Boolean(parsed.graph) && JSON.stringify(parsed.graph) !== JSON.stringify(attempt?.graph ?? emptyGraph())
  const graphEmpty = !(graph.vertices?.length) && !(graph.edges?.length)
  const confirmReason = !detail?.attempt
    ? t('documents.task.runFirst')
    : graphEmpty
      ? t('documents.task.emptyGraph')
      : blockers.length
        ? `${blockers.length} ${t('documents.task.blockers')}`
        : dirty
          ? t('documents.task.saveFirst')
          : null
  const stage = detail?.status === 'confirmed' ? 3 : detail?.status === 'review' ? 2 : 1
  const steps = [t('documents.task.step.run'), t('documents.task.step.review'), t('documents.task.step.confirm')]

  return (
    <div className="grid min-h-0 flex-1 gap-3 lg:grid-cols-[300px_minmax(0,1fr)]">
      <Panel className="flex min-h-0 flex-col" testId="documents-tasks">
        <div className="border-b px-3 py-2" style={{ borderColor: 'var(--border-subtle)' }}>
          <select
            className="ontogeny-input w-full"
            aria-label={t('documents.store')}
            value={store}
            onChange={(e) => onStoreChange(e.target.value)}
            data-testid="documents-store"
          >
            {stores.map((s) => (
              <option key={s.name} value={s.name}>{s.display}</option>
            ))}
          </select>
        </div>
        <div className="flex flex-wrap items-center gap-2 border-b px-3 py-2" style={{ borderColor: 'var(--border-subtle)' }}>
          <span className="truncate text-[11px] font-semibold uppercase tracking-wide muted">{t('documents.workspace.documents')}</span>
          <Badge tone={extractor === 'loaded' ? 'success' : 'warning'} title={extractor === 'loaded' ? undefined : t('documents.extractor.hintInstall')}>
            {extractor === 'loaded' ? t('documents.extractor.loaded') : t('documents.extractor.missing')}
          </Badge>
          <Button size="sm" className="ml-auto" onClick={() => { setDialogDocs([]); setDialog(true) }} data-testid="documents-task-new">
            {t('documents.task.new')}
          </Button>
        </div>
        {extractor === 'missing' ? (
          <div className="border-b px-3 py-2 text-[11px] leading-relaxed" style={{ borderColor: 'var(--border-subtle)', color: 'var(--tone-warning-fg)' }}>
            {t('documents.extractor.hintInstall')}
          </div>
        ) : null}
        {docs.length === 0 ? (
          <EmptyState compact title={t('documents.task.empty')} description={t('documents.task.emptyBody')} />
        ) : (
          <div className="min-h-0 overflow-auto">
            {docs.map((doc) => {
              const task = taskByDoc.get(doc.id)
              return (
                <button
                  key={doc.id}
                  type="button"
                  onClick={() => { setDocId(doc.id); setError(null) }}
                  className="block w-full border-b px-3 py-2 text-left"
                  style={{
                    borderColor: 'var(--border-subtle)',
                    background: doc.id === docId ? 'var(--surface-sunken)' : 'transparent',
                  }}
                  data-testid={task ? `documents-task-${task.id}` : `documents-doc-${doc.id}`}
                >
                  <div className="flex items-center gap-2">
                    {task ? <Badge tone={toneForStatus(task.status)}>{task.status}</Badge> : <Badge tone="neutral">{t('documents.task.noTask')}</Badge>}
                    <span className="truncate text-[12px] font-medium" style={{ color: 'var(--text-primary)' }}>{doc.name}</span>
                    {task ? <span className="ml-auto text-[10.5px] muted">r{task.revision}</span> : null}
                  </div>
                  <div className="mt-0.5 truncate text-[10.5px] muted">
                    {task
                      ? `${task.skill?.name ? String(task.skill.name) : 'graph-extract'} · ${task.scope ? t('documents.task.scopeSummary') : 'global'}`
                      : `${doc.chunk_count} ${doc.chunk_count === 1 ? t('documents.task.chunkOne') : t('documents.task.chunks')}`}
                  </div>
                </button>
              )
            })}
          </div>
        )}
      </Panel>

      <Panel className="min-h-0 overflow-auto" testId="documents-task-detail">
        {!selectedTask && selectedDoc ? (
          <div className="flex h-full min-h-0 flex-col">
            <div className="flex flex-wrap items-center gap-2 border-b px-3 py-2" style={{ borderColor: 'var(--border-subtle)' }}>
              <Badge tone="neutral">{t('documents.task.noTask')}</Badge>
              <span className="text-[12.5px] font-medium" style={{ color: 'var(--text-primary)' }}>{selectedDoc.name}</span>
              <span className="text-[10.5px] muted">{selectedDoc.media_type ?? 'document'}</span>
              <Button
                size="sm"
                className="ml-auto"
                onClick={() => { setDialogDocs([selectedDoc.id]); setDialog(true) }}
                data-testid="documents-doc-create-task"
              >
                {t('documents.task.createFromDoc')}
              </Button>
            </div>
            <EmptyState
              compact
              title={t('documents.task.sourceOnlyTitle')}
              description={t('documents.task.sourceOnlyBody')}
              action={
                <Button size="sm" onClick={() => { setDialogDocs([selectedDoc.id]); setDialog(true) }} data-testid="documents-doc-create-task-empty">
                  {t('documents.task.createFromDoc')}
                </Button>
              }
            />
          </div>
        ) : detail ? (
          <div className="flex h-full min-h-0 flex-col">
            <div className="flex flex-wrap items-center gap-2 border-b px-3 py-2" style={{ borderColor: 'var(--border-subtle)' }}>
              <Badge tone={toneForStatus(detail.status)}>{detail.status}</Badge>
              <span className="text-[12.5px] font-medium" style={{ color: 'var(--text-primary)' }}>{detail.name}</span>
              <span className="text-[10.5px] muted">{t('documents.task.revision')} {detail.revision}</span>
              <div className="ml-auto flex shrink-0 flex-nowrap items-center gap-2">
                <Button
                  size="sm"
                  variant="subtle"
                  onClick={() => setConfigOpen(true)}
                  className="shrink-0 whitespace-nowrap"
                  data-testid="documents-task-config"
                >
                  {t('documents.task.configButton')}
                </Button>
                {detail.status !== 'confirmed' ? (
                  <Button
                    size="sm"
                    variant="primary"
                    icon={<IconPlay width={12} height={12} />}
                    onClick={() => run.mutate()}
                    disabled={run.isPending}
                    className="shrink-0 whitespace-nowrap"
                    data-testid="documents-task-run"
                  >
                    {t('documents.task.run')}
                  </Button>
                ) : null}
                {detail.status !== 'confirmed' && detail.attempt ? (
                  <Button
                    size="sm"
                    variant="ghost"
                    icon={<IconPencil width={12} height={12} />}
                    onClick={() => save.mutate()}
                    disabled={save.isPending || !parsed.graph}
                    className="shrink-0 whitespace-nowrap"
                    data-testid="documents-task-save"
                  >
                    {t('documents.task.save')}
                  </Button>
                ) : null}
                {detail.status !== 'confirmed' ? (
                  <Button
                    size="sm"
                    variant="success"
                    icon={<IconCheck width={12} height={12} />}
                    onClick={() => confirm.mutate()}
                    disabled={confirm.isPending || !detail.attempt || graphEmpty || blockers.length > 0 || dirty || !parsed.graph}
                    title={confirmReason ?? undefined}
                    className="shrink-0 whitespace-nowrap"
                    style={{ minWidth: 132 }}
                    data-testid="documents-task-confirm"
                  >
                    {t('documents.task.confirm')}
                  </Button>
                ) : (
                  <Button size="sm" variant="subtle" onClick={() => rerun.mutate()} disabled={rerun.isPending} data-testid="documents-task-rerun">
                    {t('documents.task.rerun')}
                  </Button>
                )}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2 border-b px-3 py-2" style={{ borderColor: 'var(--border-subtle)' }} data-testid="documents-task-flow">
              {steps.map((label, i) => {
                const done = stage > i + 1 || detail.status === 'confirmed'
                const current = stage === i + 1 && detail.status !== 'confirmed'
                return (
                  <div key={label} className="flex items-center gap-1.5">
                    <span
                      className="grid size-5 place-items-center rounded-full text-[10px] font-semibold"
                      style={{
                        background: done || current ? 'var(--color-brand-500)' : 'var(--surface-sunken)',
                        color: done || current ? '#fff' : 'var(--text-muted)',
                      }}
                    >
                      {done ? <IconCheck width={11} height={11} /> : i + 1}
                    </span>
                    <span className="text-[11px]" style={{ color: current ? 'var(--text-primary)' : 'var(--text-muted)', fontWeight: current ? 600 : 400 }}>{label}</span>
                    {i < steps.length - 1 ? <span className="mx-1 text-[10px]" style={{ color: 'var(--border-strong)' }}>→</span> : null}
                  </div>
                )
              })}
              <span
                className="ml-auto text-right text-[10.5px]"
                style={{ color: confirmReason ? 'var(--tone-warning-fg)' : 'var(--text-muted)' }}
              >
                {confirmReason ?? t('documents.task.flowHint')}
              </span>
            </div>
            {error ? <div className="px-3 pt-2"><ErrorBanner error={error} /></div> : null}
            {!detail.attempt ? (
              <EmptyState
                compact
                title={t('documents.task.runFirst')}
                description={t('documents.task.runHint')}
                action={<Button size="sm" onClick={() => run.mutate()} disabled={run.isPending} data-testid="documents-task-run-empty">{t('documents.task.runNow')}</Button>}
              />
            ) : (
              <>
                <div className="grid gap-2 border-b px-3 py-2 text-[11px] lg:grid-cols-3" style={{ borderColor: 'var(--border-subtle)' }}>
                  <div><span className="muted">{t('documents.task.scopeSummary')}: </span>{detail.scope ? Object.keys(detail.scope.objects).join(', ') : 'global'}</div>
                  <div><span className="muted">{t('documents.task.skillSummary')}: </span>{String(detail.skill?.name ?? 'graph-extract')} v{String(detail.skill?.version ?? 1)}</div>
                  <div><span className="muted">{t('documents.task.attempt', { n: detail.attempt.attempt_no })} · </span>{detail.attempt.provider ?? 'agent'}</div>
                </div>
                <Split cols="lg:grid-cols-2" className="min-h-0 flex-1">
                  <div className="min-h-0 overflow-auto p-4" data-testid="documents-task-original">
                    <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide muted">{t('documents.original')}</div>
                    {(detail.chunks.length ? detail.chunks : []).map((chunk, i) => (
                      <pre key={i} className="mb-3 whitespace-pre-wrap font-sans text-[12.5px] leading-relaxed">
                        {chunk.text}
                      </pre>
                    ))}
                  </div>
                  <div className="min-h-0 overflow-auto border-t p-4 lg:border-l lg:border-t-0" style={{ borderColor: 'var(--border-subtle)' }} data-testid="documents-task-graph">
                    <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide muted">{t('documents.extracted')}</div>
                    <ExtractionGraph
                      graph={graph}
                      jsonValue={json}
                      onJsonChange={setJson}
                      height={420}
                      testId="documents-task-extraction"
                    />
                    {parsed.error ? <p className="mt-2 text-[11px] text-[var(--tone-danger-fg)]">{parsed.error}</p> : null}
                    <p className="mt-2 text-[11px] muted">{dirty ? t('documents.task.saveFirst') : t('documents.task.editHint')}</p>
                  </div>
                </Split>
                {warnings.length ? (
                  <Alert tone="info" title={t('documents.task.warnings')} testId="documents-task-warnings">
                    <ul className="list-disc pl-4 text-[11.5px]">
                      {warnings.slice(0, 8).map((w, i) => <li key={i}>{w.reason}: {w.message ?? ''}</li>)}
                    </ul>
                  </Alert>
                ) : null}
                {blockers.length ? (
                  <Alert tone="warning" title={t('documents.task.blockers')} testId="documents-task-blockers">
                    <ul className="list-disc pl-4 text-[11.5px]">
                      {blockers.slice(0, 8).map((b, i) => <li key={i}>{b.reason}{b.object_type ? ` · ${b.object_type}` : ''}{b.link ? ` · ${b.link}` : ''}</li>)}
                    </ul>
                  </Alert>
                ) : (
                  <Alert tone="success" title={t('documents.task.noBlockers')} testId="documents-task-ready" />
                )}
                {detail.attempts.length > 1 ? (
                  <div className="border-t px-3 py-2 text-[11px] muted" style={{ borderColor: 'var(--border-subtle)' }}>
                    {detail.attempts.map((a) => `#${a.attempt_no} ${a.status}`).join(' · ')}
                  </div>
                ) : null}
              </>
            )}
          </div>
        ) : (
          <EmptyState compact title={t('documents.task.select')} />
        )}
      </Panel>

      {configOpen && detail ? (
        <TaskConfigDialog
          store={store}
          task={detail}
          onClose={() => setConfigOpen(false)}
          onSaved={async (next) => {
            setConfigOpen(false)
            setDocId(next.doc_id)
            await invalidate()
          }}
        />
      ) : null}
      {dialog ? (
        <NewTaskDialog
          store={store}
          initialDocIds={dialogDocs}
          onClose={() => setDialog(false)}
          onCreated={async (created) => {
            setDialog(false)
            setDocId(created[0]?.doc_id ?? null)
            await invalidate()
          }}
        />
      ) : null}
    </div>
  )
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="flex flex-col gap-2.5">
      <div>
        <div className="text-[11px] font-semibold uppercase tracking-[0.07em]" style={{ color: 'var(--text-secondary)' }}>{title}</div>
        {hint ? <p className="mt-0.5 text-[11.5px] muted">{hint}</p> : null}
      </div>
      {children}
    </section>
  )
}

function NewTaskDialog({ store, initialDocIds = [], onClose, onCreated }: {
  store: string
  initialDocIds?: string[]
  onClose: () => void
  onCreated: (tasks: DocumentTaskSummary[]) => Promise<void>
}) {
  const { t } = useI18n()
  const schemaQ = useQuery(documentSchemaQuery(store))
  const skillsQ = useQuery(documentSkillsQuery())
  const docsQ = useQuery({ ...documentsQuery(store), enabled: Boolean(store) })
  const existingDocs = (docsQ.data?.documents ?? []).filter((doc) => doc.status === 'active')
  const [files, setFiles] = useState<File[]>([])
  const [docIds, setDocIds] = useState<Set<string>>(new Set(initialDocIds))
  const [selected, setSelected] = useState<Record<string, Set<string>>>({})
  const [links, setLinks] = useState<Set<string>>(new Set())
  const [skillId, setSkillId] = useState('graph-extract')
  const [addendum, setAddendum] = useState('')
  const [error, setError] = useState<string | null>(null)
  const initRef = useRef(false)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (initRef.current || !schemaQ.data) return
    initRef.current = true
    const next: Record<string, Set<string>> = {}
    for (const obj of schemaQ.data.objects) next[obj.name] = new Set(obj.properties.map((p) => p.name))
    setSelected(next)
    setLinks(new Set(schemaQ.data.links.map((l) => l.name)))
  }, [schemaQ.data])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
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
  const validation = !files.length && docIds.size === 0
    ? t('documents.task.needFile')
    : selectedObjectCount === 0
      ? t('documents.task.needObject')
      : null

  const submit = () => {
    if (validation) {
      setError(validation)
      return
    }
    setError(null)
    create.mutate()
  }

  const create = useMutation({
    mutationFn: async () => {
      if (!files.length && docIds.size === 0) throw new Error(t('documents.task.needFile'))
      const objects: Record<string, string[]> = {}
      for (const [name, props] of Object.entries(selected)) {
        if (props.size) objects[name] = Array.from(props)
      }
      if (!Object.keys(objects).length) throw new Error(t('documents.task.needObject'))
      const scope: DocumentScope = { objects, links: Array.from(links) }
      const encoded = await Promise.all(files.map(async (f) => ({ name: f.name, content_b64: await fileToBase64(f) })))
      const skill: DocumentSkillInput = { id: skillId, addendum, examples: [], language: 'en' }
      return apiClient.createDocumentTasks(store, encoded, scope, skill, Array.from(docIds))
    },
    onSuccess: async (created) => { await onCreated(created.tasks) },
    onError: (e) => setError(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e)),
  })

  const dialog = (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-3 sm:p-4"
      style={{ background: 'rgba(15, 23, 42, 0.38)' }}
      role="dialog"
      aria-modal="true"
      aria-labelledby="documents-task-dialog-title"
      data-testid="documents-task-dialog"
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
            <div className="text-[10px] font-semibold uppercase tracking-[0.12em]" style={{ color: 'var(--color-brand-500)' }}>
              {t('documents.title')}
            </div>
            <h2 id="documents-task-dialog-title" className="mt-0.5 text-[18px] font-semibold" style={{ color: 'var(--text-primary)' }}>
              {t('documents.task.new')}
            </h2>
            <p className="mt-1 text-[12px] leading-relaxed muted">{t('documents.task.dialogHint')}</p>
          </div>
          <button
            type="button"
            className="ml-auto grid size-8 shrink-0 place-items-center rounded-lg"
            style={{ color: 'var(--text-muted)' }}
            onClick={onClose}
            aria-label={t('documents.task.cancel')}
          >
            <IconX width={16} height={16} />
          </button>
        </header>

        <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-5 py-4 sm:px-6">
          {error ? <ErrorBanner error={error} /> : null}

          <Section title={t('documents.task.existingDocs')} hint={t('documents.task.existingHint')}>
            {existingDocs.length === 0 ? (
              <p className="text-[11px] muted">{t('documents.task.noExistingDocs')}</p>
            ) : (
              <div className="max-h-[168px] overflow-y-auto rounded-xl border" style={{ borderColor: 'var(--border-subtle)' }}>
                {existingDocs.map((doc) => {
                  const checked = docIds.has(doc.id)
                  return (
                    <label key={doc.id} className="flex cursor-pointer items-center gap-2.5 border-b px-3 py-2 last:border-b-0" style={{ borderColor: 'var(--border-subtle)' }}>
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => setDocIds((prev) => {
                          const next = new Set(prev)
                          if (next.has(doc.id)) next.delete(doc.id)
                          else next.add(doc.id)
                          return next
                        })}
                        data-testid={`documents-task-existing-${doc.id}`}
                      />
                      <span className="min-w-0 flex-1 truncate text-[12px]" style={{ color: 'var(--text-primary)' }}>{doc.name}</span>
                      <span className="text-[10px] muted">{doc.chunk_count} {t('documents.task.chunks')}</span>
                    </label>
                  )
                })}
              </div>
            )}
          </Section>

          <Section title={t('documents.task.files')} hint={t('documents.task.fileHint')}>
            <input
              ref={fileRef}
              type="file"
              multiple
              accept=".md,.txt,.markdown,.pdf,.docx"
              className="hidden"
              data-testid="documents-task-files"
              onChange={(e) => { setFiles(Array.from(e.target.files ?? [])); setError(null) }}
            />
            <button
              type="button"
              onClick={() => fileRef.current?.click()}
              className="flex w-full items-center gap-3 rounded-xl border border-dashed px-4 py-3.5 text-left transition-colors"
              style={{ borderColor: 'var(--border-strong)', background: 'var(--surface-sunken)' }}
            >
              <span className="grid size-9 shrink-0 place-items-center rounded-lg" style={{ background: 'var(--brand-tint)', color: 'var(--brand-fg)' }}>
                <IconUpload width={16} height={16} />
              </span>
              <span className="min-w-0">
                <span className="block text-[12.5px] font-medium" style={{ color: 'var(--text-primary)' }}>{t('documents.task.chooseFiles')}</span>
                <span className="mt-0.5 block text-[11px] muted">.md · .txt · .pdf · .docx</span>
              </span>
            </button>
            {files.length ? (
              <div className="flex flex-col gap-1.5">
                {files.map((file, i) => (
                  <div key={`${file.name}-${i}`} className="flex items-center gap-2 rounded-lg border px-3 py-2" style={{ borderColor: 'var(--border-subtle)' }}>
                    <span className="min-w-0 flex-1 truncate text-[12px]" style={{ color: 'var(--text-primary)' }}>{file.name}</span>
                    <span className="text-[10.5px] muted">{formatBytes(file.size)}</span>
                    <button
                      type="button"
                      className="grid size-6 place-items-center rounded"
                      style={{ color: 'var(--text-muted)' }}
                      aria-label={t('documents.task.removeFile')}
                      onClick={() => setFiles((prev) => prev.filter((_, idx) => idx !== i))}
                    >
                      <IconX width={12} height={12} />
                    </button>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-[11px] muted">{t('documents.task.noFiles')}</p>
            )}
          </Section>

          <Section title={`${t('documents.task.scope')} · ${t('documents.task.objects')}`} hint={t('documents.task.scopeHint')}>
            {schemaQ.isLoading ? <p className="text-[11.5px] muted">{t('common.loading')}</p> : null}
            <div className="grid gap-2.5">
              {(schemaQ.data?.objects ?? []).map((obj) => {
                const active = (selected[obj.name]?.size ?? 0) > 0
                return (
                  <div
                    key={obj.name}
                    className="rounded-xl border p-3"
                    style={{
                      borderColor: active ? 'var(--color-brand-500)' : 'var(--border-subtle)',
                      background: active ? 'var(--brand-tint)' : 'var(--surface-card)',
                    }}
                  >
                    <label className="flex items-start gap-2.5">
                      <input
                        type="checkbox"
                        className="mt-0.5"
                        checked={active}
                        onChange={() => toggleObject(obj)}
                        aria-label={obj.display}
                      />
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
                          <label
                            key={prop.name}
                            className="flex cursor-pointer items-center gap-1 rounded-md border px-2 py-1 text-[10.5px]"
                            style={{
                              borderColor: on ? 'var(--border-strong)' : 'var(--border-subtle)',
                              background: on ? 'var(--surface-card)' : 'transparent',
                              color: on ? 'var(--text-primary)' : 'var(--text-muted)',
                              opacity: active ? 1 : 0.55,
                            }}
                          >
                            <input
                              type="checkbox"
                              className="size-3"
                              checked={on}
                              onChange={() => toggleProp(obj.name, prop.name)}
                              data-testid={`documents-task-prop-${obj.name}-${prop.name}`}
                            />
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
              {(() => {
                const refs = Array.from(new Set(
                  (schemaQ.data?.links ?? [])
                    .filter((link) => links.has(link.name) && link.source_is_reference)
                    .map((link) => link.source),
                ))
                return refs.length ? (
                  <p className="mt-1 text-[10.5px] muted">
                    {t('documents.task.references')}: <span className="font-mono">{refs.join(', ')}</span>
                  </p>
                ) : null
              })()}
            </div>
          </Section>

          <Section title={t('documents.task.skill')}>
            <select className="ontogeny-input" value={skillId} onChange={(e) => setSkillId(e.target.value)} data-testid="documents-task-skill">
              {(skillsQ.data?.skills ?? [{ id: 'graph-extract', display: '通用图抽取', name: 'graph-extract', version: 1, body: '', examples: [] }]).map((s) => (
                <option key={s.id} value={s.id}>{s.display || s.name} · v{s.version}</option>
              ))}
            </select>
            <label className="flex flex-col gap-1">
              <span className="text-[11px] muted">{t('documents.task.skillAddendum')}</span>
              <textarea
                className="ontogeny-input min-h-[84px] resize-y"
                value={addendum}
                onChange={(e) => setAddendum(e.target.value)}
                placeholder={t('documents.task.skillPlaceholder')}
                data-testid="documents-task-addendum"
              />
            </label>
          </Section>
        </div>

        <footer className="flex shrink-0 flex-wrap items-center gap-2 border-t px-5 py-3 sm:px-6" style={{ borderColor: 'var(--border-subtle)', background: 'var(--surface-sunken)' }}>
          <span className="text-[11px]" style={{ color: validation ? 'var(--tone-warning-fg)' : 'var(--text-muted)' }}>
            {validation ?? t('documents.task.footerHint')}
          </span>
          <div className="ml-auto flex items-center gap-2">
            <Button size="sm" variant="subtle" onClick={onClose}>{t('documents.task.cancel')}</Button>
            <Button
              size="sm"
              onClick={submit}
              disabled={create.isPending}
              data-testid="documents-task-create"
            >
              {create.isPending ? t('common.loading') : t('documents.task.create')}
            </Button>
          </div>
        </footer>
      </div>
    </div>
  )
  return createPortal(dialog, document.body)
}

export type { DocumentTaskDetail }
