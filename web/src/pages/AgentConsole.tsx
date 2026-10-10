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
 * Agent console: ONE conversation, three ways to fill it.
 *
 * The page is a single dialogue surface — a title, then a scrolling transcript
 * with a composer docked at its bottom. The composer's mode switch picks what
 * the input *does*:
 *
 * - RSI提案    ontology-grounded chat that also drafts a schema mutation (the
 *              entry to the self-evolution loop; a human still promotes it
 *              through the governance loop);
 * - ontology问答  the same chat, answers only, grounded on the snapshot;
 * - agent模式  hands the task to a real AgentPlugin session. The picker left of
 *              the input chooses an existing session (persisted in the 会话
 *              module) or opens a new one; the engine's step trace streams into
 *              the transcript, through the same budget/catalog/approval gates
 *              an external agent goes through.
 *
 * Sessions, pending writes and plugins are their own page under /agent/manage,
 * in the sidebar's agent-management module.
 *
 * Since the agent became a floating dock, the conversation itself lives in
 * `AgentConsoleBody` and is rendered inside `AgentDock`'s dialog; `AgentConsole`
 * is only the route-level frame (plus the `h1` a page owes the document).
 */
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import { keys, useMeta } from '../api/queries'
import { useI18n } from '../i18n'
import { Alert, Badge, Button, Card, Page } from '../components/ui'
import { ErrorBanner } from '../components/ErrorBanner'
import { Markdown } from '../components/Markdown'
import { MutationDiff } from '../components/MutationDiff'
import { StepTimeline } from './agent/panels'
import { statusTone } from './agent/tone'
import { IconChat, IconPlay, IconRefresh, IconRoute, IconSend, IconSpark, IconShield } from '../components/icons'
import type { Mutation } from '../api/types'

type Mode = 'propose' | 'qa' | 'agent'

const MODES: Mode[] = ['agent', 'qa', 'propose']

/** direction 4: agent-mode starter questions. Every one is answerable by the
 *  shipped plugins' own catalogue (search / call functions) -- verified live
 *  against the manufacturing domain, not aspirational copy. */
const AGENT_SUGGESTIONS: { zh: string; en: string }[] = [
  { zh: '盘点当前的生产订单，并给出一句优先级建议',
    en: 'Inventory production orders and give a one-line priority recommendation' },
  { zh: '检查产品 P-100、数量 5 的物料可用性',
    en: 'Check material availability for product P-100, qty 5' },
  { zh: '列出所有 ACTIVE 状态的工作中心及其产能',
    en: 'List all ACTIVE work centres and their capacity' },
]

interface ChatItem {
  id: number
  role: 'user' | 'assistant'
  content: string
  thinking?: string | null
  proposals?: Mutation[] | null
}

interface RunItem {
  id: number
  sessionId: number
  plugin: string
  task: string
}

type Item = ({ kind: 'msg' } & ChatItem) | ({ kind: 'run' } & RunItem)

let nextId = 1
const uid = () => nextId++

export function AgentConsole() {
  return (
    <Page fill testId="agent-console">
      <h1 className="sr-only">{useI18n().t('agent.title')}</h1>
      <AgentConsoleBody />
    </Page>
  )
}

/** The conversation surface itself, reusable off the page.
 *
 * The agent is a floating dock (see components/AgentDock.tsx), so the same
 * transcript, mode switch and composer has to render inside a dialog as well as
 * on a route — one implementation, two frames. Every dependency is a hook
 * (React Query, i18n, the router), so nothing has to be threaded through. */
