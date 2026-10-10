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
import { useMutation } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import { useMeta } from '../api/queries'
import { useI18n } from '../i18n'
import { Badge, Button, Card, EmptyState, KeyValue, Page, Skeleton } from '../components/ui'
import { ErrorBanner } from '../components/ErrorBanner'
import { Timeline } from '../components/Timeline'
import { FlowGraph } from '../components/FlowGraph'
import { formatCell, pkOf, typeColor } from '../lib/rows'
import { NodeInfoDrawer } from '../components/NodeInfoDrawer'
import { ObjectsDialog } from '../components/ObjectsDialog'
import { exploreToFlow } from '../components/graphAdapters'
import { IconArrowLeft, IconNetwork, IconRoute } from '../components/icons'

export function ObjectDetail() {
  const { type = '', id = '' } = useParams()
  return (
    <Page>
      <h1 className="sr-only">{id}</h1>
      <ObjectDetailBody type={type} id={id} />
    </Page>
  )
}

/** The object detail surface itself, reusable outside the route.
 *
 * The audit page opens the same view in a large dialog (one implementation,
 * two frames — the same split the agent console makes for its dock). In
 * `embedded` frame:
 * - the browser-back button and its objects dialog are hidden (they are the
 *   page frame's navigation),
 * - a linked object is followed IN PLACE via `onSelectObject` instead of an
 *   SPA navigation that would yank the dialog's host page away.
 */
