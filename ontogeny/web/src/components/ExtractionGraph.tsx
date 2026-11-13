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
/** Extracted graph with a graph / JSON switch.
 *
 * The graph is the readable view (same canvas as the instance explorer); JSON
 * is the exact contract the agent returned and the shape the reviewer edits.
 */
import { useMemo, useState } from 'react'
import { FlowGraph, type FlowGraphData, type FlowGraphEdge, type FlowGraphNode } from './FlowGraph'
import { JsonView } from './JsonView'
import { useI18n } from '../i18n'
import type { ExtractedGraph } from '../api/types'

function labelOf(v: { label?: string; id?: string | number; properties?: Record<string, unknown> }): string {
  const p = v.properties ?? {}
  for (const key of ['name', 'supplier_name', 'display', 'note_id', 'title']) {
    const value = p[key]
    if (value !== undefined && value !== null && String(value) !== '') return String(value)
  }
  return v.id !== undefined ? String(v.id) : v.label ?? '?'
}

export function graphToFlow(graph: ExtractedGraph): FlowGraphData {
  const nodes: FlowGraphNode[] = []
  const keyByRaw = new Map<string, string>()
  const seen = new Set<string>()
  ;(graph.vertices ?? []).forEach((v, i) => {
    const raw = v.id !== undefined ? String(v.id) : `auto-${i}`
    const key = `${v.label ?? 'vertex'}/${raw}`
    if (seen.has(key)) return
    seen.add(key)
    keyByRaw.set(raw, key)
    nodes.push({
      id: key,
      label: labelOf(v),
      sublabel: v.label ?? 'vertex',
      type: v.label ?? 'vertex',
    })
  })
  const edges: FlowGraphEdge[] = (graph.edges ?? []).map((e, i) => {
    const source = keyByRaw.get(String(e.outV)) ?? `${e.outVLabel ?? 'vertex'}/${String(e.outV)}`
    const target = keyByRaw.get(String(e.inV)) ?? `${e.inVLabel ?? 'vertex'}/${String(e.inV)}`
    return {
      id: `edge-${i}`,
      source,
      target,
      label: e.label,
      arrow: 'end' as const,
    }
  }).filter((e) => nodes.some((n) => n.id === e.source) && nodes.some((n) => n.id === e.target))
  return { nodes, edges, layout: 'layered', nodeStyle: 'dot' }
}

export function ExtractionGraph({
  graph,
  jsonValue,
  onJsonChange,
  height = 420,
  testId = 'extraction-graph',
}: {
  graph: ExtractedGraph
  /** When supplied, JSON mode is an editor (review); otherwise read-only. */
  jsonValue?: string
  onJsonChange?: (value: string) => void
  height?: number
  testId?: string
}) {
  const { t } = useI18n()
  const [mode, setMode] = useState<'graph' | 'json'>('graph')
  const data = useMemo(() => graphToFlow(graph), [graph])
  const empty = !data.nodes.length && !data.edges.length
  return (
    <div className="flex min-h-0 flex-col gap-2" data-testid={testId}>
      <div className="flex items-center gap-1 self-start rounded-lg p-0.5" style={{ background: 'var(--surface-sunken)' }}>
        <button
          type="button"
          className="rounded-md px-2 py-1 text-[11px]"
          style={{ background: mode === 'graph' ? 'var(--surface-card)' : 'transparent', color: mode === 'graph' ? 'var(--text-primary)' : 'var(--text-muted)' }}
          onClick={() => setMode('graph')}
          data-testid={`${testId}-graph`}
        >
          {t('documents.view.graph')}
        </button>
        <button
          type="button"
          className="rounded-md px-2 py-1 text-[11px]"
          style={{ background: mode === 'json' ? 'var(--surface-card)' : 'transparent', color: mode === 'json' ? 'var(--text-primary)' : 'var(--text-muted)' }}
          onClick={() => setMode('json')}
          data-testid={`${testId}-json`}
        >
          {t('documents.view.json')}
        </button>
      </div>
      {mode === 'graph' ? (
        empty ? (
          <p className="p-3 text-[12px] muted">{t('documents.runs.noGraph')}</p>
        ) : (
          <FlowGraph data={data} height={height} testId={`${testId}-canvas`} />
        )
      ) : jsonValue !== undefined ? (
        <textarea
          className="ontogeny-input min-h-[280px] w-full font-mono text-[11.5px]"
          value={jsonValue}
          onChange={(e) => onJsonChange?.(e.target.value)}
          spellCheck={false}
          data-testid={`${testId}-json-editor`}
        />
      ) : (
        <JsonView value={graph} />
      )}
    </div>
  )
}
