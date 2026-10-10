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
 * Color system for this page: exactly three accent hues, each with shades —
 * PURPLE = modeling / semantic / agents, BLUE = writes / core / alerts,
 * GREEN = the loop / evals / pass. Oranges and reds are out.
 *
 * 运行看板 — the opening page. Four hero panels cut from the same cloth
 * (icon · bold title · badge · lede · content):
 *
 *   §1 ONTOGENY 介绍       what the platform is + the condensed architecture
 *                      board (ArchBoard): citizens / pipeline × RSI loop /
 *                      supporting + mechanisms;
 *   §2 本体模型        resource-mix donut, then the model grouped by layer
 *                      (semantic / kinetic / governance) as accent panels;
 *   §3 智能Agent扩展   lifecycle beats, the session-status donut and icon
 *                      vitals tiles;
 *   §4 治理与自进化     RSI loop hero with the six-beat strip.
 *
 * Metrics only: every tile is a number, every button a navigation.
 */
import { Fragment } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import { keys, useMeta } from '../api/queries'
import { useI18n } from '../i18n'
import { Badge, Page } from '../components/ui'
import {
  IconBolt, IconBraces, IconCube, IconInfo, IconLayers, IconLinkType, IconList,
  IconPlay, IconRefresh, IconShield, IconSpark, IconUser, IconWarning,
} from '../components/icons'
import { LoopStrip } from './evolve/LoopStrip'
import { ArchBoard } from './dashboard/ArchBoard'

type Tone = 'violet' | 'brand' | 'info' | 'success'

/** Light shade of an accent hue (theme-aware, for donut segments and chips). */
const shade = (fg: string, pct: number) => `color-mix(in srgb, ${fg} ${pct}%, var(--surface-card))`

const toneFg: Record<string, string> = {
  brand: 'var(--tone-brand-fg)',
  success: 'var(--tone-success-fg)',
  violet: 'var(--tone-violet-fg)',
}

/** Renders the **bold** spans inside a catalogue string, so key terms in a
 *  lede can be emphasized without splitting the message into many keys. */
function RichText({ text }: { text: string }) {
  const parts = text.split('**')
  return (
    <>
      {parts.map((p, i) =>
        i % 2 === 1 ? <strong key={i} className="font-bold">{p}</strong> : <Fragment key={i}>{p}</Fragment>,
      )}
    </>
  )
}

/** The shared hero header: icon chip, bold title, badges, and a trailing slot. */
function HeroHead({
  icon, title, children,
}: { icon: React.ReactNode; title: string; children?: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="grid size-7 place-items-center rounded-lg" style={{ background: 'var(--tone-violet-bg)', color: 'var(--tone-violet-fg)' }}>
        {icon}
      </span>
      <h2 className="text-[15px] font-bold tracking-tight">{title}</h2>
      {children}
    </div>
  )
}

/** Minimal donut used by both metric sections: segmented ring, total centered. */
function Donut({ segs, center, centerSub, size = 116, testId }: {
  segs: Array<{ value: number; color: string }>
  center: string | number
  centerSub?: string
  size?: number
  testId?: string
}) {
  const total = segs.reduce((a, s) => a + s.value, 0)
  const R = 40
  const C = 2 * Math.PI * R
  let offset = 0
  return (
    <svg width={size} height={size} viewBox="0 0 104 104" data-testid={testId}>
      <circle cx="52" cy="52" r={R} fill="none" stroke="var(--surface-sunken)" strokeWidth={13} />
      {total > 0 && segs.map((s, i) => {
        const frac = s.value / total
        const el = (
          <circle key={i} cx="52" cy="52" r={R} fill="none" stroke={s.color} strokeWidth={13}
                  strokeDasharray={`${frac * C} ${C}`} strokeDashoffset={-offset * C}
                  transform="rotate(-90 52 52)" strokeLinecap="butt" />
        )
        offset += frac
        return el
      })}
      <text x="52" y="50" textAnchor="middle" className="tnum" fontSize="20" fontWeight="700" fill="var(--text-primary)">
        {center}
      </text>
      {centerSub ? (
        <text x="52" y="66" textAnchor="middle" fontSize="9.5" fill="var(--text-muted)">{centerSub}</text>
      ) : null}
    </svg>
  )
}

