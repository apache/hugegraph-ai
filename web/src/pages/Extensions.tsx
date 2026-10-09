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
import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { apiClient } from '../api/client'
import { keys } from '../api/queries'
import { useI18n } from '../i18n'
import { Alert, Badge, Button, Card, Skeleton, Strip, TONES, toneSurface } from '../components/ui'
import { ErrorBanner } from '../components/ErrorBanner'
import {
  IconChat, IconCog, IconLayers, IconNetwork,
} from '../components/icons'
import type { BadgeTone } from '../components/ui'

const STATUS_TONE: Record<string, BadgeTone> = {
  loaded: 'success',
  disabled: 'neutral',
  skipped: 'warning',
  error: 'danger',
  discovered: 'neutral',
}

const TERMINAL = new Set(['finished', 'blocked_on_approval', 'budget_exhausted'])

/** Per-kind presentation for the inventory cards: an icon plus the accent used
 *  for its tile, so the three extension families read apart at a glance. */
const KIND_META: Record<string, { icon: typeof IconLayers; tone: BadgeTone }> = {
  'llm-provider': { icon: IconChat, tone: 'info' },
  'agent-engine': { icon: IconCog, tone: 'violet' },
  'graph-projection': { icon: IconNetwork, tone: 'success' },
}
const kindMeta = (kind: string) =>
  KIND_META[kind] ?? { icon: IconLayers, tone: 'neutral' as BadgeTone }

/** Extensions panel — the "extensions" category of the merged ops console.
 *
 * What loaded from extensions/ and, below it, the engine capability that has
 * no runtime-config form to live in. The LLM and graph-store capability cards
 * were deleted, not moved: their status is now the live badge on the matching
 * runtime-config section (and their probes sit inside the form they verify),
 * so the same fact never renders twice on one page. */
