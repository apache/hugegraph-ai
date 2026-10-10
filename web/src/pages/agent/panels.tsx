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
 * Agent governance panels: the three surfaces that used to be tabs of the
 * console and now live in the sidebar's "agent management" module.
 *
 * - SessionsPanel  one run's step timeline: every tool call, its stable outcome
 *   code, latency and any revision it produced.
 * - ApprovalsPanel the human gate for writes: an agent's pending intent is
 *   executed only when a principal who holds the action's permit themselves
 *   approves it — the decision is audited to the human, the execution to the
 *   plugin.
 * - PluginsPanel   each plugin's frozen principal, tool subset (the
 *   allow∩catalog−deny intersection), approval posture and budget.
 */
import { useEffect, useMemo, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../../api/client'
import { keys } from '../../api/queries'
import { useI18n } from '../../i18n'
import {
  Alert, Badge, Button, Card, EmptyState, KeyValue,
  ProgressBar, Skeleton, SpecRow, Strip,
} from '../../components/ui'
import { ErrorBanner } from '../../components/ErrorBanner'
import type { BadgeTone } from '../../components/ui'
import { fmtDate } from '../../lib/rows'
import { JsonView } from '../../components/JsonView'
import {
  IconClock, IconCog, IconPlay, IconPlus, IconShield, IconSpark, IconTrash,
} from '../../components/icons'
import { NewPluginDialog } from './NewPluginDialog'
import { CreateSessionDialog } from './CreateSessionDialog'
import { outcomeTone, statusTone } from './tone'

/* ---------------------------------------------------------------- plugins */

export function PluginsPanel() {
  const plugins = useQuery({ queryKey: ['agent-plugins'], queryFn: apiClient.agentPlugins })
  const declared = plugins.data?.plugins ?? []

  return (
    <PluginsTab
      plugins={declared}
      loading={plugins.isLoading}
      error={plugins.error}
      onCreated={() => plugins.refetch()}
    />
  )
}

function PluginsTab({ plugins, loading, error, onCreated }: {
  plugins: import('../../api/types').AgentPluginInfo[]
  loading: boolean
  error: unknown
  onCreated?: () => void
}) {
  const { t, plural } = useI18n()
  const [newOpen, setNewOpen] = useState(false)
  // direction 3: editing fetches the plugin's raw resource and prefills
  const [editTarget, setEditTarget] = useState<{ name: string; resource: Record<string, any> } | null>(null)
  const openEdit = async (name: string) => {
    const r = await apiClient.agentPluginResource(name)
    setEditTarget({ name, resource: r.resource })
    setNewOpen(true)
  }
  if (loading) return <Skeleton rows={6} />
  if (error) return <ErrorBanner error={error} />
  if (plugins.length === 0) {
    // the empty package is exactly when creating the first plugin matters, so
    // the dialog door is wired here too — not only into the fleet's stats band
    return (
      <Card>
        <EmptyState
          title={t('agent.pluginsEmpty')}
          description={t('agent.pluginsEmptyHint')}
          icon={<IconCog width={18} height={18} />}
          action={
            <Button
              variant="primary"
              data-testid="new-plugin-open"
              icon={<IconPlus width={14} height={14} />}
              onClick={() => setNewOpen(true)}
            >
              {t('agent.new.open')}
            </Button>
          }
        />
        <NewPluginDialog
          key="empty-new"
          open={newOpen}
          onClose={() => setNewOpen(false)}
          existingNames={[]}
          onCreated={onCreated}
        />
      </Card>
    )
  }

  const allTools = plugins.flatMap((p) => Object.values(p.tools))
  const writeTools = allTools.filter((x) => x.writes)
  const engines = new Set(plugins.map((p) => p.engine?.kind ?? 'external-pull'))

  return (
    <div className="flex flex-col gap-5">
      {/* one slim band: the plugin fleet's numbers and the create action,
          so a button row never floats alone above the cards */}
      <div
        className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl px-3.5 py-2"
        style={{ background: 'var(--surface-sunken)', border: '1px solid var(--border-subtle)' }}
      >
        <span className="flex items-center gap-1.5">
          <Badge tone="brand" mono>{plugins.length}</Badge>
          <span className="text-[11.5px] muted">{t('agent.stat.plugins')}</span>
        </span>
        <span className="flex items-center gap-1.5">
          <Badge tone="violet" mono>{engines.size}</Badge>
          <span className="text-[11.5px] muted">{t('agent.stat.engines')}</span>
        </span>
        <span className="flex items-center gap-1.5">
          <Badge tone="info" mono>{allTools.length}</Badge>
          <span className="text-[11.5px] muted">{t('agent.stat.tools')}</span>
        </span>
        <span className="flex items-center gap-1.5">
          <Badge tone={writeTools.length ? 'warning' : 'success'} mono>{writeTools.length}</Badge>
          <span className="text-[11.5px] muted">{t('agent.stat.writes')}</span>
        </span>
        <Button
          size="sm"
          className="ml-auto"
          data-testid="new-plugin-open"
          onClick={() => setNewOpen(true)}
          icon={<IconPlus width={14} height={14} />}
        >
          {t('agent.new.open')}
        </Button>
      </div>
      <NewPluginDialog
        key={editTarget?.name ?? 'new'}
        open={newOpen}
        onClose={() => { setNewOpen(false); setEditTarget(null) }}
        existingNames={plugins.map((p) => p.name)}
        onCreated={onCreated}
        editing={editTarget}
      />

      <div className="grid items-start gap-5 xl:grid-cols-2">
        {plugins.map((p) => {
          const tools = Object.values(p.tools)
          const writes = tools.filter((x) => x.writes)
          const principal = p.principal as Record<string, unknown>
          const principalId = String(principal.id ?? '—')
          const roles = (principal.Role ?? principal.roles ?? []) as string[]
          const site = principal.site ? String(principal.site) : null
          return (
            <Card
              key={p.name}
              title={<span className="font-mono">{p.name}</span>}
              description={p.display ?? p.description}
              actions={
                <span className="flex items-center gap-1.5">
                  <Badge tone="info">{t(`agent.engine.${p.engine?.kind ?? 'external-pull'}`)}</Badge>
                  <Badge tone={p.approval === 'never' ? 'neutral' : p.approval === 'auto' ? 'warning' : 'brand'}>
                    {p.approval === 'never' ? t('agent.readonly')
                      : p.approval === 'auto' ? t('agent.auto') : t('agent.confirm')}
                  </Badge>
                  <Button
                    size="sm"
                    square
                    variant="subtle"
                    data-testid={`edit-plugin-${p.name}`}
                    title={t('agent.new.editTitle')}
                    aria-label={t('agent.new.editTitle')}
                    onClick={() => void openEdit(p.name)}
                    icon={<IconCog width={13} height={13} />}
                  />
                </span>
              }
            >
              {/* frozen identity = the plugin's whole permission surface */}
              <Strip label={t('agent.principal')}>
                <code className="ontogeny-code">{principalId}</code>
                {roles.map((r) => <Badge key={r} tone="brand">{r}</Badge>)}
                {site ? <Badge tone="info">{t('agent.site')} {site}</Badge> : null}
              </Strip>

              <SpecRow
                className="mt-3"
                items={[
                  { label: t('agent.budget.steps'), value: String(p.budget.steps) },
                  { label: t('agent.budget.wall'), value: `${p.budget.wall_ms} ms` },
                  { label: t('agent.writes'), value: String(p.budget.writes_per_session) },
                ]}
              />

              <div className="mt-4">
                <div className="mb-2 flex items-center justify-between">
                  <span className="ontogeny-label">{plural('agent.toolCount', tools.length)}</span>
                  <span className="text-[11.5px] muted">
                    {tools.filter((x) => !x.writes).length} {t('agent.readonly')} · {writes.length} {t('agent.writes')}
                  </span>
                </div>
                <ToolList tools={tools} />
              </div>
            </Card>
          )
        })}
      </div>
    </div>
  )
}

/** Tool catalogue as hairline rows inside the card. Capped at a few rows plus a
 *  count so a 10-tool plugin and a 5-tool plugin stay comparable in height —
 *  the remainder is named in the footer's tooltip rather than hidden. */
const TOOL_ROWS = 6

function ToolList({ tools }: { tools: import('../../api/types').AgentToolDef[] }) {
  const { t, plural } = useI18n()
  const shown = tools.slice(0, TOOL_ROWS)
  const rest = tools.slice(TOOL_ROWS)
  return (
    <div style={{ borderTop: '1px solid var(--border-subtle)' }}>
      <table className="w-full">
        <thead>
          <tr>
            <th scope="col" className="ontogeny-th">{t('agent.step.tool')}</th>
            <th scope="col" className="ontogeny-th">kind</th>
            <th scope="col" className="ontogeny-th" style={{ textAlign: 'right' }}>{t('agent.writes')}</th>
          </tr>
        </thead>
        <tbody>
          {shown.map((x) => (
            <tr key={x.name} className="transition-colors hover:bg-[var(--surface-hover)]">
              <td className="ontogeny-td font-mono text-[11.5px]">{x.name}</td>
              <td className="ontogeny-td">
                <Badge tone={x.kind === 'act' ? 'violet' : x.kind === 'search' ? 'info' : 'neutral'} mono>{x.kind}</Badge>
              </td>
              <td className="ontogeny-td" style={{ textAlign: 'right' }}>
                {x.writes
                  ? <span style={{ color: 'var(--tone-warning-fg)' }} title={t('agent.writes')}>●</span>
                  : <span className="muted">—</span>}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {rest.length ? (
        <div
          className="px-5 py-2 text-[11.5px] muted"
          style={{ borderTop: '1px solid var(--border-subtle)' }}
          title={rest.map((x) => x.name).join('\n')}
        >
          {plural('agent.moreTools', rest.length)}
        </div>
      ) : null}
    </div>
  )
}

/* --------------------------------------------------------------- sessions */

/** Backend status -> the catalogue's translation, falling back to the raw code
 *  for statuses the UI has never heard of. */
/** Budget display: a cap of 0 means UNLIMITED -- shown as ∞, never as 0. */
export const fmtCap = (cap: number): string => (cap > 0 ? String(cap) : '∞')

function statusLabel(status: string, t: (k: string) => string): string {
  const key = `agent.status.${status}`
  return t(key) !== key ? t(key) : status
}

export function SessionsPanel() {
  const { t, lang } = useI18n()
  const qc = useQueryClient()
  const nav = useNavigate()
  const [openId, setOpenId] = useState<number | null>(null)
  // direction 1: creation moved into a dialog -- plugin, budgets (default
  // unlimited) and expiry (default none) are configured there
  const [createOpen, setCreateOpen] = useState(false)
  // the 创建会话 button lives in the page header (AgentManagement toolbar),
  // one rail above this panel — it asks this panel to open the dialog
  useEffect(() => {
    const open = () => setCreateOpen(true)
    window.addEventListener('ontogeny:agent-sessions-create', open)
    return () => window.removeEventListener('ontogeny:agent-sessions-create', open)
  }, [])

  const plugins = useQuery({ queryKey: ['agent-plugins'], queryFn: apiClient.agentPlugins })
  const declared = plugins.data?.plugins ?? []
  const sessions = useQuery({
    queryKey: keys.agentSessions(''),
    queryFn: () => apiClient.agentSessions(),
    refetchInterval: 5000,
  })
  const detail = useQuery({
    queryKey: keys.agentSession(openId),
    queryFn: () => apiClient.agentSession(openId!),
    enabled: openId !== null,
    refetchInterval: 4000,
  })

  const finish = useMutation({
    mutationFn: (id: number) => apiClient.agentFinish(id, { closed_by: 'console' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agent-session'] }),
  })
  const remove = useMutation({
    mutationFn: (id: number) => apiClient.agentDeleteSession(id),
    onSuccess: (_out, id) => {
      if (openId === id) setOpenId(null)
      qc.invalidateQueries({ queryKey: ['agent-session'] })
      qc.invalidateQueries({ queryKey: ['agent-sessions'] })
    },
  })

  const current = detail.data
  const currentEngineKind = plugins.data?.plugins.find((p) => p.name === current?.plugin)?.engine.kind
  const rows = sessions.data?.sessions ?? []

  return (
    <div className="flex flex-col gap-5">
      {/* ONE surface: the header carries the live counts, the toolbar the
          new-session controls, and the body is list + detail of the same panel */}
      <Card
        padded={false}
        bare
      >
        <CreateSessionDialog
          open={createOpen}
          plugins={declared}
          onClose={() => setCreateOpen(false)}
          onCreated={(s) => { setOpenId(s.id); qc.invalidateQueries({ queryKey: ['agent-sessions'] }) }}
        />
        <div className="grid min-h-0 lg:grid-cols-[minmax(300px,360px)_1fr]">
          {/* the run list: compact rows (id · plugin · status · task · budget)
              instead of a heavy table, so ten runs read at a glance */}
          <div className="min-w-0 overflow-y-auto" style={{ borderRight: '1px solid var(--border-subtle)', maxHeight: 640 }}>
          {sessions.error ? <div className="px-5 py-4"><ErrorBanner error={sessions.error} /></div>
          : sessions.isLoading ? <div className="px-5 py-4"><Skeleton rows={4} /></div>
          : rows.length === 0 ? (
            <EmptyState
              title={t('agent.noSessions')}
              description={t('agent.noSessionsHint')}
              icon={<IconClock width={18} height={18} />}
            />
          ) : (
            <ul className="divide-subtle">
              {rows.map((s) => {
                const active = s.id === openId
                return (
                  <li key={s.id}>
                    <button
                      type="button"
                      data-testid={`session-row-${s.id}`}
                      onClick={() => setOpenId(s.id)}
                      className="flex w-full flex-col gap-1 px-4 py-2.5 text-left transition-colors hover:bg-[var(--surface-hover)]"
                      style={{
                        background: active ? 'var(--brand-tint-soft)' : undefined,
                        boxShadow: active ? 'inset 2px 0 0 var(--brand-fg)' : undefined,
                      }}
                    >
                      <span className="flex items-center gap-2">
                        <span className="font-mono text-[12px] font-semibold tnum">#{s.id}</span>
                        <span className="min-w-0 flex-1 truncate font-mono text-[11.5px] secondary-text">{s.plugin}</span>
                        <Badge tone={statusTone(s.status)}>{statusLabel(s.status, t)}</Badge>
                      </span>
                      <span className="truncate text-[11.5px] muted">{s.task || '—'}</span>
                      <span className="flex items-center gap-3 font-mono text-[10.5px] muted tnum">
                        <span>{t('agent.usage.steps')} {s.budget.steps_used}/{fmtCap(s.budget.steps)}</span>
                        <span>{t('agent.usage.writes')} {s.budget.writes_used}/{fmtCap(s.budget.writes)}</span>
                      </span>
                    </button>
                  </li>
                )
              })}
            </ul>
          )}
          </div>

          <div className="min-w-0 p-5">
            {/* detail sub-header: the selected run gets its own row */}
            <div className="mb-4 flex flex-wrap items-center justify-between gap-x-3 gap-y-2">
              <div className="min-w-0">
                <div className="flex items-center gap-2 text-[13px] font-semibold tracking-wide">
                  {current ? (
                    <>
                      <span className="font-mono tnum">#{current.id}</span>
                      <span className="font-mono text-[12px] font-normal secondary-text">{current.plugin}</span>
                    </>
                  ) : t('agent.selectSession')}
                </div>
                <div className="mt-0.5 truncate text-[12.5px] muted">{current ? current.task || '—' : t('agent.selectSessionHint')}</div>
              </div>
              {current ? (
                <span className="flex items-center gap-2">
                  {current.status === 'running' ? <Badge tone="warning">{t('agent.running')}</Badge> : null}
                  <Button
                    size="sm"
                    variant="primary"
                    data-testid="plugin-example"
                    title={t('agent.example.dockHint')}
                    onClick={() => window.dispatchEvent(
                      new CustomEvent('ontogeny:agent-dock-open', { detail: { sessionId: current.id } }))}
                  >
                    {t('agent.example')}
                  </Button>
                  {/* manual end: open (idle), running (force-stop) or blocked --
                      a finished/exhausted session is already over, and any of
                      them can be re-driven afterwards */}
                  {['open', 'running', 'blocked_on_approval'].includes(current.status) ? (
                    <Button
                      size="sm"
                      data-testid="finish-session"
                      title={t('agent.finish.hint')}
                      disabled={finish.isPending}
                      onClick={() => finish.mutate(current.id)}
                    >
                      {t('agent.finish')}
                    </Button>
                  ) : null}
                  <Button
                    size="sm"
                    square
                    variant="subtle"
                    data-testid="delete-session"
                    title={t('agent.deleteSession')}
                    aria-label={t('agent.deleteSession')}
                    disabled={remove.isPending}
                    onClick={() => remove.mutate(current.id)}
                    icon={<IconTrash width={13} height={13} />}
                    style={{ color: 'var(--tone-danger-fg)' }}
                  />
                </span>
              ) : null}
            </div>
          {current?.status === 'blocked_on_approval' ? (
            <div className="mb-3">
              <Alert tone="warning" action={
                <Button size="sm" data-testid="go-approvals" onClick={() => nav('/agent/manage?tab=approvals')}>
                  {t('agent.goApprovals')}
                </Button>
              }>
                {t('agent.blocked')}
              </Alert>
            </div>
          ) : null}
          {!current ? (
            <EmptyState
              title={t('agent.selectSession')}
              description={t('agent.selectSessionHint')}
              icon={<IconClock width={18} height={18} />}
            />
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone={statusTone(current.status)}>{statusLabel(current.status, t)}</Badge>
                <Badge tone="info">{t(`agent.engine.${currentEngineKind ?? 'external-pull'}`)}</Badge>
                <span className="font-mono text-[11.5px] muted">{current.principal}</span>
              </div>

              <div className="mt-4 grid gap-4 lg:grid-cols-2">
                <KeyValue items={[
                  { key: t('agent.created'), value: fmtDate(current.created_at ?? null, lang) },
                  { key: t('agent.session.runCount'), value: String(current.run_count ?? 0) },
                  { key: t('agent.session.expires'), value: current.expires_at ? fmtDate(current.expires_at, lang) : t('agent.session.neverExpires') },
                ]} />
                <div className="flex flex-col gap-3">
                  {current.budget.steps > 0 ? (
                    <ProgressBar
                      value={current.budget.steps_used}
                      max={current.budget.steps}
                      tone="var(--color-brand-500)"
                      label={<><span>{t('agent.usage.steps')}</span><span className="tnum">{current.budget.steps_used}/{current.budget.steps}</span></>}
                    />
                  ) : (
                    <div className="flex items-center justify-between text-[12px]" data-testid="budget-steps-unlimited">
                      <span>{t('agent.usage.steps')}</span>
                      <span className="tnum">{current.budget.steps_used} / ∞</span>
                    </div>
                  )}
                  {current.budget.writes > 0 ? (
                    <ProgressBar
                      value={current.budget.writes_used}
                      max={current.budget.writes}
                      tone="var(--tone-warning-fg)"
                      label={<><span>{t('agent.usage.writes')}</span><span className="tnum">{current.budget.writes_used}/{current.budget.writes}</span></>}
                    />
                  ) : (
                    <div className="flex items-center justify-between text-[12px]" data-testid="budget-writes-unlimited">
                      <span>{t('agent.usage.writes')}</span>
                      <span className="tnum">{current.budget.writes_used} / ∞</span>
                    </div>
                  )}
                </div>
              </div>

              <div className="mt-5">
                <div className="mb-2 flex items-center justify-between">
                  <span className="ontogeny-label">{t('agent.steps')}</span>
                  <span className="text-[11.5px] muted tnum">{(current.steps ?? []).length}</span>
                </div>
                {(current.steps ?? []).length === 0 ? (
                  <EmptyState title={t('agent.noSteps')} description={t('agent.runHint')} icon={<IconPlay width={18} height={18} />} />
                ) : (
                  <StepTimeline steps={current.steps ?? []} />
                )}
              </div>

              {/* a round's conclusion (or error) shows no matter the current
                  status: the session stays open and re-drivable afterwards */}
              {current.result?.final ? (
                <div className="mt-4" data-testid="session-final">
                  <Alert tone="success" title={t('agent.round.final')}>{current.result.final}</Alert>
                </div>
              ) : current.result?.error ? (
                <div className="mt-4" data-testid="session-error">
                  <Alert tone="danger">{current.result.error}</Alert>
                </div>
              ) : null}
              {current.status === 'budget_exhausted' ? (
                <div className="mt-4"><Alert tone="danger">{t('agent.tryout.budget')}</Alert></div>
              ) : null}
            </>
          )}
          </div>
        </div>
      </Card>

    </div>
  )
}


/* --------------------------------------------------------------- timeline */

/** One run's decision process as a rail: sequence marker, the driver's own
 *  reasoning for the step, the tool it chose, its outcome and latency, and
 *  whatever the engine produced (revision / approval ref).
 *
 *  The reasoning line is the point: a tool-call list alone says *what* happened,
 *  not *why*, and "why" is what a reviewer (or the human at the approval gate)
 *  actually needs. Drivers that supply no thought simply render without it. */
export function StepTimeline({ steps }: { steps: import('../../api/types').AgentStep[] }) {
  // direction 3: one session may be driven many times -- group the steps by
  // their run and make every group collapsible (newest expanded by default)
  const runs = useMemo(() => {
    const groups = new Map<number, import('../../api/types').AgentStep[]>()
    for (const s of steps) {
      const k = s.run_no && s.run_no > 0 ? s.run_no : 1
      if (!groups.has(k)) groups.set(k, [])
      groups.get(k)!.push(s)
    }
    return [...groups.entries()].sort((a, b) => a[0] - b[0])
  }, [steps])

  if (runs.length <= 1) return <StepList steps={steps} />
  return (
    <div className="flex flex-col gap-2">
      {runs.map(([runNo, group], i) => (
        <RunGroup key={runNo} runNo={runNo} steps={group} defaultOpen={i === runs.length - 1} />
      ))}
    </div>
  )
}

function RunGroup({ runNo, steps, defaultOpen }: {
  runNo: number
  steps: import('../../api/types').AgentStep[]
  defaultOpen: boolean
}) {
  const { t } = useI18n()
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="rounded-lg" style={{ border: '1px solid var(--border-subtle)', background: 'var(--surface-card)' }}>
      <button type="button" data-testid={`run-group-${runNo}`} aria-expanded={open}
              onClick={() => setOpen((o) => !o)}
              className="flex w-full items-center gap-2 px-3 py-2 text-left transition-colors hover:bg-[var(--surface-hover)] rounded-lg">
        <span className="muted text-[10.5px]">{open ? '▾' : '▸'}</span>
        <Badge tone="info" mono>{t('agent.runs.nth', { n: runNo })}</Badge>
        <span className="text-[11px] muted tnum">{t('agent.runs.steps', { n: steps.length })}</span>
      </button>
      {open ? <div className="px-2 pb-2"><StepList steps={steps} /></div> : null}
    </div>
  )
}

function StepList({ steps }: { steps: import('../../api/types').AgentStep[] }) {
  const { t } = useI18n()
  return (
    <ol className="relative flex flex-col gap-2">
      {steps.map((s, i) => {
        const tone = outcomeTone(s.outcome)
        const color = tone === 'success' ? 'var(--tone-success-fg)' : tone === 'warning' ? 'var(--tone-warning-fg)' : tone === 'danger' ? 'var(--tone-danger-fg)' : 'var(--text-muted)'
        return (
          <li key={s.seq} className="relative flex items-start gap-3">
            <span className="relative flex w-6 shrink-0 justify-center">
              {i < steps.length - 1 ? (
                <span className="absolute top-6 bottom-[-8px] w-px" style={{ background: 'var(--border-subtle)' }} />
              ) : null}
              <span
                className="z-10 grid size-6 place-items-center rounded-full text-[10.5px] font-semibold tnum"
                style={{ background: `${color}1a`, color, boxShadow: `inset 0 0 0 1px ${color}33` }}
              >
                {s.seq}
              </span>
            </span>
            <div
              className="min-w-0 flex-1 rounded-lg px-3 py-2"
              style={{ background: 'var(--surface-card)', border: '1px solid var(--border-subtle)' }}
            >
              {s.thought ? (
                <p
                  className="mb-2 flex gap-2 whitespace-pre-wrap text-[12px] leading-relaxed secondary-text"
                  data-testid={`step-thought-${s.seq}`}
                >
                  <span className="mt-[3px] shrink-0" style={{ color: 'var(--tone-violet-fg)' }} aria-hidden="true">
                    <IconSpark width={12} height={12} />
                  </span>
                  <span className="min-w-0">{s.thought}</span>
                </p>
              ) : null}
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className="font-mono text-[12px] font-medium">{s.tool}</span>
                <Badge tone={tone}>
                  {t(`agent.outcome.${s.outcome}`) !== `agent.outcome.${s.outcome}` ? t(`agent.outcome.${s.outcome}`) : s.outcome}
                </Badge>
                <span className="ml-auto font-mono text-[11px] muted tnum">{s.latency_ms ?? 0}ms</span>
              </div>
              {s.revision_id || s.approval_id ? (
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {s.revision_id ? <code className="ontogeny-code">rev:{s.revision_id}</code> : null}
                  {s.approval_id ? <code className="ontogeny-code">appr:{s.approval_id}</code> : null}
                </div>
              ) : null}
            </div>
          </li>
        )
      })}
    </ol>
  )
}

/* -------------------------------------------------------------- approvals */

export function ApprovalsPanel() {
  const { t, lang } = useI18n()
  const qc = useQueryClient()
  const pending = useQuery({
    queryKey: ['agent-approvals', 'pending'],
    queryFn: () => apiClient.agentApprovals('pending'),
    refetchInterval: 5000,
  })
  // direction 1: the audit trail lives here too — everything past its gate
  const decided = useQuery({
    queryKey: ['agent-approvals', 'decided'],
    queryFn: () => apiClient.agentApprovals('decided'),
    refetchInterval: 10000,
  })
  // direction 1: an errored decision opens a POPUP and the row keeps its
  // server-side status — the UI never invents an outcome
  const [decisionError, setDecisionError] = useState<{ id: number; message: string } | null>(null)
  const decide = useMutation({
    mutationFn: ({ id, decision }: { id: number; decision: 'approved' | 'rejected' }) =>
      apiClient.agentDecide(id, decision),
    onSuccess: (_r, vars) => {
      setDecisionError(null)
      qc.invalidateQueries({ queryKey: ['agent-approvals'] }) // queue + audit trail
      // the session the write belonged to flips blocked_on_approval -> open,
      // so its live status must refresh without waiting for the next poll
      qc.invalidateQueries({ queryKey: ['agent-sessions'] })
      qc.invalidateQueries({ queryKey: ['agent-session'] })
      qc.invalidateQueries({ queryKey: keys.agentSession(vars.id) }).catch(() => undefined)
    },
    onError: (error, vars) => {
      setDecisionError({
        id: vars.id,
        message: (error as { message?: string }).message || String(error),
      })
    },
  })
  const remove = useMutation({
    mutationFn: (id: number) => apiClient.agentDeleteApproval(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['agent-approvals'] }),
  })

  const rows = pending.data?.approvals ?? []
  const done = decided.data?.approvals ?? []
  const plugins = new Set(rows.map((a) => a.plugin))

  const decidedTone = (s: string): BadgeTone =>
    s === 'executed' || s === 'approved' ? 'success'
      : s === 'failed' ? 'danger'
        : s === 'rejected' ? 'neutral' : 'warning'

  return (
    <div className="flex flex-col gap-5">
      {pending.error ? <ErrorBanner error={pending.error} /> : null}
      {decided.error ? <ErrorBanner error={decided.error} /> : null}

      {/* one surface: the human gate as a decision list — every row is one
          pending write with its context and its two verdict buttons */}
      <Card
        padded={false}
        bare
        description={t('agent.awaitingHumanHint')}
        actions={
          <span className="flex items-center gap-1.5">
            <Badge tone={rows.length ? 'warning' : 'success'} mono>{rows.length}</Badge>
            {plugins.size ? <Badge tone="neutral" mono>{plugins.size} {t('agent.stat.pluginsWaiting')}</Badge> : null}
          </span>
        }
      >
        {rows.length === 0 && !pending.isLoading && !pending.error ? (
          <div className="px-5 pb-5">
            <EmptyState
              title={t('agent.noApprovals')}
              description={t('agent.approvalsEmptyHint')}
              icon={<IconShield width={18} height={18} />}
            />
          </div>
        ) : pending.isLoading ? (
          <div className="px-5 pb-5"><Skeleton rows={3} /></div>
        ) : (
          <ul className="divide-subtle">
            {rows.map((a) => (
              <li key={a.id} className="flex flex-col gap-2.5 px-5 py-4">
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className="grid size-6 shrink-0 place-items-center rounded-md"
                    style={{ background: 'var(--tone-warning-bg)', color: 'var(--tone-warning-fg)' }}
                    title={t('agent.awaitingHuman')}
                  >
                    <IconShield width={13} height={13} />
                  </span>
                  <span className="font-mono text-[13px] font-semibold">{a.action}</span>
                  <Badge tone="neutral" mono>{a.plugin}</Badge>
                  <span className="font-mono text-[11.5px] muted">#{a.session_id}</span>
                  <span className="ml-auto flex shrink-0 gap-2">
                    <Button
                      size="sm"
                      variant="primary"
                      data-testid={`approve-${a.id}`}
                      disabled={decide.isPending}
                      onClick={() => decide.mutate({ id: a.id, decision: 'approved' })}
                    >
                      {t('agent.approve')}
                    </Button>
                    <Button
                      size="sm"
                      data-testid={`reject-${a.id}`}
                      disabled={decide.isPending}
                      onClick={() => decide.mutate({ id: a.id, decision: 'rejected' })}
                    >
                      {t('agent.reject')}
                    </Button>
                    <Button
                      size="sm"
                      square
                      variant="subtle"
                      data-testid={`delete-approval-${a.id}`}
                      title={t('agent.deleteApproval')}
                      aria-label={t('agent.deleteApproval')}
                      disabled={remove.isPending}
                      onClick={() => remove.mutate(a.id)}
                      icon={<IconTrash width={13} height={13} />}
                      style={{ color: 'var(--tone-danger-fg)' }}
                    />
                  </span>
                </div>
                <div className="flex flex-wrap gap-x-5 gap-y-1 text-[12px]">
                  <span className="min-w-0">
                    <span className="muted">{t('agent.target')}: </span>
                    <code className="ontogeny-code">{a.target_id ?? '—'}</code>
                  </span>
                  {a.rationale ? (
                    <span className="min-w-0 flex-1 basis-64">
                      <span className="muted">{t('agent.rationale')}: </span>
                      <span className="secondary-text">{a.rationale}</span>
                    </span>
                  ) : null}
                </div>
                <div>
                  <div className="ontogeny-label mb-1">{t('agent.parameters')}</div>
                  <JsonView value={a.parameters} />
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {/* direction 1: the audit half of the same module — decided approvals
          stay visible with who decided and what the outcome was */}
      <Card
        padded={false}
        bare
        description={t('agent.approvals.decidedHint')}
        actions={<Badge tone="neutral" mono>{done.length}</Badge>}
      >
        {done.length === 0 && !decided.isLoading && !decided.error ? (
          <div className="px-5 pb-5">
            <EmptyState title={t('agent.approvals.emptyDecided')} icon={<IconShield width={18} height={18} />} />
          </div>
        ) : decided.isLoading ? (
          <div className="px-5 pb-5"><Skeleton rows={2} /></div>
        ) : (
          <ul className="divide-subtle">
            {done.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center gap-2 px-5 py-3">
                <Badge tone={decidedTone(a.status)}>{t(`proposal.${a.status}`) !== `proposal.${a.status}` ? t(`proposal.${a.status}`) : a.status}</Badge>
                <span className="font-mono text-[12.5px] font-medium">{a.action}</span>
                <Badge tone="neutral" mono>{a.plugin}</Badge>
                <span className="font-mono text-[11.5px] muted">#{a.session_id}</span>
                <span className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-0.5 text-[11.5px] muted">
                  {a.decided_by ? <span>{t('agent.approvals.decidedBy')} <code className="ontogeny-code">{a.decided_by}</code></span> : null}
                  {a.decided_at ? <span className="tnum">{fmtDate(a.decided_at, lang)}</span> : null}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      {/* direction 1: an errored approval is a POPUP — the row keeps its
          server-side status, nothing is optimistically rewritten */}
      {decisionError ? createPortal(
        <div className="fixed inset-0 z-50 grid place-items-center p-4" style={{ background: 'rgba(0,0,0,.45)' }}>
          <div role="alertdialog" aria-modal="true" data-testid="approval-error-dialog"
               className="ontogeny-card ontogeny-modal w-full max-w-md p-5">
            <div className="flex items-start gap-3">
              <span className="grid size-8 shrink-0 place-items-center rounded-lg"
                    style={{ background: 'var(--tone-danger-bg)', color: 'var(--tone-danger-fg)' }}>
                <IconShield width={15} height={15} />
              </span>
              <div className="min-w-0">
                <h2 className="text-[14px] font-semibold">{t('agent.approvals.errorTitle')}</h2>
                <p className="mt-1 text-[12.5px] muted">{t('agent.approvals.errorHint')}</p>
                <p className="mt-2 break-all rounded-lg p-2.5 font-mono text-[11.5px]"
                   style={{ background: 'var(--surface-sunken)' }}>
                  #{decisionError.id}: {decisionError.message}
                </p>
              </div>
            </div>
            <div className="mt-4 flex justify-end">
              <Button size="sm" data-testid="approval-error-close" onClick={() => setDecisionError(null)}>
                {t('common.close')}
              </Button>
            </div>
          </div>
        </div>,
        document.body,
      ) : null}
    </div>
  )
}