/** A metric tile with an icon chip: number, label, one accent tone. */
function MetricTile({ icon, label, value, tone = 'violet', valueTone }: {
  icon: React.ReactNode
  label: string
  value: string | number
  tone?: Tone
  valueTone?: string
}) {
  return (
    <div className="flex min-w-0 items-center gap-2.5 rounded-xl px-3 py-2.5"
         style={{ background: 'var(--surface-card)', border: '1px solid var(--border-subtle)' }}>
      <span className="grid size-8 shrink-0 place-items-center rounded-lg"
            style={{ background: `var(--tone-${tone}-bg)`, color: `var(--tone-${tone}-fg)` }}>
        {icon}
      </span>
      <span className="min-w-0">
        <span className="block text-[16px] font-bold leading-none tnum" style={valueTone ? { color: valueTone } : undefined}>
          {value}
        </span>
        <span className="mt-1 block truncate text-[10.5px] muted">{label}</span>
      </span>
    </div>
  )
}

/** One ontology layer: accent panel with a tone-dot header, group subtotal
 *  and its metric tiles on top. */
function MetricGroup({ tone, label, total, cells }: {
  tone: Tone
  label: string
  total: string | number
  cells: Array<{ icon: React.ReactNode; label: string; value: string | number }>
}) {
  return (
    <div className="rounded-xl p-2" style={{ background: `var(--tone-${tone}-bg)`, border: `1px solid var(--tone-${tone}-ring)` }}>
      <div className="flex items-center gap-1.5 px-1 pb-1.5">
        <span className="size-2 shrink-0 rounded-full" style={{ background: `var(--tone-${tone}-fg)` }} />
        <span className="truncate text-[11px] font-extrabold" style={{ color: `var(--tone-${tone}-fg)` }}>{label}</span>
        <span className="ml-auto shrink-0 text-[10.5px] font-bold tnum" style={{ color: `var(--tone-${tone}-fg)` }}>{total}</span>
      </div>
      <div className={['grid gap-1.5', cells.length > 2 ? 'grid-cols-2 sm:grid-cols-4' : 'grid-cols-2'].join(' ')}>
        {cells.map((c) => <MetricTile key={c.label} icon={c.icon} label={c.label} value={c.value} tone={tone} />)}
      </div>
    </div>
  )
}