export function ExtensionsPanel() {
  const { t } = useI18n()
  const inventory = useQuery({ queryKey: ['extensions'], queryFn: apiClient.extensions })

  // ---- agent one-click run (builtin-llm engine, real gates) ----------------
  const [sessionId, setSessionId] = useState<number | null>(null)
  const plugins = useQuery({ queryKey: ['agent-plugins'], queryFn: apiClient.agentPlugins })
  const session = useQuery({
    queryKey: keys.agentSession(sessionId),
    queryFn: () => apiClient.agentSession(sessionId!),
    enabled: sessionId != null,
    refetchInterval: (q) => (q.state.data && TERMINAL.has(q.state.data.status) ? false : 1200),
  })
  const agentProbe = useMutation({
    mutationFn: async (plugin: string) => {
      const s = await apiClient.agentOpenSession(
        plugin,
        t('ext.scenario.agentTask'),
      )
      setSessionId(s.id)
      return apiClient.agentRun(s.id)
    },
  })

  const extensions = inventory.data?.extensions ?? []
  const enginePlugins = (plugins.data?.plugins ?? []).filter((p) => p.engine.kind === 'builtin-llm')
  const loaded = extensions.filter((e) => e.status === 'loaded').length
  const failed = extensions.filter((e) => e.status === 'error').length

  return (
    <div className="flex flex-col gap-5">
      {/* ------------------------------------------------ inventory ---- */}
      <Card
        title={t('ext.inventory')}
        description={t('ext.inventory.hint')}
        actions={
          <span className="flex items-center gap-2">
            <Badge tone={failed ? 'danger' : 'success'}>
              {t('ext.loadedOf', { loaded, total: extensions.length })}
            </Badge>
            {inventory.data?.dirs?.length ? (
              <Badge tone="neutral" mono title={inventory.data.dirs.join('\n')}>
                {inventory.data.dirs[0]}
              </Badge>
            ) : null}
          </span>
        }
        padded={false}
      >
        {inventory.isLoading ? (
          <div className="px-5 pb-5"><Skeleton rows={4} /></div>
        ) : inventory.error ? (
          <ErrorBanner error={inventory.error} />
        ) : (
          <div data-testid="ext-cards">
            {extensions.map((ext) => {
              const meta = kindMeta(ext.kind)
              const Icon = meta.icon
              return (
                <div
                  key={ext.name}
                  data-testid={`ext-card-${ext.name}`}
                  className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t px-5 py-3.5 transition-colors first:border-t-0 hover:bg-[var(--surface-hover)]"
                  style={{ borderColor: 'var(--border-subtle)' }}
                >
                  <span
                    className="grid size-9 shrink-0 place-items-center rounded-lg"
                    style={{ background: TONES[meta.tone].bg, color: TONES[meta.tone].fg }}
                  >
                    <Icon width={16} height={16} />
                  </span>
                  <div className="min-w-[250px] max-w-[360px] flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-[13.5px] font-semibold leading-snug">{ext.display || ext.name}</span>
                      <Badge tone={STATUS_TONE[ext.status] ?? 'neutral'}>{t(`ext.status.${ext.status}`)}</Badge>
                    </div>
                    {/* break-all, not truncate: entry names are long mono tokens
                        (`ontogeny_ext_agent_llm:register`) — a mid-token ellipsis hides
                        exactly the part that identifies the module */}
                    <div className="mt-0.5 font-mono text-[10.5px] leading-snug muted break-all">{ext.name} · {ext.kind} · {ext.entry}</div>
                  </div>
                  <p className="min-w-[220px] flex-[2] text-[12px] leading-relaxed secondary-text">{ext.description}</p>
                  {ext.provides.length || ext.requires.length ? (
                    <div className="ml-auto flex flex-wrap items-center gap-1.5">
                      {ext.provides.map((p) => <Badge key={p} tone="brand" mono>{p}</Badge>)}
                      {ext.requires.map((r) => <Badge key={r} tone="violet" mono>{r}</Badge>)}
                    </div>
                  ) : null}
                  {ext.error ? (
                    <div className="w-full rounded-lg px-2.5 py-2 font-mono text-[11px] break-words" style={toneSurface('danger')}>
                      {ext.error}
                    </div>
                  ) : null}
                </div>
              )
            })}
          </div>
        )}
      </Card>

      {/* ------------------------------------------- capability:engine ---- */}
      {/* the one capability with no config form to live in: engines come from
          plugins, not from runtime config, so this is where they are probed */}
      <Card
        title={t('ext.capEngine')}
        description={t('ext.capEngine.hint')}
        actions={enginePlugins.length ? <Badge tone="violet" mono>{enginePlugins.length}</Badge> : null}
      >
        {plugins.isLoading ? (
          <Skeleton rows={2} />
        ) : enginePlugins.length === 0 ? (
          <Alert tone="warning">{t('ext.capEngine.none')}</Alert>
        ) : (
          <>
            <div className="flex flex-wrap gap-2">
              {enginePlugins.map((p) => (
                <Button
                  key={p.name}
                  data-testid={`agent-probe-${p.name}`}
                  onClick={() => agentProbe.mutate(p.name)}
                  disabled={agentProbe.isPending}
                >
                  {p.display || p.name}
                </Button>
              ))}
            </div>
            {agentProbe.error ? <div className="mt-3"><ErrorBanner error={agentProbe.error} /></div> : null}
            {session.data ? (
              <Strip className="mt-3" testId="agent-probe-result">
                <div className="flex items-center justify-between gap-2">
                  <Badge tone={session.data.status === 'finished' ? 'success' : session.data.status === 'running' ? 'brand' : 'warning'}>
                    {session.data.status}
                  </Badge>
                  <Link className="text-[12px] ontogeny-link" to="/agent/manage">{t('ext.scenario.openConsole')}</Link>
                </div>
                <p className="mt-2 text-[12.5px] leading-relaxed">
                  {typeof session.data.result?.final === 'string'
                    ? session.data.result.final
                    : typeof session.data.result?.error === 'string'
                      ? session.data.result.error
                      : typeof session.data.result?.blocked_on === 'number'
                        ? t('ext.scenario.blocked', { id: session.data.result.blocked_on })
                        : t('ext.scenario.stepsSoFar', { count: session.data.steps?.length ?? 0 })}
                </p>
              </Strip>
            ) : null}
          </>
        )}
      </Card>
    </div>
  )
}