export function ObjectDetailBody({ type, id, embedded = false, onSelectObject }: {
  type: string
  id: string
  embedded?: boolean
  /** when given, following a linked object swaps the host dialog's object */
  onSelectObject?: (type: string, id: string) => void
}) {
  const { t } = useI18n()
  const meta = useMeta()
  const obj = useQuery({ queryKey: ['object', type, id], queryFn: () => apiClient.getObject(type, id) })
  const history = useQuery({ queryKey: ['history', type, id], queryFn: () => apiClient.getHistory(type, id) })
  const links = meta.data?.objects[type]?.links ?? []
  const [activeLink, setActiveLink] = useState<string | null>(null)
  const [ego, setEgo] = useState<import('../api/types').ExploreResult | null>(null)
  const [egoInspect, setEgoInspect] = useState<Record<string, unknown> | null>(null)
  const [browse, setBrowse] = useState(false)
  const egoRun = useMutation({
    mutationFn: () =>
      apiClient.explore({ start_type: type, start_id: id, n: 12, max_depth: 2, seed: 7 }),
    onSuccess: setEgo,
  })
  const linked = useQuery({
    queryKey: ['linked', type, id, activeLink],
    queryFn: () => apiClient.getLinks(type, id, activeLink!),
    enabled: Boolean(activeLink),
  })

  const objectMeta = meta.data?.objects[type]
  const pk = objectMeta?.primaryKey[0] ?? 'id'
  // the other end of the active link, read from the model's own source/target:
  // this used to be guessed from the current type (`equipment` -> `work-order`),
  // which sent every link leaving equipment to the wrong object type
  const activeLinkMeta = activeLink ? meta.data?.linkTypes?.[activeLink] : undefined
  const linkedType = activeLinkMeta
    ? activeLinkMeta.source === type ? activeLinkMeta.target : activeLinkMeta.source
    : undefined

  if (obj.isLoading) return <Skeleton rows={6} />
  if (obj.error) return <ErrorBanner error={obj.error} />
  const data = obj.data!
  const props = Object.entries(data).filter(([k]) => !k.startsWith('_'))
  const system = Object.entries(data).filter(([k]) => k.startsWith('_'))

  return (
    <>
      <div className="grid items-start gap-5 lg:grid-cols-[1.5fr_1fr]">
      {/* breadcrumb, object id and the traceability jump all live on the
          field panel: it is the page's one primary surface */}
      <Card
        padded={false}
        title={
          <span className="flex items-center gap-2">
            {/* back to the type's rows, in a dialog: the browser is a view of
                the model, not a place you navigate away to (page frame only —
                the audit dialog frame has no browser behind it) */}
            {!embedded ? (
              <button
                type="button"
                className="ontogeny-link inline-flex items-center gap-1 text-[12.5px] muted"
                data-testid="back-to-browser"
                onClick={() => setBrowse(true)}
              >
                <IconArrowLeft width={13} height={13} />
                {type}
              </button>
            ) : null}
            {!embedded ? <span className="muted">/</span> : null}
            <span className="font-mono">{String(data[pk])}</span>
          </span>
        }
          description={meta.data?.objects[type]?.display}
          actions={
            <Link className="ontogeny-btn-ghost ontogeny-btn-sm" to={`/graph`} title={t('object.inspectInGraph')}>
              <IconRoute width={14} height={14} />
              {t('object.traceability')}
            </Link>
          }
          bodyClassName="[&>section+section]:border-t [&>section+section]:border-[var(--border-subtle)]"
        >
          <section>
            <div className="px-5 py-2">
              {/* the shared field list, so a field's label column and value
                  typography match the graph drawer showing the same object */}
              <KeyValue items={props.map(([key, value]) => {
                const def = objectMeta?.properties[key]
                return {
                  key: (
                    <span className="block">
                      {def?.display ? <span className="block text-[12.5px] font-medium">{def.display}</span> : null}
                      <span className={`font-mono text-[12px] ${def?.display ? 'muted text-[11px]' : ''}`}>{key}</span>
                      {key === pk ? <span className="ml-2"><Badge tone="warning">PK</Badge></span> : null}
                      {def?.derived ? (
                        <span className="ml-2" title={def.derived.expr ?? def.derived.entry ?? undefined}>
                          <Badge tone="violet">{t('type.derived')}</Badge>
                        </span>
                      ) : null}
                    </span>
                  ),
                  value: (
                    <span className="block">
                      {value === '__masked__' ? (
                        <span className="inline-flex items-center gap-2">
                          <Badge tone="warning" mono>▒ {t('common.masked')}</Badge>
                          <span className="text-[11.5px] muted">{t('objects.maskedHint')}</span>
                        </span>
                      ) : (
                        formatCell(value)
                      )}
                      {def?.description ? (
                        <span className="mt-0.5 block text-[11px] muted">{def.description}</span>
                      ) : null}
                    </span>
                  ),
                }
              })} />
            </div>
            <div className="flex flex-wrap gap-2 px-5 py-3 font-mono text-[11px] muted" style={{ borderTop: '1px solid var(--border-subtle)' }}>
              <span className="w-full text-[10.5px] font-semibold uppercase tracking-[0.06em]">{t('object.systemFields')}</span>
              {system.map(([k, v]) => <span key={k}>{k}={String(v ?? '∅')}</span>)}
            </div>
          </section>

          <section className="p-5">
            <h3 className="mb-3 text-[13px] font-semibold tracking-wide">{t('object.links')}</h3>
            {links.length === 0 ? (
              <EmptyState compact icon={<IconNetwork width={16} height={16} />} title={t('common.none')} description={t('type.noLinks')} />
            ) : (
              <>
                <div className="mb-3 flex flex-wrap gap-2">
                  {links.map((l) => (
                    <Button
                      key={l}
                      variant={activeLink === l ? 'primary' : 'ghost'}
                      size="sm"
                      onClick={() => setActiveLink(activeLink === l ? null : l)}
                    >
                      {l}
                    </Button>
                  ))}
                </div>
                {activeLink ? (
                  linked.isLoading ? <Skeleton rows={2} />
                  : linked.error ? <ErrorBanner error={linked.error} />
                  : (linked.data ?? []).length === 0 ? <EmptyState compact title={t('common.empty')} />
                  : (
                    <ul className="flex flex-wrap gap-2">
                      {(linked.data ?? []).map((row, i) => {
                        const otherPk = pkOf(row)
                        const otherType = linkedType ?? type
                        const otherId = String(row[otherPk])
                        return (
                          <li key={i}>
                            {onSelectObject ? (
                              <button
                                type="button"
                                className="ontogeny-code hover:underline"
                                onClick={() => onSelectObject(otherType, otherId)}
                              >
                                {otherId}
                              </button>
                            ) : (
                              <Link className="ontogeny-code hover:underline" to={`/objects/${otherType}/${encodeURIComponent(otherId)}`}>
                                {otherId}
                              </Link>
                            )}
                          </li>
                        )
                      })}
                    </ul>
                  )
                ) : (
                  <p className="text-[12.5px] muted">{t('object.pickLink')}</p>
                )}
              </>
            )}
          </section>
        </Card>

        <Card padded={false} bodyClassName="[&>section+section]:border-t [&>section+section]:border-[var(--border-subtle)]">
          <section className="p-5">
          <div className="mb-3 flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
            <div className="min-w-0">
              <h3 className="text-[13px] font-semibold tracking-wide">{t('object.egoGraph')}</h3>
              <p className="mt-0.5 text-[12.5px] muted">{t('object.egoGraphHint')}</p>
            </div>
            {ego ? (
              <Button size="sm" onClick={() => egoRun.mutate()} icon={<IconRoute width={13} height={13} />}>
                {t('common.refresh')}
              </Button>
            ) : null}
          </div>
            {egoRun.isPending ? <Skeleton rows={4} /> : null}
            {egoRun.error ? <ErrorBanner error={egoRun.error} /> : null}
            {!ego && !egoRun.isPending ? (
              <Button variant="primary" onClick={() => egoRun.mutate()} data-testid="load-ego" icon={<IconRoute width={14} height={14} />}>
                {t('object.egoLoad')}
              </Button>
            ) : null}
            {ego ? (
              <FlowGraph
                key={`${ego.start.type}/${ego.start.id}/${ego.nodes.length}`}
                data={exploreToFlow(ego)}
                height={540}
                testId="ego-flow"
                onNodeClick={(n) => {
                  const row = ego.nodes.find((x) => `${x._type}/${x._id}` === n.id)
                  if (row) setEgoInspect(row)
                }}
              />
            ) : null}
            <NodeInfoDrawer
              open={egoInspect !== null}
              onClose={() => setEgoInspect(null)}
              title={String(egoInspect?.[pkOf(egoInspect)] ?? '')}
              subtitle={egoInspect ? String(egoInspect._type) : undefined}
              dotColor={egoInspect ? typeColor(String(egoInspect._type)) : undefined}
              items={egoInspect ? Object.entries(egoInspect)
                .filter(([k]) => !k.startsWith('_'))
                .map(([k, v]) => ({ key: k, value: v === null || v === undefined ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v) })) : []}
            />
          </section>
          <section className="p-5">
            <h3 className="mb-3 text-[13px] font-semibold tracking-wide">{t('object.timeline')}</h3>
            {/* a denied history request must not render as "no history": on a
                governance page those two states mean opposite things */}
            {history.isLoading ? <Skeleton rows={3} />
              : history.error ? <ErrorBanner error={history.error} />
              : <Timeline versions={history.data?.versions ?? []} />}
          </section>
        </Card>
      </div>
      {embedded ? null : (
        <ObjectsDialog type={browse ? type : null} onClose={() => setBrowse(false)} />
      )}
    </>
  )
}
