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
 * NeighbourhoodDialog — the 2-hop popup behind a double-click on a graph node.
 *
 * A single click inspects one node (drawer); a double click asks the engine for
 * that node's immediate surroundings instead: 2 hops, 10 nodes, re-laid out at
 * BFS depth from the clicked node. It is a dialog rather than a page because it
 * is a *detour* — the exploration canvas behind it keeps its state, and the
 * dialog's own canvas can be drilled into again (double-click a node inside it
 * re-roots the neighbourhood).
 */
import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import { useI18n } from '../i18n'
import { useFocusTrap } from '../lib/focus'
import { Badge, Button, Skeleton } from './ui'
import { ErrorBanner } from './ErrorBanner'
import { ExploreGraph } from './ExploreGraph'
import { typeColor, pkOf } from '../lib/rows'
import { IconNetwork, IconX } from './icons'

/** 2 hops, 10 nodes: "the node and what it touches, and what those touch". */
const HOPS = 2
const NODES = 10

export interface NeighbourhoodTarget {
  type: string
  id: string
  /** Primary-key value, for the header (the id is the internal one). */
  label?: string
}

export function NeighbourhoodDialog({
  node, onClose,
}: {
  node: NeighbourhoodTarget | null
  onClose: () => void
}) {
  const { t } = useI18n()
  const ref = useFocusTrap<HTMLDivElement>(node !== null)
  // the dialog can be re-rooted from inside; `root` is what is actually shown.
  // The parent keys the dialog by the node it was opened on, so opening another
  // node remounts it and this initial value is always the right one.
  const [root, setRoot] = useState<NeighbourhoodTarget | null>(node)

  useEffect(() => {
    if (!node) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [node, onClose])

  const result = useQuery({
    queryKey: ['graph-neighbourhood', root?.type, root?.id, HOPS, NODES],
    queryFn: () => apiClient.explore({ start_type: root!.type, start_id: root!.id, n: NODES, max_depth: HOPS }),
    enabled: root !== null,
  })

  if (!node || !root) return null

  const data = result.data

  return createPortal(
    <div
      className="fixed inset-0 z-50 grid place-items-center p-4"
      style={{ background: 'rgba(0,0,0,.45)' }}
      data-testid="neighbourhood-overlay"
      onClick={onClose}
    >
      <div
        ref={ref}
        role="dialog"
        aria-modal="true"
        aria-label={t('graph.neighbourhood.title')}
        data-testid="neighbourhood-dialog"
        className="ontogeny-card ontogeny-modal flex max-h-[88vh] w-full max-w-4xl flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <header
          className="flex shrink-0 items-start justify-between gap-3 px-5 py-3.5"
          style={{ borderBottom: '1px solid var(--border-subtle)' }}
        >
          <div className="flex min-w-0 items-center gap-2.5">
            <span className="size-3 shrink-0 rounded-full" style={{ background: typeColor(root.type) }} />
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <IconNetwork width={14} height={14} />
                <h2 className="text-[14px] font-semibold">{t('graph.neighbourhood.title')}</h2>
              </div>
              <div className="mt-0.5 truncate font-mono text-[11.5px] muted">
                {root.type} · {root.label ?? root.id}
              </div>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {data ? <Badge tone="neutral">{t('graph.explore.stat', { nodes: data.nodes.length, edges: data.edges.length })}</Badge> : null}
            <Button size="sm" onClick={onClose} data-testid="neighbourhood-close" icon={<IconX width={13} height={13} />}>
              {t('common.close')}
            </Button>
          </div>
        </header>

        <div className="flex min-h-0 flex-1 flex-col gap-2 px-4 py-3">
          <p className="shrink-0 text-[11.5px] muted">{t('graph.neighbourhood.hint', { hops: HOPS, nodes: NODES })}</p>
          {result.error ? <ErrorBanner error={result.error} /> : null}
          <div
            className="ontogeny-canvas-grid relative min-h-[320px] flex-1 overflow-hidden rounded-xl"
            style={{ border: '1px solid var(--border-subtle)', height: 'min(56vh, 520px)' }}
          >
            {result.isLoading ? (
              <div className="p-4"><Skeleton rows={5} /></div>
            ) : data ? (
              <ExploreGraph
                result={data}
                fill
                onNodeDoubleClick={(row) => setRoot({
                  type: row._type,
                  id: row._id,
                  label: String(row[pkOf(row)] ?? row._id),
                })}
              />
            ) : null}
          </div>
        </div>
      </div>
    </div>,
    document.body,
  )
}