export function AgentConsoleBody({ className, flush = false, presetSessionId = null }: {
  className?: string
  flush?: boolean
  /** when the dock is summoned for a specific session, the composer
   *  auto-selects it and its run card appears in the transcript */
  presetSessionId?: number | null
}) {
  const { t, lang } = useI18n()
  const meta = useMeta()
  const qc = useQueryClient()
  const [mode, setMode] = useState<Mode>('agent')
  // one transcript per mode, so switching never mixes an agent trace into a Q&A
  const [logs, setLogs] = useState<Record<Mode, Item[]>>({ propose: [], qa: [], agent: [] })
  const [input, setInput] = useState('')
  const [target, setTarget] = useState('')
  const logRef = useRef<HTMLDivElement>(null)

  const plugins = useQuery({ queryKey: ['agent-plugins'], queryFn: apiClient.agentPlugins })
  const declared = plugins.data?.plugins ?? []
  const sessions = useQuery({
    queryKey: keys.agentSessions(''),
    queryFn: () => apiClient.agentSessions(),
    refetchInterval: 8000,
  })
  const rows = sessions.data?.sessions ?? []

  // the summoned-with-a-session flow: pick it in the composer (bottom of the
  // dock) and surface its run card in the transcript
  useEffect(() => {
    if (!presetSessionId) return
    setMode('agent')
    setTarget(`s:${presetSessionId}`)
    setLogs((prev) => {
      if (prev.agent.some((it) => it.kind === 'run' && it.sessionId === presetSessionId)) return prev
      const known = sessions.data?.sessions.find((s) => s.id === presetSessionId)
      return { ...prev, agent: [...prev.agent, {
        kind: 'run' as const, id: uid(), sessionId: presetSessionId,
        plugin: known?.plugin ?? '', task: known?.task ?? '',
      }] }
    })
  }, [presetSessionId, sessions.data])

  const push = (m: Mode, ...items: Item[]) =>
    setLogs((prev) => ({ ...prev, [m]: [...prev[m], ...items] }))
  const scrollDown = () =>
    requestAnimationFrame(() => logRef.current?.scrollTo({ top: 1e9, behavior: 'smooth' }))

  const chat = useMutation({
    mutationFn: async (payload: { history: Array<{ role: string; content: string }>; text: string; propose: boolean; mode: Mode }) =>
      apiClient.assistantChat([...payload.history, { role: 'user', content: payload.text }], payload.propose),
    // the reply lands in the transcript that sent it, even if the user has
    // switched modes (or is looking at another one) by the time it arrives
    onSuccess: (reply, payload) => {
      push(payload.mode, {
        kind: 'msg', id: uid(), role: 'assistant', content: reply.content,
        thinking: reply.thinking ?? null, proposals: (reply.proposals as Mutation[]) ?? null,
      })
      setInput('')
      scrollDown()
    },
  })

  const openRun = useMutation({
    mutationFn: async ({ task, target: chosen }: { task: string; target: string }) => {
      if (chosen.startsWith('new:')) {
        const plugin = chosen.slice(4)
        const s = await apiClient.agentOpenSession(plugin, task)
        push('agent', { kind: 'run', id: uid(), sessionId: s.id, plugin: s.plugin, task: s.task })
        await apiClient.agentRun(s.id)
        return
      }
      const id = Number(chosen.slice(2))
      const known = rows.find((s) => s.id === id)
      if (!known) return
      if (!logs.agent.some((it) => it.kind === 'run' && it.sessionId === id)) {
        push('agent', { kind: 'run', id: uid(), sessionId: known.id, plugin: known.plugin, task: known.task })
      }
      // any status can take this drive: open/blocked continue, running is a
      // no-op (the engine already owns it), and a finished/exhausted session
      // is re-opened by the run endpoint for this new instruction
      await apiClient.agentRun(id, task)
    },
    onSuccess: () => {
      setInput('')
      scrollDown()
      qc.invalidateQueries({ queryKey: ['agent-sessions'] })
      // the drive is dispatched: refresh every mounted run card so its status
      // flips to `running` (and the thinking indicator) without waiting a tick
      qc.invalidateQueries({ queryKey: ['agent-session'] })
    },
  })

  // default the agent target to the first plugin as soon as the catalogue lands
  const targetOptions = [
    ...declared.map((p) => ({ value: `new:${p.name}`, label: t('agent.composer.newSession', { plugin: p.name }) })),
    ...rows.map((s) => ({ value: `s:${s.id}`, label: t('agent.composer.session', { id: s.id, task: s.task || '—' }) })),
  ]
  const effectiveTarget = target || targetOptions[0]?.value || ''

  const suggestions = mode === 'agent'
    ? AGENT_SUGGESTIONS.map((x) => (lang === 'zh' ? x.zh : x.en))
    : [t('assistant.suggest1'), t('assistant.suggest2'), t('assistant.suggest3')]
  const items = logs[mode]

  const send = () => {
    if (mode === 'agent') {
      // the composer IS the command input: its text is THIS run's instruction
      // (for a new session it becomes the task; for an existing one it is the
      // instruction of this drive) -- empty input has nothing to execute
      if (!effectiveTarget || !input.trim() || openRun.isPending) return
      openRun.mutate({ task: input.trim(), target: effectiveTarget })
      return
    }
    const text = input.trim()
    if (!text || chat.isPending) return
    const history = logs[mode]
      .filter((it): it is { kind: 'msg' } & ChatItem => it.kind === 'msg')
      .map((m) => ({ role: m.role, content: m.content }))
    push(mode, { kind: 'msg', id: uid(), role: 'user', content: text })
    setInput('')
    scrollDown()
    chat.mutate({ history, text, propose: mode === 'propose', mode })
  }

  // `busy` gates the composer globally (never two requests at once); the
  // indicator only shows in the transcript the request belongs to
  const busy = chat.isPending || openRun.isPending
  const pendingHere = (chat.isPending && chat.variables?.mode === mode) || (mode === 'agent' && openRun.isPending)

  return (
    <div className={['flex h-full min-h-0 flex-col gap-3', className].filter(Boolean).join(' ')} data-testid="agent-console">
      {plugins.error ? <ErrorBanner error={plugins.error} /> : null}

      <Card
        bare={flush}
        padded={false}
        className="flex min-h-0 flex-1 flex-col"
        bodyClassName="flex min-h-0 flex-1 flex-col"
        // direction 1: in the dock the gray toolbar row is gone -- its badge,
        // sessions link and refresh live in the dock's header row instead
        toolbar={flush ? undefined : (
          <>
            <Badge tone={declared.length ? 'brand' : 'neutral'}>{t('agent.plugins')}: {declared.length}</Badge>
            <span className="ml-auto flex items-center gap-2">
              <Link className="ontogeny-btn-ghost ontogeny-btn-sm" to="/agent/manage">
                <IconRoute width={13} height={13} />
                {t('agent.sessions')}
              </Link>
              <Button
                size="sm"
                icon={<IconRefresh width={14} height={14} />}
                onClick={() => { plugins.refetch(); sessions.refetch() }}
              >
                {t('common.refresh')}
              </Button>
            </span>
          </>
        )}
      >
        <div ref={logRef} className="min-h-0 flex-1 space-y-4 overflow-y-auto p-5" data-testid="chat-log">
          {items.length === 0 ? (
            <Welcome mode={mode} suggestions={suggestions} onPick={setInput} />
          ) : (
            items.map((it) => (it.kind === 'run'
              ? <AgentRunCard key={it.id} sessionId={it.sessionId} plugin={it.plugin} task={it.task} />
              : <Bubble key={it.id} item={it} />))
          )}
          {pendingHere ? (
            <div className="flex items-center gap-2.5" data-testid="chat-pending">
              <span className="grid size-7 shrink-0 place-items-center rounded-lg" style={{ background: 'var(--brand-tint-soft)', color: 'var(--brand-fg)' }}>
                <IconChat width={14} height={14} />
              </span>
              <span className="text-[12.5px] muted">
                {mode === 'agent' ? t('agent.composer.starting') : t('assistant.sending')}
              </span>
            </div>
          ) : null}
        </div>

        <form
          className="flex shrink-0 flex-col gap-2.5 px-4 pt-2.5 pb-3"
          style={{ background: 'var(--surface-card)' }}
          onSubmit={(e) => { e.preventDefault(); send() }}
        >
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            {/* Compact neutral mode switch: no track, no outer border; the
                active tab is a small raised black/white chip, so the composer
                stays quiet under the transcript. */}
            <div role="tablist" aria-label={t('agent.composer.mode')} className="flex items-center gap-1">
              {MODES.map((m) => {
                const active = m === mode
                return (
                  <button
                    key={m}
                    type="button"
                    role="tab"
                    aria-selected={active}
                    data-testid={`mode-${m}`}
                    title={t(`agent.mode.${m}Hint`)}
                    onClick={() => setMode(m)}
                    className="flex items-center gap-1 rounded-md px-2.5 py-1 text-[11.5px] transition-all duration-150"
                    style={active
                      ? {
                        background: 'var(--text-primary)',
                        color: 'var(--surface-card)',
                        fontWeight: 600,
                        boxShadow: '0 1px 2px rgba(16, 24, 40, 0.18), 0 2px 4px rgba(16, 24, 40, 0.08)',
                        transform: 'translateY(-0.5px)',
                      }
                      : { background: 'transparent', color: 'var(--text-muted)', fontWeight: 500 }}
                  >
                    {m === 'propose' ? <IconSpark width={12} height={12} />
                      : m === 'qa' ? <IconChat width={12} height={12} />
                      : <IconPlay width={12} height={12} />}
                    {t(`agent.mode.${m}`)}
                  </button>
                )
              })}
            </div>
            <span className="min-w-0 flex-1 truncate text-[11.5px] muted">{t(`agent.mode.${mode}Hint`)}</span>
            {meta.data ? <Badge tone="brand" mono>{meta.data.package}</Badge> : null}
          </div>

          <div className="flex items-stretch gap-2">
            {mode === 'agent' ? (
              <select
                aria-label={t('agent.composer.session')}
                className="ontogeny-input w-60 shrink-0 font-mono text-[12px]"
                data-testid="agent-session-picker"
                value={effectiveTarget}
                onChange={(e) => {
                  setTarget(e.target.value)
                  // choosing an existing run shows it straight away
                  if (e.target.value.startsWith('s:')) {
                    const id = Number(e.target.value.slice(2))
                    const known = rows.find((s) => s.id === id)
                    if (known && !logs.agent.some((it) => it.kind === 'run' && it.sessionId === id)) {
                      push('agent', { kind: 'run', id: uid(), sessionId: known.id, plugin: known.plugin, task: known.task })
                      scrollDown()
                    }
                  }
                }}
              >
                {targetOptions.length === 0 ? <option value="">{t('agent.composer.noPlugin')}</option> : null}
                {targetOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            ) : null}
            <input
              className="ontogeny-input"
              placeholder={mode === 'agent' ? t('agent.composer.agentPlaceholder') : t('assistant.placeholder')}
              value={input}
              data-testid="chat-input"
              onChange={(e) => setInput(e.target.value)}
            />
            <Button
              variant="primary"
              type="submit"
              data-testid="chat-send"
              square
              aria-label={mode === 'agent' ? t('agent.composer.run') : t('assistant.send')}
              title={mode === 'agent' ? t('agent.composer.run') : t('assistant.send')}
              disabled={busy || !input.trim() || (mode === 'agent' ? !effectiveTarget : false)}
              icon={<IconSend width={15} height={15} />}
            />
          </div>
        </form>
      </Card>

      {chat.error ? <ErrorBanner error={chat.error} hint={t('assistant.notConfigured')} /> : null}
      {openRun.error ? <ErrorBanner error={openRun.error} hint={t('agent.llmMissing')} /> : null}
    </div>
  )
}

/* --------------------------------------------------------------- transcript */

function Welcome({ mode, suggestions, onPick }: {
  mode: Mode
  suggestions: string[]
  onPick: (text: string) => void
}) {
  const { t } = useI18n()
  return (
    <div className="flex h-full flex-col items-center justify-center px-4 text-center">
      <span
        className="grid size-12 place-items-center rounded-2xl"
        style={{ background: 'linear-gradient(150deg, var(--brand-tint-soft), var(--tone-violet-bg))', color: 'var(--brand-fg)' }}
      >
        {mode === 'agent' ? <IconPlay width={22} height={22} /> : <IconChat width={22} height={22} />}
      </span>
      <p className="mt-4 text-[14px] font-semibold">{t(`agent.welcome.${mode}Title`)}</p>
      <p className="mt-1 max-w-lg text-[12.5px] leading-relaxed muted">
        {t(`agent.welcome.${mode}`)}
      </p>
      <div className="mt-5 grid w-full max-w-2xl gap-2 sm:grid-cols-3" data-testid="welcome-suggestions">
        {suggestions.map((s) => (
          <button key={s} type="button"
                  className="rounded-xl px-3.5 py-3 text-left text-[12px] leading-relaxed transition-colors hover:bg-[var(--surface-hover)]"
                  style={{ background: 'var(--surface-card)', border: '1px solid var(--border-subtle)' }}
                  onClick={() => onPick(s)}>
            {s}
          </button>
        ))}
      </div>
    </div>
  )
}

function Bubble({ item }: { item: ChatItem }) {
  const { t } = useI18n()
  const user = item.role === 'user'
  return (
    <div className={`flex items-start gap-2.5 ${user ? 'justify-end' : 'justify-start'}`}>
      {!user ? (
        <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg" style={{ background: 'var(--brand-tint-soft)', color: 'var(--brand-fg)' }}>
          <IconChat width={14} height={14} />
        </span>
      ) : null}
      <div
        className="max-w-[82%] rounded-2xl px-4 py-2.5 text-[13px] leading-[1.75]"
        style={user
          ? { background: 'var(--color-brand-500)', color: '#fff', borderTopRightRadius: 6 }
          : { background: 'var(--surface-sunken)', border: '1px solid var(--border-subtle)', borderTopLeftRadius: 6 }}
      >
        {/* the reasoning sits ABOVE the answer: read the trace first if you
            want it, the reply itself stays the last thing on the card */}
        {item.thinking ? (
          <details className="mb-2 text-[11.5px] opacity-70">
            <summary className="cursor-pointer">{t('assistant.thinking')}</summary>
            <div className="mt-1 whitespace-pre-wrap font-mono">{item.thinking}</div>
          </details>
        ) : null}
        {user ? <span className="whitespace-pre-wrap">{item.content}</span> : <Markdown text={item.content} />}
        {item.proposals?.length ? (
          <div className="mt-3">
            <div className="ontogeny-label">{t('assistant.draft')}</div>
            <MutationDiff mutations={item.proposals} />
            <p className="mt-2 text-[11.5px] muted">{t('assistant.draftHint')}</p>
          </div>
        ) : null}
      </div>
    </div>
  )
}

/** One agent session inside the transcript: live step trace + the round's
 *  conclusion. The run itself lives on the server (会话 module), so the card is
 *  a *view* — reopening the page and picking the session brings the same trace
 *  back. The session is a continuing conversation: a final answer ends the
 *  round, not the session (budget threshold or the 结束会话 button ends that),
 *  and an ended session can be re-driven at any time. */
function AgentRunCard({ sessionId, plugin, task }: { sessionId: number; plugin: string; task: string }) {
  const { t } = useI18n()
  const qc = useQueryClient()
  const session = useQuery({
    queryKey: keys.agentSession(sessionId),
    queryFn: () => apiClient.agentSession(sessionId),
    // poll while a drive is live; keep a slow poll while `open` because a
    // drive can start (and even finish) between ticks -- stopping on `open`
    // would miss the round's conclusion landing right after `running`
    refetchInterval: (q) => {
      const s = q.state.data as import('../api/types').AgentSession | undefined
      if (!s) return 2000
      if (s.status === 'running') return 2000
      return s.status === 'open' ? 6000 : false
    },
  })
  const finish = useMutation({
    mutationFn: () => apiClient.agentFinish(sessionId, { closed_by: 'dock' }),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.agentSession(sessionId) }),
  })
  const s = session.data
  const steps = s?.steps ?? []
  const canFinish = s != null && ['open', 'running', 'blocked_on_approval'].includes(s.status)

  return (
    <div className="flex items-start gap-2.5">
      <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg" style={{ background: 'var(--tone-violet-bg)', color: 'var(--tone-violet-fg)' }}>
        <IconSpark width={14} height={14} />
      </span>
      <div
        className="min-w-0 flex-1 rounded-2xl p-3.5"
        style={{ background: 'var(--surface-sunken)', border: '1px solid var(--border-subtle)', borderTopLeftRadius: 6 }}
        data-testid={`agent-run-${sessionId}`}
      >
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={s ? statusTone(s.status) : 'neutral'}>
            {s ? (t(`agent.status.${s.status}`) !== `agent.status.${s.status}` ? t(`agent.status.${s.status}`) : s.status) : '…'}
          </Badge>
          <span className="font-mono text-[11.5px] muted">{plugin}</span>
          <Link className="ontogeny-link text-[11.5px]" to="/agent/manage">#{sessionId} →</Link>
          {canFinish ? (
            <Button
              size="sm"
              variant="subtle"
              data-testid={`finish-session-${sessionId}`}
              title={t('agent.finish.hint')}
              disabled={finish.isPending}
              onClick={() => finish.mutate()}
            >
              {t('agent.finish')}
            </Button>
          ) : null}
          {s ? (
            <span className="ml-auto font-mono text-[11px] muted tnum">
              {s.budget.steps_used}/{s.budget.steps} · {s.budget.writes_used}/{s.budget.writes}
            </span>
          ) : null}
        </div>
        <p className="mt-2 text-[12.5px] secondary-text">{task}</p>

        <div className="mt-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="ontogeny-label" style={{ marginBottom: 0 }}>{t('agent.trace')}</span>
            <span className="text-[11px] muted tnum">{steps.length}</span>
          </div>
          {steps.length === 0 ? (
            <p className="text-[12px] muted">
              {s && s.status !== 'running' ? t('agent.noSteps') : t('agent.tryout.working')}
            </p>
          ) : (
            <StepTimeline steps={steps} />
          )}
          {/* while the engine owns the session it is almost always inside an
              LLM call: this row is the visible proof the drive is alive */}
          {s?.status === 'running' ? (
            <div className="mt-2.5 flex items-center gap-2.5" data-testid="agent-thinking">
              <span className="flex items-center gap-1" aria-hidden="true">
                <span className="size-1.5 animate-pulse rounded-full" style={{ background: 'var(--tone-violet-fg)' }} />
                <span className="size-1.5 animate-pulse rounded-full" style={{ background: 'var(--tone-violet-fg)', animationDelay: '200ms' }} />
                <span className="size-1.5 animate-pulse rounded-full" style={{ background: 'var(--tone-violet-fg)', animationDelay: '400ms' }} />
              </span>
              <span className="text-[12px] muted">{t('agent.thinking')}</span>
            </div>
          ) : null}
        </div>

        {/* a round's conclusion (or error) shows no matter the current status:
            the session stays open afterwards, ready for the next instruction */}
        {s?.result?.final ? (
          <div className="mt-3 flex flex-col gap-2">
            {/* the round's reasoning collapses ABOVE the conclusion it
                produced -- the final answer stays last and unwrapped */}
            {s.result.thought ? (
              <details
                className="rounded-lg px-2.5 py-1.5 text-[12px] leading-relaxed secondary-text"
                style={{ background: 'var(--surface-card)', border: '1px dashed var(--border-strong)' }}
                data-testid="run-final-thought"
              >
                <summary className="flex cursor-pointer items-center gap-2 font-semibold" style={{ color: 'var(--tone-violet-fg)' }}>
                  <IconSpark width={12} height={12} />
                  {t('assistant.thinking')}
                </summary>
                <p className="mt-1.5 whitespace-pre-wrap">{s.result.thought}</p>
              </details>
            ) : null}
            <Alert tone="success" title={t('agent.round.final')}>
              <Markdown text={s.result.final} />
            </Alert>
          </div>
        ) : s?.result?.error ? (
          <div className="mt-3"><Alert tone="danger">{s.result.error}</Alert></div>
        ) : null}
        {s?.status === 'budget_exhausted' ? (
          <div className="mt-3"><Alert tone="danger">{t('agent.tryout.budget')}</Alert></div>
        ) : null}
        {s?.status === 'blocked_on_approval' ? (
          <div className="mt-3">
            <Alert
              tone="warning"
              action={<Link className="ontogeny-btn-ghost ontogeny-btn-sm" to="/agent/manage?tab=approvals"><IconShield width={13} height={13} />{t('agent.goApprovals')}</Link>}
            >
              {t('agent.blocked')}
            </Alert>
          </div>
        ) : null}
      </div>
    </div>
  )
}
