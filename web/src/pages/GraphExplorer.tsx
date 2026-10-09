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
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import { useMeta } from '../api/queries'
import { useI18n } from '../i18n'
import { Alert, Badge, Button, Card, Page } from '../components/ui'
import { ProjectionView } from './ProjectionView'
import { ErrorBanner } from '../components/ErrorBanner'
import { ExploreGraph, ExploreNodeList } from '../components/ExploreGraph'
import { FlowGraph } from '../components/FlowGraph'
import { traverseToFlow } from '../components/graphAdapters'
import { NodeInfoDrawer } from '../components/NodeInfoDrawer'
import { NeighbourhoodDialog, type NeighbourhoodTarget } from '../components/NeighbourhoodDialog'
import { pkOf, typeColor } from '../lib/rows'
import { IconLayers, IconNetwork, IconPlus, IconRefresh, IconRoute, IconX } from '../components/icons'

/** The pre-run state for the canvas.
 *
 * Not a grey "no data" box: an empty canvas is the normal state here, so it
 * explains what will happen and how to start — icon, one line, three steps, and
 * the run button, centred on the same dot grid the result will use. */
function GraphEmptyState({ icon, title, steps, action }: {
  icon: React.ReactNode
  title: string
  steps: string[]
  action?: React.ReactNode
}) {
  return (
    <div
      className="ontogeny-canvas-grid relative grid min-h-0 flex-1 place-items-center overflow-hidden"
      data-testid="graph-empty"
    >
      <div className="max-w-md px-7 py-6 text-center">
        <span
          className="mx-auto grid size-10 place-items-center rounded-xl"
          style={{ background: 'var(--brand-tint)', color: 'var(--brand-fg)' }}
        >
          {icon}
        </span>
        <p className="mt-3 text-[14px] font-semibold">{title}</p>
        <ol className="mx-auto mt-3 flex max-w-xs flex-col gap-1.5 text-left">
          {steps.map((step, i) => (
            <li key={i} className="flex items-start gap-2 text-[12px] muted">
              <span
                className="mt-[3px] grid size-4 shrink-0 place-items-center rounded-full font-mono text-[9.5px] font-semibold"
                style={{ background: 'var(--surface-sunken)', color: 'var(--text-secondary)' }}
              >
                {i + 1}
              </span>
              {step}
            </li>
          ))}
        </ol>
        {action ? <div className="mt-4 flex justify-center">{action}</div> : null}
      </div>
    </div>
  )
}

/**
 * Graph exploration workbench.
 *
 * One surface, two regions: a narrow "exploration parameters" rail on the left
 * and the result canvas filling everything to its right. The three modes
 * (neighbourhood · path · projection) are a switcher *inside the rail* — they
 * change both the parameters shown and the canvas, so the page never stacks a
 * tab row above a box above another box. The URL still carries the mode
 * (`?tab=path`), so a view stays linkable.
 */
type Mode = 'neighbourhood' | 'path' | 'projection'
interface Hop { link: string; direction: 'out' | 'in' }

