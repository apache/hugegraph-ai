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
/** Instance-graph views for /graph — thin wrappers over the shared FlowGraph
 * canvas (React Flow): drag, zoom/pan, minimap, click-to-highlight all come
 * from the one component; this file only maps payloads to nodes/edges. */
import { Link } from 'react-router-dom'
import { FlowGraph } from './FlowGraph'
import { pkOf, typeColor } from '../lib/rows'
import { exploreToFlow } from './graphAdapters'
import { Badge } from './ui'
import { useI18n } from '../i18n'
import type { ExploreResult } from '../api/types'

/** The explored neighbourhood on the shared canvas. `onNodeClick` receives the
 * full assembled object row (masking applied) for the info drawer. */
export function ExploreGraph({ result, onNodeClick, onNodeDoubleClick, fill = false }: {
  result: ExploreResult
  onNodeClick?: (node: Record<string, unknown> & { _type: string; _id: string }) => void
  /** Double-click asks for a *deeper* neighbourhood of that node (popup). */
  onNodeDoubleClick?: (node: Record<string, unknown> & { _type: string; _id: string }) => void
  /** Size to the parent box instead of a fixed height (full-bleed page). */
  fill?: boolean
}) {
  const { t } = useI18n()
  const rowOf = (n: { sublabel?: string; id: string }) =>
    result.nodes.find((x) => x._type === n.sublabel && x._id === n.id.split('/').slice(1).join('/'))
  return (
    <div className="relative h-full" data-testid="explore-graph">
      <FlowGraph
        data={exploreToFlow(result)}
        height={640}
        fill={fill}
        testId="explore-flow"
        onNodeClick={(n) => {
          if (!onNodeClick) return
          const row = rowOf(n)
          if (row) onNodeClick(row)
        }}
        onNodeDoubleClick={(n) => {
          if (!onNodeDoubleClick) return
          const row = rowOf(n)
          if (row) onNodeDoubleClick(row)
        }}
      />
      {/* type key, on the canvas like the ontology legend */}
      <div className="pointer-events-none absolute bottom-4 left-4 z-10 flex max-w-[calc(100%-2rem)] flex-wrap items-center gap-1.5 rounded-xl px-2.5 py-1.5"
        style={{ background: 'var(--surface-card)', border: '1px solid var(--border-subtle)', boxShadow: 'var(--shadow-float)' }}
      >
        <span className="text-[10.5px] font-semibold uppercase tracking-[0.06em] muted">{t('graph.legend')}</span>
        {Array.from(new Set(result.nodes.map((n) => n._type))).map((ty) => (
          <Badge key={ty} mono>
            <span className="mr-1 inline-block size-2 rounded-full align-middle" style={{ background: typeColor(ty) }} />
            {ty}
          </Badge>
        ))}
      </div>
    </div>
  )
}

/** Chip list of the explored nodes with links into the object pages.
 *
 * This is the canvas's text equivalent — the same nodes as real links — so a
 * keyboard or screen-reader user reaches the result without the canvas. It is
 * an `aria-live` region because the result arrives from a mutation, and the list
 * is rendered *before* the canvas in the page so it is reached first. */
export function ExploreNodeList({ result }: { result: ExploreResult }) {
  const { t } = useI18n()
  const label = t('graph.nodeListLabel', { nodes: result.nodes.length })
  return (
    <ul
      className="flex flex-wrap gap-1.5"
      data-testid="explore-nodes"
      aria-live="polite"
      aria-label={label}
    >
      {result.nodes.map((n) => {
        const isStart = n._type === result.start.type && n._id === result.start.id
        return (
          <li key={`${n._type}/${n._id}`}>
            <Link
              className="ontogeny-code hover:underline"
              to={`/objects/${n._type}/${encodeURIComponent(String(n[pkOf(n)] ?? n._id))}`}
              style={isStart ? { boxShadow: 'inset 0 0 0 1px var(--color-brand-500)' } : undefined}
            >
              {isStart ? '\u2605 ' : ''}{String(n[pkOf(n)] ?? n._id)}
              <span className="muted ml-1">{n._type}</span>
            </Link>
          </li>
        )
      })}
    </ul>
  )
}