export function Dashboard() {
  const { t, lang } = useI18n()
  const zh = lang === 'zh'
  const meta = useMeta()
  const signals = useQuery({ queryKey: keys.signals, queryFn: () => apiClient.signals() })
  const proposals = useQuery({ queryKey: keys.proposals, queryFn: () => apiClient.proposals() })
  const sessions = useQuery({ queryKey: ['agent-sessions', ''], queryFn: () => apiClient.agentSessions() })
  const approvals = useQuery({
    queryKey: ['agent-approvals', 'dashboard'],
    queryFn: () => apiClient.agentApprovals('pending'),
    refetchInterval: 8000,
  })

  const counts = meta.data
  const propStats = Object.values(counts?.objects ?? {}).reduce(
    (acc: { total: number; derived: number }, o) => {
      const props = Object.values(o.properties ?? {})
      return {
        total: acc.total + props.length,
        derived: acc.derived + props.filter((p) => p.derived).length,
      }
    },
    { total: 0, derived: 0 },
  )
  const nObjects = counts ? Object.keys(counts.objects).length : 0
  const nLinks = counts ? Object.keys(counts.linkTypes ?? {}).length : 0
  const nActions = counts ? Object.keys(counts.actions).length : 0
  const nFunctions = counts ? Object.keys(counts.functions).length : 0
  const nPolicies = counts ? Object.keys(counts.policies ?? {}).length : 0
  const nRoles = (counts?.roles ?? []).length
  const mixTotal = nObjects + nLinks + nActions + nFunctions + nPolicies + nRoles

  const sessionRows = sessions.data?.sessions ?? []
  const running = sessionRows.filter((s) => s.status === 'running').length
  const openSessions = sessionRows.filter((s) => s.status === 'open').length
  const finished = sessionRows.filter((s) => s.status === 'finished').length
  const blocked = approvals.data?.approvals.length ?? 0
  const promotedCount = (proposals.data?.proposals ?? []).filter((p) => p.status === 'promoted').length
  const signalCount = signals.data?.signals.length ?? 0

  const refreshAll = () => {
    meta.refetch(); signals.refetch(); proposals.refetch(); sessions.refetch(); approvals.refetch()
  }

  // §2 resource-mix donut: one segment per declared resource kind —
  // purple = semantic kinds, blue = kinetic kinds, green = governance kinds;
  // the light halves are shades of the same hue
  const mixSegs = [
    { value: nObjects, color: 'var(--tone-violet-fg)' },
    { value: nLinks, color: shade('var(--tone-violet-fg)', 45) },
    { value: nActions, color: 'var(--tone-brand-fg)' },
    { value: nFunctions, color: shade('var(--tone-brand-fg)', 45) },
    { value: nPolicies, color: 'var(--tone-success-fg)' },
    { value: nRoles, color: shade('var(--tone-success-fg)', 45) },
  ]

  // §3 the agent lifecycle as numbered beats
  const agentFlow = [
    t('dashboard.agent.flow.1'),
    t('dashboard.agent.flow.2'),
    t('dashboard.agent.flow.3'),
    t('dashboard.agent.flow.4'),
    t('dashboard.agent.flow.5'),
  ]
  const sessionSegs = [
    { value: running, color: 'var(--tone-violet-fg)', label: t('dashboard.rt.running') },
    { value: openSessions, color: shade('var(--tone-brand-fg)', 55), label: t('dashboard.rt.open') },
    { value: finished, color: 'var(--tone-success-fg)', label: t('dashboard.rt.finished') },
  ]
  const sessionTotal = running + openSessions + finished

  return (
    <Page>
      <h1 className="sr-only">{t('dashboard.title')}</h1>

      {/* ------------------------- §1 ONTOGENY 介绍: intro + architecture ---- */}
      <section
        className="relative overflow-hidden rounded-2xl p-5"
        style={{
          background: 'linear-gradient(130deg, var(--tone-violet-bg) 0%, var(--surface-card) 52%, var(--tone-success-bg) 125%)',
          border: '1px solid var(--border-subtle)',
        }}
        data-testid="system-overview"
      >
        <div className="flex flex-wrap items-center gap-2">
          <HeroHead icon={<IconInfo width={15} height={15} />} title={t('dashboard.overview.title')}>
            <Badge tone="violet" mono>{counts?.package ?? '—'}</Badge>
          </HeroHead>
          <button
            type="button"
            data-testid="dashboard-refresh"
            title={t('common.refresh')}
            aria-label={t('common.refresh')}
            onClick={refreshAll}
            className="ml-auto grid size-7 place-items-center rounded-lg transition-colors hover:bg-[var(--surface-hover)]"
            style={{ color: 'var(--text-muted)' }}
          >
            <IconRefresh width={14} height={14} />
          </button>
        </div>
        <p className="mt-2 max-w-5xl text-[12.5px] font-medium leading-relaxed" style={{ color: 'var(--text-primary)' }}>
          <RichText text={t('dashboard.overview.desc')} />
        </p>

        {/* the condensed architecture board from docs/architecture/01-overall-architecture.md */}
        <ArchBoard />
      </section>

      {/* ----------------------------- §2 本体模型: mix + layered groups ---- */}
      <section
        className="relative overflow-hidden rounded-2xl p-5"
        style={{
          background: 'linear-gradient(115deg, var(--tone-violet-bg) 0%, var(--surface-card) 48%, var(--tone-brand-bg) 120%)',
          border: '1px solid var(--border-subtle)',
        }}
        data-testid="ontology-model"
      >
        <HeroHead icon={<IconCube width={15} height={15} />} title={t('dashboard.section.ontology')}>
          {counts ? <Badge tone="violet" mono>{counts.package}</Badge> : null}
          <Link to="/ontology" className="ontogeny-link ml-auto text-[12px]" style={{ color: 'var(--tone-violet-fg)' }}>
            {t('dashboard.card.ontologyJump')} →
          </Link>
        </HeroHead>
        <p className="mt-2 max-w-3xl text-[12.5px] leading-relaxed secondary-text">
          {t('dashboard.ontology.desc')}
        </p>

        <div className="mt-3.5 grid items-stretch gap-2.5 lg:grid-cols-[148px_minmax(0,1fr)]" data-testid="dash-metric-ontology">
          {/* the mix: one donut per resource kind, total in the middle */}
          <div className="flex flex-col items-center justify-center rounded-xl px-3 py-3"
               style={{ background: 'var(--surface-card)', border: '1px solid var(--border-subtle)' }}>
            <Donut
              testId="ontology-mix-donut"
              segs={mixSegs}
              center={counts ? mixTotal : '—'}
              centerSub={zh ? '类资源' : 'resources'}
            />
            <div className="mt-1.5 text-center text-[10.5px] font-semibold" style={{ color: 'var(--text-secondary)' }}>
              {t('dashboard.ontology.mix')}
            </div>
          </div>

          {/* the model by layer: semantic / kinetic / governance */}
          <div className="flex min-w-0 flex-col gap-2.5">
            <MetricGroup
              tone="violet"
              label={t('dashboard.ontology.group.semantic')}
              total={counts ? nObjects + nLinks : '—'}
              cells={[
                { icon: <IconCube width={14} height={14} />, label: t('dashboard.metric.objects'), value: counts ? nObjects : '—' },
                { icon: <IconList width={14} height={14} />, label: t('dashboard.metric.properties'), value: counts ? propStats.total : '—' },
                { icon: <IconSpark width={14} height={14} />, label: t('dashboard.metric.derived'), value: counts ? propStats.derived : '—' },
                { icon: <IconLinkType width={14} height={14} />, label: t('dashboard.metric.links'), value: counts ? nLinks : '—' },
              ]}
            />
            <div className="grid gap-2.5 sm:grid-cols-2">
              <MetricGroup
                tone="brand"
                label={t('dashboard.ontology.group.kinetic')}
                total={counts ? nActions + nFunctions : '—'}
                cells={[
                  { icon: <IconBolt width={14} height={14} />, label: t('dashboard.metric.actions'), value: counts ? nActions : '—' },
                  { icon: <IconBraces width={14} height={14} />, label: t('dashboard.metric.functions'), value: counts ? nFunctions : '—' },
                ]}
              />
              <MetricGroup
                tone="success"
                label={t('dashboard.ontology.group.governance')}
                total={counts ? nPolicies + nRoles : '—'}
                cells={[
                  { icon: <IconShield width={14} height={14} />, label: t('dashboard.metric.policies'), value: counts ? nPolicies : '—' },
                  { icon: <IconUser width={14} height={14} />, label: t('dashboard.metric.roles'), value: counts ? nRoles : '—' },
                ]}
              />
            </div>
          </div>
        </div>
      </section>

      {/* ------------------- §3 智能Agent扩展: lifecycle + vitals ---- */}
      <section
        className="relative overflow-hidden rounded-2xl p-5"
        style={{
          background: 'linear-gradient(115deg, var(--tone-brand-bg) 0%, var(--surface-card) 48%, var(--tone-violet-bg) 120%)',
          border: '1px solid var(--border-subtle)',
        }}
        data-testid="agent-extensions"
      >
        <HeroHead icon={<IconLayers width={15} height={15} />} title={t('dashboard.agent.title')}>
          {blocked > 0 ? <Badge tone="brand">{t('dashboard.metric.approvalsPending')} {blocked}</Badge> : null}
          <Link to="/agent/manage" className="ontogeny-link ml-auto text-[12px]" style={{ color: 'var(--tone-violet-fg)' }}>
            {t('dashboard.card.runtimeJump')} →
          </Link>
        </HeroHead>
        <p className="mt-2 max-w-3xl text-[12.5px] leading-relaxed secondary-text">
          {t('dashboard.agent.desc')}
        </p>

        {/* the agent lifecycle: declare → execute → approve → trace → audit */}
        <div className="mt-3.5 flex flex-wrap items-center gap-1.5">
          {agentFlow.map((step, i) => (
            <div key={step} className="flex min-w-0 flex-wrap items-center gap-1.5">
              <span className="flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[12px]"
                    style={{ background: 'var(--surface-card)', border: '1px solid var(--border-subtle)' }}>
                <span className="grid size-[18px] place-items-center rounded-full text-[10px] font-bold"
                      style={{ background: 'var(--tone-violet-bg)', color: 'var(--tone-violet-fg)' }}>
                  {i + 1}
                </span>
                {step}
              </span>
              {i < agentFlow.length - 1 ? (
                <span aria-hidden style={{ color: 'var(--text-muted)' }}>→</span>
              ) : null}
            </div>
          ))}
        </div>

        {/* vitals: session-status donut with legend, then the icon tiles */}
        <div className="mt-4 flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-3 rounded-xl px-4 py-3"
               style={{ background: 'var(--surface-card)', border: '1px solid var(--border-subtle)' }}
               data-testid="session-donut">
            <Donut segs={sessionSegs} center={sessionTotal} centerSub="sessions" size={104} />
            <div className="flex flex-col gap-1.5">
              {sessionSegs.map((s) => (
                <div key={s.label} className="flex items-center gap-2 text-[12px]">
                  <span className="size-2.5 rounded-full" style={{ background: s.color }} />
                  <span className="muted">{s.label}</span>
                  <span className="tnum font-semibold">{s.value}</span>
                </div>
              ))}
            </div>
          </div>
          <div className="grid min-w-[260px] flex-1 grid-cols-1 gap-2 sm:grid-cols-3">
            <MetricTile
              tone="info"
              icon={<IconPlay width={14} height={14} />}
              label={t('dashboard.metric.runs')}
              value={sessionRows.reduce((a, s) => a + (s.run_count ?? 0), 0)}
            />
            <MetricTile
              tone="violet"
              icon={<IconBolt width={14} height={14} />}
              label={t('dashboard.metric.writesUsed')}
              value={sessionRows.reduce((a, s) => a + (s.budget.writes_used ?? 0), 0)}
            />
            <MetricTile
              tone="brand"
              icon={<IconWarning width={14} height={14} />}
              label={t('dashboard.metric.approvalsPending')}
              value={blocked}
              valueTone={blocked > 0 ? toneFg.brand : toneFg.success}
            />
          </div>
        </div>
      </section>

      {/* ------------------------- §4 治理与自进化: RSI loop hero ---- */}
      <section
        data-testid="rsi-hero"
        className="relative overflow-hidden rounded-2xl"
        style={{
          background: 'linear-gradient(115deg, var(--tone-success-bg) 0%, var(--surface-card) 46%, var(--tone-violet-bg) 115%)',
          border: '1px solid var(--border-subtle)',
        }}
      >
        <div className="flex flex-col gap-5 p-5 lg:flex-row lg:items-center lg:gap-7">
          <div className="min-w-0 flex-1">
            <HeroHead icon={<IconSpark width={15} height={15} />} title={t('dashboard.rsi.title')}>
              <Badge tone="violet">{t('dashboard.rsi.badge')}</Badge>
            </HeroHead>
            <p className="mt-2 max-w-2xl text-[12.5px] leading-relaxed secondary-text">
              {t('dashboard.rsi.desc')}
            </p>
            <div className="mt-3.5 flex flex-wrap items-center gap-2">
              <Link to="/evolve" className="ontogeny-btn ontogeny-btn-primary" data-testid="rsi-open">
                <IconSpark width={14} height={14} />
                {t('dashboard.rsi.open')}
              </Link>
            </div>
          </div>
          <div className="shrink-0 lg:w-[352px]">
            <div className="grid grid-cols-3 gap-2">
              <div data-testid="rsi-stat-signals" className="rounded-xl px-3 py-2.5"
                   style={{ background: 'var(--surface-card)', border: '1px solid var(--border-subtle)' }}>
                <div className="text-[20px] font-bold leading-none tnum"
                     style={{ color: signalCount > 0 ? toneFg.brand : 'var(--text-primary)' }}>
                  {signalCount}
                </div>
                <div className="mt-1.5 truncate text-[10.5px] muted">{t('dashboard.rsi.stat.signals')}</div>
              </div>
              <div data-testid="rsi-stat-proposals" className="rounded-xl px-3 py-2.5"
                   style={{ background: 'var(--surface-card)', border: '1px solid var(--border-subtle)' }}>
                <div className="text-[20px] font-bold leading-none tnum" style={{ color: toneFg.violet }}>
                  {proposals.data?.proposals.length ?? 0}
                </div>
                <div className="mt-1.5 truncate text-[10.5px] muted">{t('dashboard.rsi.stat.proposals')}</div>
              </div>
              <div data-testid="rsi-stat-promoted" className="rounded-xl px-3 py-2.5"
                   style={{ background: 'var(--surface-card)', border: '1px solid var(--border-subtle)' }}>
                <div className="text-[20px] font-bold leading-none tnum" style={{ color: 'var(--tone-success-fg)' }}>
                  {promotedCount}
                </div>
                <div className="mt-1.5 truncate text-[10.5px] muted">{t('dashboard.rsi.stat.promoted')}</div>
              </div>
            </div>
            <div className="mt-2 truncate px-1 text-[11px] muted">{t('dashboard.rsi.stat.hint')}</div>
          </div>
        </div>
        <div className="px-5 pb-4">
          <LoopStrip />
        </div>
      </section>
    </Page>
  )
}