export function GraphExplorer() {
  const { t, plural } = useI18n()
  const meta = useMeta()
  const nav = useNavigate()
  const [params, setParams] = useSearchParams()
  const raw = params.get('tab')
  const top: Mode =
    raw === 'path' ? 'path'
    : raw === 'projection' ? 'projection'
    : 'neighbourhood'
  const setTop = (t: Mode) => setParams(t === 'neighbourhood' ? {} : { tab: t })

  const legacyDataTab = raw === 'data' || raw === 'preview'
  useEffect(() => {
    if (legacyDataTab) nav('/knowledge', { replace: true })
  }, [legacyDataTab, nav])

  const objectTypes = Object.keys(meta.data?.objects ?? {})
  const links = useMemo(
    () => Array.from(new Set(Object.values(meta.data?.objects ?? {}).flatMap((o) => o.links))),
    [meta.data],
  )

  // ---- explore state (邻域探索)
  const [useRandom, setUseRandom] = useState(true)
  const [startType, setStartType] = useState(objectTypes[0] ?? '')
  const [startId, setStartId] = useState('')
  const [nNodes, setNNodes] = useState(12)
  const [maxDepth, setMaxDepth] = useState(3)
  const [seed, setSeed] = useState<string>('')

  const explore = useMutation({
    mutationFn: () =>
      apiClient.explore({
        ...(useRandom ? {} : { start_type: startType, start_id: startId.trim() }),
        n: nNodes,
        max_depth: maxDepth,
        seed: seed.trim() ? Number(seed.trim()) : null,
      }),
  })

  // ---- path state (路径遍历)
  const [pStartType, setPStartType] = useState(objectTypes[0] ?? '')
  const [pStartIds, setPStartIds] = useState('')
  const [hops, setHops] = useState<Hop[]>([])
  const traverse = useMutation({
    mutationFn: () =>
      apiClient.traverse({
        start_type: pStartType,
        start_ids: pStartIds.split(/[,\s]+/).map((x) => x.trim()).filter(Boolean),
        path: hops,
      }),
  })

  /** The walk's drawing plus its colour key: one legend row per object type in
   *  the result, tinted with the exact palette the canvas paints it with. */
  const walkFlow = useMemo(
    () => (traverse.data ? traverseToFlow(traverse.data) : null),
    [traverse.data],
  )
  const walkLegend = useMemo(() => {
    if (!walkFlow) return []
    const types = [...new Set(walkFlow.nodes.map((n) => n.type).filter(Boolean))] as string[]
    return types.map((ty) => ({ id: ty, label: ty, color: typeColor(ty) }))
  }, [walkFlow])

  const projectionDeclared = Object.keys(meta.data?.projections ?? {}).length > 0
  const [inspect, setInspect] = useState<{
    title: string; subtitle: string; props: Record<string, unknown>; link?: string
  } | null>(null)
  const [neighbourhood, setNeighbourhood] = useState<NeighbourhoodTarget | null>(null)

  const openExploreNode = (row: Record<string, unknown> & { _type: string; _id: string }) => {
    setInspect({
      title: String(row[pkOf(row)] ?? row._id),
      subtitle: row._type,
      props: row,
      link: `/objects/${row._type}/${encodeURIComponent(row._id)}`,
    })
  }
  const openNeighbourhood = (row: Record<string, unknown> & { _type: string; _id: string }) => {
    setNeighbourhood({ type: row._type, id: row._id, label: String(row[pkOf(row)] ?? row._id) })
  }

  const MODES: Array<{ id: Mode; label: string; icon: React.ReactNode; hint: string }> = [
    { id: 'neighbourhood', label: t('graph.mode.explore'), icon: <IconNetwork width={14} height={14} />, hint: t('graph.mode.exploreHint') },
    { id: 'path', label: t('graph.mode.path'), icon: <IconRoute width={14} height={14} />, hint: t('graph.mode.pathHint') },
    { id: 'projection', label: t('trace.tab.projection'), icon: <IconLayers width={14} height={14} />, hint: t('graph.mode.projectionHint') },
  ]

  return (
    <Page fill testId="graph-explorer">
      <h1 className="sr-only">{t('graph.title')}</h1>

      <Card
        padded={false}
        className="flex min-h-0 flex-1 flex-col"
        bodyClassName="flex min-h-0 flex-1 flex-col"
      >
        <div className="grid min-h-0 flex-1 md:grid-cols-[256px_1fr]">
          {/* ------------------------------------------------ parameters rail */}
          <aside
            className="flex min-h-0 flex-col overflow-y-auto border-b p-3.5 md:border-b-0 md:border-r"
            style={{ borderColor: 'var(--border-subtle)' }}
            data-testid="explore-params"
          >
            <div className="flex items-center justify-between gap-2" style={{ marginBottom: 8 }}>
              <div className="ontogeny-label">{t('graph.explore.title')}</div>
              <Badge tone={projectionDeclared ? 'success' : 'neutral'}>{projectionDeclared ? 'HugeGraph' : 'SQL'}</Badge>
            </div>

            {/* mode switcher: vertical, one row per mode, so the rail reads as a
                single control column instead of a tab strip above a form */}
            <div
              role="tablist"
              aria-orientation="vertical"
              aria-label={t('graph.explore.title')}
              className="flex flex-col gap-0.5 rounded-xl p-1"
              style={{ background: 'var(--surface-sunken)', border: '1px solid var(--border-subtle)' }}
            >
              {MODES.map((m) => {
                const active = m.id === top
                return (
                  <button
                    key={m.id}
                    role="tab"
                    aria-selected={active}
                    title={m.hint}
                    data-testid={`tab-${m.id}`}
                    onClick={() => setTop(m.id)}
                    className="flex items-center gap-2 rounded-lg px-2.5 py-1.5 text-left text-[12.5px] transition-colors"
                    style={{
                      background: active ? 'var(--surface-card)' : 'transparent',
                      color: active ? 'var(--text-primary)' : 'var(--text-muted)',
                      fontWeight: active ? 600 : 500,
                      boxShadow: active ? 'var(--shadow-card)' : 'none',
                    }}
                  >
                    <span style={{ color: active ? 'var(--brand-fg)' : 'var(--text-muted)' }}>{m.icon}</span>
                    {m.label}
                  </button>
                )
              })}
            </div>

            <p className="mt-3 text-[11.5px] leading-relaxed muted">
              {MODES.find((m) => m.id === top)?.hint}
            </p>

            {top === 'projection' ? (
              <div className="mt-3">
                <Alert tone="info">{t('graph.projectionPanel')}</Alert>
              </div>
            ) : null}

            {/* ------------------------------------------- neighbourhood form */}
            {top === 'neighbourhood' ? (
              <div className="mt-3 flex flex-col gap-3">
                <label className="flex cursor-pointer items-center gap-2 text-[12.5px]">
                  <input type="checkbox" className="size-3.5" checked={useRandom} onChange={(e) => setUseRandom(e.target.checked)} />
                  <span className="font-medium">{t('graph.explore.random')}</span>
                </label>

                {!useRandom ? (
                  <div className="flex flex-col gap-2">
                    <div>
                      <label className="ontogeny-label" htmlFor="ex-type">{t('graph.startType')}</label>
                      <select id="ex-type" className="ontogeny-input" value={startType} onChange={(e) => setStartType(e.target.value)}>
                        {objectTypes.map((o) => <option key={o}>{o}</option>)}
                      </select>
                    </div>
                    <div>
                      <label className="ontogeny-label" htmlFor="ex-id">{t('graph.startIds')}</label>
                      <input id="ex-id" className="ontogeny-input font-mono" value={startId} onChange={(e) => setStartId(e.target.value)} placeholder="EQ-01" />
                    </div>
                  </div>
                ) : (
                  <p className="text-[11px] muted">{t('graph.explore.randomHint')}</p>
                )}

                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="ontogeny-label" htmlFor="ex-n">{t('graph.explore.n')}</label>
                    <input id="ex-n" type="number" min={1} max={200} className="ontogeny-input" value={nNodes} onChange={(e) => setNNodes(Number(e.target.value) || 12)} />
                  </div>
                  <div>
                    <label className="ontogeny-label" htmlFor="ex-depth">{t('graph.explore.depth')}</label>
                    <input id="ex-depth" type="number" min={1} max={6} className="ontogeny-input" value={maxDepth} onChange={(e) => setMaxDepth(Number(e.target.value) || 3)} />
                  </div>
                </div>
                <div>
                  <label className="ontogeny-label" htmlFor="ex-seed">{t('graph.explore.seed')}</label>
                  <input id="ex-seed" className="ontogeny-input font-mono" value={seed} onChange={(e) => setSeed(e.target.value)} placeholder={t('graph.explore.seedPh')} />
                </div>

                <div className="flex flex-wrap gap-2">
                  <Button variant="primary" onClick={() => explore.mutate()} disabled={explore.isPending} data-testid="run-explore" icon={<IconNetwork width={14} height={14} />}>
                    {t('graph.explore.run')}
                  </Button>
                  {explore.data ? (
                    <Button onClick={() => explore.mutate()} icon={<IconRefresh width={14} height={14} />} data-testid="re-roll">
                      {useRandom ? t('graph.explore.reroll') : t('common.refresh')}
                    </Button>
                  ) : null}
                </div>

                {explore.data ? (
                  <div className="rounded-lg px-3 py-2 text-[11.5px] muted" style={{ background: 'var(--surface-sunken)' }}>
                    <div className="truncate font-mono">{explore.data.start.type}/{explore.data.start.id}</div>
                    <div>{t('graph.explore.stat', { nodes: explore.data.nodes.length, edges: explore.data.edges.length })}</div>
                    {explore.data.truncated ? <div style={{ color: 'var(--brand-fg)' }}>{t('graph.explore.truncated')}</div> : null}
                  </div>
                ) : null}

                {/* The canvas's text equivalent. Collapsed by default so the
                    right-hand side stays pure graph, but still one click (and
                    one Tab) away for keyboard/screen-reader users. */}
                {explore.data ? (
                  <details style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: 10 }}>
                    <summary className="cursor-pointer text-[11.5px] font-medium muted">
                      {plural('graph.resultNodes', explore.data.nodes.length)}
                    </summary>
                    <div className="mt-2">
                      <ExploreNodeList result={explore.data} />
                    </div>
                  </details>
                ) : null}
              </div>
            ) : null}

            {/* -------------------------------------------------- path form */}
            {top === 'path' ? (
              <div className="mt-3 flex flex-col gap-3">
                <div>
                  <label className="ontogeny-label" htmlFor="p-type">{t('graph.startType')}</label>
                  <select id="p-type" className="ontogeny-input" value={pStartType} onChange={(e) => setPStartType(e.target.value)}>
                    {objectTypes.map((o) => <option key={o}>{o}</option>)}
                  </select>
                </div>
                <div>
                  <label className="ontogeny-label" htmlFor="p-ids">{t('graph.startIds')}</label>
                  <input id="p-ids" className="ontogeny-input font-mono" value={pStartIds} onChange={(e) => setPStartIds(e.target.value)} placeholder="SO-2026-0001" />
                </div>
                <div className="flex flex-col gap-2">
                  {hops.map((hop, i) => (
                    <div key={i} className="rounded-lg p-2" style={{ background: 'var(--surface-sunken)' }}>
                      <div className="mb-1.5 flex items-center justify-between">
                        <span className="text-[11px] font-semibold uppercase tracking-[0.06em] muted">{t('graph.hopN', { n: i + 1 })}</span>
                        <button
                          type="button"
                          aria-label={`remove-hop-${i}`}
                          onClick={() => setHops(hops.filter((_, j) => j !== i))}
                          className="grid size-5 place-items-center rounded-md muted transition-colors hover:bg-[var(--surface-hover)]"
                        >
                          <IconX width={12} height={12} />
                        </button>
                      </div>
                      <select aria-label={`hop-link-${i}`} className="ontogeny-input mb-1.5" value={hop.link} onChange={(e) => setHops(hops.map((h, j) => (j === i ? { ...h, link: e.target.value } : h)))}>
                        {links.map((l) => <option key={l}>{l}</option>)}
                      </select>
                      <select aria-label={`hop-dir-${i}`} className="ontogeny-input" value={hop.direction} onChange={(e) => setHops(hops.map((h, j) => (j === i ? { ...h, direction: e.target.value as 'out' | 'in' } : h)))}>
                        <option value="out">{t('graph.direction.out')}</option>
                        <option value="in">{t('graph.direction.in')}</option>
                      </select>
                    </div>
                  ))}
                  <div>
                    <Button size="sm" onClick={() => setHops([...hops, { link: links[0] ?? '', direction: 'out' }])} data-testid="add-hop" icon={<IconPlus width={13} height={13} />}>
                      {t('graph.addHop')}
                    </Button>
                  </div>
                </div>
                <Button variant="primary" disabled={!pStartIds.trim()} onClick={() => traverse.mutate()} data-testid="run-traverse" icon={<IconRoute width={14} height={14} />}>
                  {t('graph.run')}
                </Button>
              </div>
            ) : null}
          </aside>

          {/* ------------------------------------------------------ canvas */}
          <section className="flex min-h-0 flex-1 flex-col">
            {top === 'projection' ? (
              <div className="min-h-0 flex-1 overflow-y-auto p-4">
                <ProjectionView />
              </div>
            ) : null}

            {top === 'neighbourhood' ? (
              <>
                <CanvasHeader
                  icon={<IconNetwork width={14} height={14} />}
                  title={t('graph.explore.resultTitle')}
                  hint={t('graph.dblclickHint')}
                  badge={explore.data ? t('graph.explore.stat', { nodes: explore.data.nodes.length, edges: explore.data.edges.length }) : undefined}
                  actions={explore.data ? (
                    <Button size="sm" onClick={() => explore.mutate()} icon={<IconRefresh width={13} height={13} />}>
                      {useRandom ? t('graph.explore.reroll') : t('common.refresh')}
                    </Button>
                  ) : null}
                />
                {explore.error ? <div className="p-4"><ErrorBanner error={explore.error} /></div> : null}
                {!explore.data ? (
                  <GraphEmptyState
                    icon={<IconNetwork width={22} height={22} />}
                    title={t('graph.explore.emptyTitle')}
                    steps={[t('graph.explore.emptyStep1'), t('graph.explore.emptyStep2'), t('graph.explore.emptyStep3')]}
                    action={<Button variant="primary" onClick={() => explore.mutate()} icon={<IconNetwork width={14} height={14} />}>{t('graph.explore.run')}</Button>}
                  />
                ) : (
                  <div className="min-h-0 flex-1 p-2" data-testid="explore-result">
                    <ExploreGraph result={explore.data} onNodeClick={openExploreNode} onNodeDoubleClick={openNeighbourhood} fill />
                  </div>
                )}
              </>
            ) : null}

            {top === 'path' ? (
              <>
                <CanvasHeader
                  icon={<IconRoute width={14} height={14} />}
                  title={t('graph.walkTitle')}
                  badge={traverse.data ? plural('graph.resultCount', traverse.data.final_ids.length) : undefined}
                />
                {traverse.error ? <div className="p-4"><ErrorBanner error={traverse.error} /></div> : null}
                {!traverse.data ? (
                  <GraphEmptyState
                    icon={<IconRoute width={22} height={22} />}
                    title={t('graph.path.emptyTitle')}
                    steps={[t('graph.path.emptyStep1'), t('graph.path.emptyStep2'), t('graph.path.emptyStep3')]}
                  />
                ) : (
                  <div className="flex min-h-0 flex-1 flex-col" data-testid="traverse-result">
                    <div className="min-h-0 flex-1 p-2">
                      <FlowGraph
                        key={JSON.stringify(traverse.data.final_ids) + traverse.data.steps.length}
                        data={walkFlow ?? traverseToFlow(traverse.data)}
                        legendItems={walkLegend}
                        height={520}
                        fill
                        testId="traverse-flow"
                      />
                    </div>
                    <div
                      className="max-h-[38%] shrink-0 overflow-y-auto px-4 py-3"
                      style={{ borderTop: '1px solid var(--border-subtle)' }}
                    >
                      <div className="flex flex-col gap-2">
                        {traverse.data.steps.map((step, i) => (
                          <div key={i} className="flex flex-wrap items-baseline gap-2">
                            <Badge tone={i === 0 ? 'brand' : 'info'}>{t('graph.stepN', { n: i })}</Badge>
                            <span className="font-mono text-[12.5px]">{step.type}</span>
                            <span className="text-[11.5px] muted">{plural('graph.resultCount', step.ids.length)}</span>
                            <span className="flex flex-wrap gap-1.5">
                              {step.objects.map((row, j) => {
                                const pk = pkOf(row)
                                return (
                                  <Link key={j} className="ontogeny-code hover:underline" to={`/objects/${step.type}/${encodeURIComponent(String(row[pk]))}`}>
                                    {String(row[pk])}
                                  </Link>
                                )
                              })}
                            </span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                )}
              </>
            ) : null}
          </section>
        </div>
      </Card>

      <NodeInfoDrawer
        open={inspect !== null}
        onClose={() => setInspect(null)}
        title={inspect?.title ?? ''}
        subtitle={inspect?.subtitle}
        dotColor={inspect ? typeColor(inspect.subtitle) : undefined}
        items={inspect ? Object.entries(inspect.props)
          .filter(([k]) => !k.startsWith('_'))
          .map(([k, v]) => ({ key: k, value: v === null || v === undefined ? '—' : String(v) })) : []}
        link={inspect?.link ? { to: inspect.link, label: t('drawer.openDetail') } : undefined}
      />

      <NeighbourhoodDialog
        key={neighbourhood ? `${neighbourhood.type}/${neighbourhood.id}` : 'closed'}
        node={neighbourhood}
        onClose={() => setNeighbourhood(null)}
      />
    </Page>
  )
}

/** Slim strip above a canvas: what the canvas is, its size, and its one action. */
function CanvasHeader({ icon, title, hint, badge, actions }: {
  icon: React.ReactNode
  title: string
  hint?: string
  badge?: string
  actions?: React.ReactNode
}) {
  return (
    <header
      className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1.5 px-4 py-2.5"
      style={{ borderBottom: '1px solid var(--border-subtle)' }}
    >
      <span className="flex items-center gap-2 text-[13px] font-semibold">
        <span style={{ color: 'var(--brand-fg)' }}>{icon}</span>
        {title}
      </span>
      {badge ? <Badge tone="neutral">{badge}</Badge> : null}
      {hint ? <span className="text-[11.5px] muted">{hint}</span> : null}
      {actions ? <span className="ml-auto flex items-center gap-2">{actions}</span> : null}
    </header>
  )
}
