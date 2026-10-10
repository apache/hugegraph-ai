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
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import { keys, invalidateMeta, useMeta } from '../api/queries'
import { useI18n } from '../i18n'
import { Alert, Badge, Button, Card, Skeleton } from './ui'
import { ErrorBanner } from './ErrorBanner'
import { IconLayers, IconRefresh, IconShield } from './icons'
import type { BadgeTone } from './ui'

/** Runtime config with live reachability and an in-place probe merged in.
 *
 * Three things used to live apart: the form, the probe button and the status
 * readout — you configured the LLM/HugeGraph endpoints, then scrolled to
 * separate "capability" cards to learn whether the values you typed actually
 * connect, all repeating the same status. Everything now shares one query per
 * service, each section header carries the live state of what it configures
 * (green = reachable, red = unreachable, grey = nothing configured), and the
 * LLM section ends with a one-shot grounded round-trip to prove the gateway. */
export function RuntimeConfigCard() {
  const { t, plural } = useI18n()
  const qc = useQueryClient()
  const cfg = useQuery({ queryKey: ['runtime-config'], queryFn: apiClient.runtimeConfig })
  // same keys the capability cards read: one cache, one refetch, no drift
  const llm = useQuery({ queryKey: ['llm-status'], queryFn: () => apiClient.llmStatus(), retry: false })
  const projection = useQuery({
    queryKey: keys.projection,
    queryFn: apiClient.projectionSummary,
    retry: false,
  })
  const [llmProvider, setLlmProvider] = useState('ollama')
  const [llmUrl, setLlmUrl] = useState('')
  const [model, setModel] = useState('')
  const [apiKey, setApiKey] = useState('')
  const [storageProvider, setStorageProvider] = useState('sqlite')
  const [storageUrl, setStorageUrl] = useState('')
  const [storageUser, setStorageUser] = useState('')
  const [storagePassword, setStoragePassword] = useState('')
  // the capability probe lives IN the form: what you configure is what gets
  // verified — a separate "capability:llm" card only repeated the same status
  // one screen below the fields that produce it
  const [llmReply, setLlmReply] = useState<string | null>(null)
  const llmProbe = useMutation({
    mutationFn: async () => {
      const out = await apiClient.assistantChat(
        [{ role: 'user', content: 'Reply with one short sentence: which package is loaded?' }],
        false,
      )
      setLlmReply(out.content)
      return out
    },
  })
  // direction 4: leaving an INITIALIZED HugeGraph is a severe operation -- it
  // demands a typed-out domain name before the form even changes
  const [pendingSwitch, setPendingSwitch] = useState<string | null>(null)
  const [confirmName, setConfirmName] = useState('')
  const meta = useMeta()
  const domainName = String(meta.data?.package ?? '')

  useEffect(() => {
    if (!cfg.data) return
    setLlmProvider(cfg.data.llm.provider)
    setLlmUrl(cfg.data.llm.base_url ?? '')
    setModel(cfg.data.llm.model ?? '')
    setApiKey('')
    setStorageProvider(cfg.data.storage.provider)
    setStorageUrl(cfg.data.storage.url ?? '')
    setStorageUser(cfg.data.storage.user ?? '')
    setStoragePassword('')
  }, [cfg.data])

  const save = useMutation({
    mutationFn: () => apiClient.saveRuntimeConfig({
      llm_provider: llmProvider,
      llm_base_url: llmUrl.trim() || null,
      llm_model: model.trim() || null,
      llm_api_key: apiKey.trim() || null,
      storage_provider: storageProvider,
      storage_url: storageUrl.trim() || null,
      storage_user: storageUser.trim() || null,
      // blank keeps the stored password, exactly like the API key above
      storage_password: storagePassword.trim() || null,
    }),
    onSuccess: () => {
      setApiKey('')
      setStoragePassword('')
      qc.invalidateQueries({ queryKey: keys.runtimeConfig })
      qc.invalidateQueries({ queryKey: keys.llmStatus })
      qc.invalidateQueries({ queryKey: keys.extensions })
      qc.invalidateQueries({ queryKey: keys.projection })
    },
  })

  // ---- the graph: declare a projection, then build it ---------------------
  // Saving the provider alone cannot produce a graph: HugeGraph needs a
  // Projection resource to know *what* to mirror. Without one the storage card
  // used to dead-end on "no projection declared". These two actions close the
  // loop from this card: `scaffold` derives the projection from the ontology,
  // publishes it and backfills; `rebuild` re-runs the backfill afterwards.
  const refreshGraph = () => {
    qc.invalidateQueries({ queryKey: keys.projection })
    qc.invalidateQueries({ queryKey: keys.projectionVerticesPrefix })
    qc.invalidateQueries({ queryKey: keys.projectionEdgesPrefix })
    void invalidateMeta(qc)
  }
  const scaffold = useMutation({
    mutationFn: () => apiClient.scaffoldProjection(),
    onSuccess: refreshGraph,
  })
  const rebuild = useMutation({
    mutationFn: () => apiClient.rebuildProjection(),
    onSuccess: refreshGraph,
  })

  const counts = scaffold.data ?? rebuild.data
  const graphBusy = scaffold.isPending || rebuild.isPending

  // ---- reachability badges: one per section header ------------------------
  const llmTone: BadgeTone = llm.error ? 'danger'
    : !llm.data?.configured ? 'neutral'
    : llm.data.ok ? 'success' : 'danger'
  const llmLabel = llm.error ? t('common.unknown')
    : !llm.data?.configured ? t('ops.llm.absent')
    : llm.data.ok ? plural('admin.llm.reachable', (llm.data.models ?? []).length)
    : t('admin.llm.unreachable')
  const storageIsHg = cfg.data?.storage.provider === 'hugegraph'
  // a probe still in flight is not a verdict: "no projection declared" while the
  // answer is loading is a claim the console would then have to take back
  const storagePending = projection.isLoading || cfg.isLoading
  const storageTone: BadgeTone = storagePending ? 'neutral'
    : !storageIsHg ? 'neutral'
    : projection.error ? 'danger'
    : !projection.data?.configured ? 'warning'
    : projection.data.ok ? 'success' : 'danger'
  const storageLabel = storagePending ? t('common.loading')
    : !storageIsHg ? t('ops.runtime.storage.sqlOnly')
    : projection.error ? t('common.unknown')
    : !projection.data?.configured ? t('ops.runtime.storage.noDecl')
    : projection.data.ok ? t('ops.runtime.storage.ok') : t('ops.runtime.storage.bad')

  return (
    <Card
      // no title here: the card sits under the ops console's "runtime config"
      // section heading, which already says what it is — a second title read as
      // a stutter. The header survives only for the saved badge.
      actions={save.isSuccess ? <Badge tone="success">{t('ops.runtime.saved')}</Badge> : null}
    >
      {cfg.isLoading ? <Skeleton rows={3} /> : cfg.error ? <ErrorBanner error={cfg.error} /> : (
        <div className="grid gap-5 lg:grid-cols-2">
          <section className="flex min-w-0 flex-col gap-3">
            <h3 className="flex items-center gap-2 text-[13px] font-semibold">
              {t('ops.runtime.llm')}
              <span title={llm.data && !llm.error ? `${llm.data.base_url ?? ''} · ${llm.data.model ?? ''}` : undefined}>
                <Badge tone={llmTone}>{llmLabel}</Badge>
              </span>
            </h3>
            <label className="block">
              <span className="ontogeny-label" style={{ marginBottom: 4 }}>{t('ops.runtime.provider')}</span>
              <select className="ontogeny-input" value={llmProvider} onChange={(e) => setLlmProvider(e.target.value)}>
                <option value="ollama">{t('ops.runtime.llm.ollama')}</option>
                <option value="external">{t('ops.runtime.llm.external')}</option>
                <option value="disabled">{t('ops.runtime.llm.disabled')}</option>
              </select>
            </label>
            {llmProvider !== 'disabled' ? (
              <>
                <label className="block">
                  <span className="ontogeny-label" style={{ marginBottom: 4 }}>{t('ops.runtime.baseUrl')}</span>
                  <input className="ontogeny-input font-mono" value={llmUrl}
                         placeholder={llmProvider === 'external' ? 'https://api.example.com/v1' : 'http://127.0.0.1:11434'}
                         onChange={(e) => setLlmUrl(e.target.value)} />
                </label>
                <label className="block">
                  <span className="ontogeny-label" style={{ marginBottom: 4 }}>{t('ops.runtime.model')}</span>
                  <input className="ontogeny-input font-mono" value={model}
                         placeholder={llmProvider === 'external' ? 'gpt-4o-mini' : 'qwen3:27b'}
                         onChange={(e) => setModel(e.target.value)} />
                </label>
              </>
            ) : null}
            {llmProvider === 'external' ? (
              <label className="block">
                <span className="ontogeny-label" style={{ marginBottom: 4 }}>{t('ops.runtime.apiKey')}</span>
                <input className="ontogeny-input font-mono" type="password" value={apiKey}
                       placeholder={cfg.data?.llm.api_key_set ? t('ops.runtime.apiKeySet') : 'sk-...'}
                       onChange={(e) => setApiKey(e.target.value)} />
              </label>
            ) : null}
            {/* the probe: configured gateway → one grounded round-trip, here,
                not on a capability card that repeated this section's status */}
            {llm.data?.configured ? (
              <div className="mt-1 flex flex-col items-start gap-2">
                <Button data-testid="llm-probe" onClick={() => llmProbe.mutate()} disabled={llmProbe.isPending}>
                  {t('ext.scenario.llmRun')}
                </Button>
                {llmProbe.error ? <ErrorBanner error={llmProbe.error} /> : null}
                {llmReply ? (
                  <div
                    className="w-full rounded-xl px-3.5 py-3 text-[12.5px] leading-relaxed"
                    data-testid="llm-probe-result"
                    style={{ background: 'var(--surface-sunken)', border: '1px solid var(--border-subtle)' }}
                  >
                    {llmReply}
                  </div>
                ) : null}
              </div>
            ) : null}
          </section>

          <section className="flex min-w-0 flex-col gap-3 lg:border-l lg:pl-5" style={{ borderColor: 'var(--border-subtle)' }}>
            <h3 className="flex items-center gap-2 text-[13px] font-semibold">
              {t('ops.runtime.storage')}
              <span title={t('ops.runtime.statusHint')}>
                <Badge tone={storageTone}>{storageLabel}</Badge>
              </span>
            </h3>
            <label className="block">
              <span className="ontogeny-label" style={{ marginBottom: 4 }}>{t('ops.runtime.provider')}</span>
              <select className="ontogeny-input" data-testid="storage-provider"
                      value={storageProvider}
                      onChange={(e) => {
                        const next = e.target.value
                        const leavingInitializedHugeGraph =
                          cfg.data?.storage.provider === 'hugegraph'
                          && storageProvider === 'hugegraph'
                          && next !== 'hugegraph'
                          && projection.data?.configured === true
                        if (leavingInitializedHugeGraph) {
                          setPendingSwitch(next) // severe-warning dialog decides
                          return
                        }
                        setStorageProvider(next)
                      }}>
                <option value="hugegraph">{t('ops.runtime.storage.hugegraph')}</option>
                <option value="sqlite">{t('ops.runtime.storage.sqlite')}</option>
              </select>
            </label>
            {storageProvider === 'hugegraph' ? (
              <label className="block">
                <span className="ontogeny-label" style={{ marginBottom: 4 }}>{t('ops.runtime.hugegraph')}</span>
                <input className="ontogeny-input font-mono" value={storageUrl}
                       placeholder="http://127.0.0.1:8080"
                       onChange={(e) => setStorageUrl(e.target.value)} />
              </label>
            ) : null}

            {storageProvider === 'hugegraph' ? (
              <>
                <div className="grid grid-cols-2 gap-3">
                  <label className="block">
                    <span className="ontogeny-label" style={{ marginBottom: 4 }}>{t('ops.runtime.storage.user')}</span>
                    <input className="ontogeny-input font-mono text-[12.5px]" value={storageUser}
                           data-testid="storage-user"
                           placeholder="admin"
                           onChange={(e) => setStorageUser(e.target.value)} />
                  </label>
                  <label className="block">
                    <span className="ontogeny-label" style={{ marginBottom: 4 }}>{t('ops.runtime.storage.password')}</span>
                    <input className="ontogeny-input font-mono text-[12.5px]" type="password" value={storagePassword}
                           data-testid="storage-password"
                           placeholder={cfg.data?.storage.password_set
                             ? t('ops.runtime.apiKeySet') : t('ops.runtime.storage.passwordHint')}
                           onChange={(e) => setStoragePassword(e.target.value)} />
                  </label>
                </div>
                {/* Why these exist at all: a HugeGraph in auth mode refuses
                    anonymous calls, and 1.7 only allows the platform to CREATE a
                    graph when auth is on — so this pair is what makes "the
                    platform creates its own graph" possible. Stated in the UI
                    because an operator meeting a 401 has nowhere else to look. */}
                <p className="text-[11px] leading-relaxed muted" data-testid="storage-auth-hint">
                  {t('ops.runtime.storage.authHint')}
                </p>
                {/* A rejected credential and an unreachable server look identical
                    from the outside ("cannot probe"), but only one of them is
                    fixed by retyping the password — so say which it is. */}
                {projection.data?.auth_rejected ? (
                  <Alert tone="danger" testId="storage-auth-rejected">
                    {t('ops.runtime.storage.authRejected')}
                  </Alert>
                ) : null}
              </>
            ) : null}

            {/* The graph itself, and its one name: the domain's own English name.
                A domain and a graph are one-to-one, so the only question left is
                whether that graph is already on the server — if it is, it is
                LOADED (its contents are left alone), and only a missing graph is
                built. */}
            {storageProvider === 'hugegraph' ? (
              <div className="rounded-lg p-3" style={{ background: 'var(--surface-sunken)' }} data-testid="graph-control">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-[11.5px] muted">{t('ops.runtime.graph.name')}</span>
                  <Badge tone="neutral" mono>
                    {projection.data?.graph_name ?? projection.data?.graph ?? '—'}
                  </Badge>
                  {projection.data?.graph_exists === true ? <Badge tone="success">{t('ops.runtime.graph.onServer')}</Badge> : null}
                  {projection.data?.graph_exists === false ? <Badge tone="warning">{t('ops.runtime.graph.absent')}</Badge> : null}
                  {projection.data?.graph_exists === null ? <Badge tone="neutral">{t('ops.runtime.graph.unknown')}</Badge> : null}
                </div>

                {!projection.data?.configured ? (
                  projection.data?.declared ? (
                    /* A projection IS declared; the graph layer is only unwired.
                       Offering "create a projection" here was a dead end: the
                       backend refuses it (ALREADY_DECLARED). Say what is
                       actually missing and where to fix it. */
                    <Alert tone="warning" testId="projection-blocked">
                      {t(`ops.runtime.graph.blocked.${projection.data.blocked_by ?? 'unknown'}`)}
                    </Alert>
                  ) : (
                    <>
                      <p className="mt-2 text-[11.5px] leading-relaxed secondary-text">
                        {projection.data?.graph_exists
                          ? t('ops.runtime.graph.adoptHint')
                          : t('ops.runtime.graph.missing')}
                      </p>
                      <Button
                        className="mt-2.5"
                        variant="primary"
                        size="sm"
                        data-testid="graph-scaffold"
                        disabled={graphBusy}
                        onClick={() => scaffold.mutate()}
                        icon={<IconLayers width={13} height={13} />}
                      >
                        {scaffold.isPending ? t('ops.runtime.graph.building')
                          : projection.data?.graph_exists ? t('ops.runtime.graph.load') : t('ops.runtime.graph.create')}
                      </Button>
                    </>
                  )
                ) : (
                  <>
                    <div className="mt-2 flex flex-wrap items-center gap-2">
                      <span className="text-[11.5px] muted">
                        {projection.data.graph_exists === false
                          ? t('ops.runtime.graph.emptyOnServer')
                          : t('ops.runtime.graph.counts', {
                            vertices: counts?.vertices ?? graphVertexCount(projection.data),
                            edges: counts?.edges ?? graphEdgeCount(projection.data),
                          })}
                      </span>
                      <Button
                        className="ml-auto"
                        size="sm"
                        data-testid="graph-rebuild"
                        disabled={graphBusy}
                        onClick={() => rebuild.mutate()}
                        icon={<IconRefresh width={13} height={13} />}
                      >
                        {rebuild.isPending ? t('ops.runtime.graph.building') : t('ops.runtime.graph.rebuild')}
                      </Button>
                    </div>
                    {/* A destructive action says so, next to itself. */}
                    <p className="mt-1.5 text-[10.5px] muted">{t('ops.runtime.graph.rebuildHint')}</p>
                  </>
                )}
                {scaffold.error ? <div className="mt-2"><ErrorBanner error={scaffold.error} /></div> : null}
                {rebuild.error ? <div className="mt-2"><ErrorBanner error={rebuild.error} /></div> : null}
                {scaffold.data ? (
                  <div className="mt-2" data-testid="graph-built">
                    <Alert tone="success">
                      {t(`ops.runtime.graph.${scaffold.data.action}`, {
                        vertices: scaffold.data.vertices,
                        edges: scaffold.data.edges,
                        path: scaffold.data.path,
                        graph: scaffold.data.graph,
                      })}
                    </Alert>
                  </div>
                ) : null}
              </div>
            ) : null}
          </section>
        </div>
      )}
      {/* direction 4: the severe warning for walking away from an initialized
          HugeGraph -- nothing happens until the domain's full name is typed. */}
      {pendingSwitch !== null ? createPortal(
        <div className="fixed inset-0 z-50 grid place-items-center p-4" style={{ background: 'rgba(0,0,0,.55)' }}
             data-testid="storage-switch-overlay">
          <div role="alertdialog" aria-modal="true" data-testid="storage-switch-dialog"
               className="ontogeny-card ontogeny-modal w-full max-w-lg p-5">
            <div className="flex items-start gap-3">
              <span className="grid size-9 shrink-0 place-items-center rounded-lg"
                    style={{ background: 'var(--tone-danger-bg)', color: 'var(--tone-danger-fg)' }}>
                <IconShield width={17} height={17} />
              </span>
              <div className="min-w-0">
                <h2 className="text-[14px] font-semibold" style={{ color: 'var(--tone-danger-fg)' }}>
                  {t('ops.runtime.storage.switch.title')}
                </h2>
                <p className="mt-1 text-[12px] muted">{t('ops.runtime.storage.switch.subtitle')}</p>
              </div>
            </div>
            <ul className="mt-3 flex list-disc flex-col gap-1.5 pl-5 text-[12.5px] leading-relaxed">
              <li>{t('ops.runtime.storage.switch.c1')}</li>
              <li>{t('ops.runtime.storage.switch.c2')}</li>
              <li>{t('ops.runtime.storage.switch.c3')}</li>
              <li>{t('ops.runtime.storage.switch.c4')}</li>
            </ul>
            <div className="mt-4">
              <span className="ontogeny-label">{t('ops.runtime.storage.switch.typeName')}</span>
              <input className="ontogeny-input mt-1 font-mono" data-testid="storage-switch-confirm"
                     value={confirmName}
                     placeholder={domainName}
                     onChange={(e) => setConfirmName(e.target.value)} />
              <p className="mt-1 text-[11px] muted">{t('ops.runtime.storage.switch.typeHint', { name: domainName })}</p>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <Button size="sm" data-testid="storage-switch-cancel" onClick={() => { setPendingSwitch(null); setConfirmName('') }}>
                {t('common.cancel')}
              </Button>
              <Button size="sm" variant="primary" data-testid="storage-switch-confirm-btn"
                      style={{ background: 'var(--tone-danger-fg)' }}
                      disabled={confirmName.trim() !== domainName || !domainName}
                      onClick={() => { setStorageProvider(pendingSwitch); setPendingSwitch(null); setConfirmName('') }}>
                {t('ops.runtime.storage.switch.confirm')}
              </Button>
            </div>
          </div>
        </div>,
        document.body,
      ) : null}
      {cfg.error ? null : (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <Button variant="primary" data-testid="runtime-config-save"
                  onClick={() => save.mutate()} disabled={save.isPending}
                  icon={<IconRefresh width={14} height={14} />}>
            {save.isPending ? '…' : t('ops.runtime.save')}
          </Button>
          {save.error ? <ErrorBanner error={save.error} /> : null}
        </div>
      )}
    </Card>
  )
}

/** Totals from the live label inventory — what the graph holds right now, vs the
 *  counts a just-finished build reports. */
function graphVertexCount(summary?: { counts?: { vertices?: Record<string, number> } }): number {
  return Object.values(summary?.counts?.vertices ?? {}).reduce((a, b) => a + b, 0)
}

function graphEdgeCount(summary?: { counts?: { edges?: Record<string, number> } }): number {
  return Object.values(summary?.counts?.edges ?? {}).reduce((a, b) => a + b, 0)
}
