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
import { describe, expect, it, beforeEach } from 'vitest'
import { renderWithProviders } from '../test/render'
import { FlowGraph } from './FlowGraph'
import { exploreToFlow, orientUndirectedLinks, schemaToFlow, traverseToFlow } from './graphAdapters'

const DATA = {
  nodes: [
    { id: 'sales-order/SO-1', label: 'SO-1', sublabel: 'sales-order', type: 'sales-order', start: true },
    { id: 'production-order/PO-1', label: 'PO-1', sublabel: 'production-order', type: 'production-order' },
    { id: 'operation/OP-1', label: 'OP-1', sublabel: 'operation', type: 'operation' },
  ],
  edges: [
    { source: 'sales-order/SO-1', target: 'production-order/PO-1', label: 'production-order-sales-order' },
    { source: 'production-order/PO-1', target: 'operation/OP-1', label: 'production-order-operations' },
  ],
  layout: 'layered' as const,
}

const g6 = () => (globalThis as any).__ooG6

const renderGraph = () => {
  const onNodeClick = (node: unknown) => (globalThis as any).__clicked = node
  ;(globalThis as any).__clicked = null
  renderWithProviders(<FlowGraph data={DATA} height={300} onNodeClick={onNodeClick} />, { path: '/' })
  return g6()
}

describe('FlowGraph (G6 engine)', () => {
  beforeEach(() => { (globalThis as any).__ooG6Created = [] })

  it('creates a G6 graph with the full node/edge payload', async () => {
    renderGraph()
    await Promise.resolve()
    const g = g6()
    expect(g).toBeTruthy()
    expect(g.cfg.data.nodes).toHaveLength(3)
    expect(g.cfg.data.edges).toHaveLength(2)
    // behaviours: drag/zoom + minimap plugin
    expect(g.cfg.behaviors).toContain('drag-canvas')
    expect(g.cfg.behaviors).toContain('zoom-canvas')
    expect(g.cfg.behaviors).toContain('drag-element')
    expect(g.cfg.plugins.some((p: any) => p.type === 'minimap')).toBe(true)
  })

  it('never fades a node through a state (G6 does not restore opacity)', async () => {
    // Regression: `inactive: { opacity: 0.16 }` was a one-way ratchet — G6 v5
    // clears the state list but leaves the shape at the faded opacity, so every
    // node you ever clicked stayed washed out for the rest of the session.
    // Selection must read as weight, never as fading the rest.
    renderGraph()
    await Promise.resolve()
    const nodeStates = g6().cfg.node.state ?? {}
    for (const [name, style] of Object.entries(nodeStates)) {
      expect((style as Record<string, unknown>).opacity, `node state "${name}" must not set opacity`).toBeUndefined()
    }
    expect(nodeStates.inactive).toBeUndefined()
    // the selected node is emphasised by weight instead
    expect(nodeStates.selected.lineWidth).toBeGreaterThan(g6().cfg.node.style({ data: {} }).lineWidth)
  })

  it('maps layouts: organic for instances, dagre for schema', async () => {
    const a = renderWithProviders(<FlowGraph data={DATA} height={300} />, { path: '/' })
    await Promise.resolve()
    expect(g6().cfg.layout.type).toBe('d3-force')
    a.unmount()

    renderWithProviders(
      <FlowGraph data={{ ...DATA, layout: 'schema' }} height={300} />,
      { path: '/' },
    )
    await Promise.resolve()
    expect(g6().cfg.layout.type).toBe('antv-dagre')
    a.unmount?.()
  })

  it('node click raises onNodeClick with the node payload', async () => {
    const g = renderGraph()
    await Promise.resolve()
    g.emitNodeClick('operation/OP-1')
    expect((globalThis as any).__clicked).toMatchObject({
      id: 'operation/OP-1', type: 'operation', label: 'OP-1',
    })
  })

  it('schema adapter: dagre layout for the ontology graph', () => {
    const flow = schemaToFlow({
      package: 'p', content_hash: 'h',
      objects: {
        a: { primaryKey: ['a_id'], properties: {}, links: ['a-b'], actions: [] },
        b: { primaryKey: ['b_id'], properties: {}, links: ['a-b'], actions: [] },
      },
      actions: {}, functions: {}, projections: {},
    })
    expect(flow.nodes).toHaveLength(2)
    expect(flow.edges).toHaveLength(1)
    expect(flow.layout).toBe('schema')
  })
  it('traverse adapter: steps -> layered nodes with the edges payload', () => {
    const flow = traverseToFlow({
      steps: [
        { type: 'sales-order', ids: ['SO-1'], objects: [{ so_id: 'SO-1' }] },
        { type: 'production-order', ids: ['PO-1'], objects: [{ prod_order_id: 'PO-1' }] },
      ],
      edges: [{
        link: 'production-order-sales-order',
        source: { type: 'sales-order', id: 'SO-1' },
        target: { type: 'production-order', id: 'PO-1' },
      }],
      final_ids: ['PO-1'],
    })
    expect(flow.nodes).toHaveLength(2)
    expect(flow.edges[0].source).toBe('sales-order/SO-1')
  })

  it('explore adapter: marks the start node', () => {
    const flow = exploreToFlow({
      start: { type: 'sales-order', id: 'SO-1' }, n_requested: 5, depth: 2, truncated: false,
      nodes: [
        { _type: 'sales-order', _id: 'SO-1', so_id: 'SO-1' },
        { _type: 'production-order', _id: 'PO-1', prod_order_id: 'PO-1' },
      ],
      edges: [{ link: 'production-order-sales-order',
        source: { type: 'sales-order', id: 'SO-1' },
        target: { type: 'production-order', id: 'PO-1' } }],
    })
    expect(flow.nodes.find((n) => n.start)?.id).toBe('sales-order/SO-1')
    expect(flow.edges).toHaveLength(1)
  })
})

/** Schema links are undirected, but dagre needs a DAG: an arbitrary orientation
 *  makes links span ranks and cross. These pin the orientation that keeps the
 *  drawn schema free of crossing lines. */
describe('orientUndirectedLinks', () => {
  const nodes = (...ids: string[]) => ids.map((id) => ({ id, label: id }))

  it('points every link away from the best-connected type', () => {
    // hub is linked to three leaves, each declared *after* its neighbour, so
    // the raw declaration order would orient every link leaf→hub
    const out = orientUndirectedLinks(
      nodes('leaf-a', 'leaf-b', 'leaf-c', 'hub'),
      [
        { source: 'leaf-a', target: 'hub' },
        { source: 'leaf-b', target: 'hub' },
        { source: 'leaf-c', target: 'hub' },
      ],
    )
    expect(out.map((e) => [e.source, e.target])).toEqual([
      ['hub', 'leaf-a'], ['hub', 'leaf-b'], ['hub', 'leaf-c'],
    ])
  })

  it('orients tree links parent→child so dagre gets a real DAG', () => {
    // chain a—b—c—d; b and c both have degree 2, so the first declared (b) roots
    const out = orientUndirectedLinks(
      nodes('a', 'b', 'c', 'd'),
      [
        { source: 'd', target: 'c' },
        { source: 'c', target: 'b' },
        { source: 'b', target: 'a' },
      ],
    )
    expect(out.map((e) => `${e.source}->${e.target}`)).toEqual(['c->d', 'b->c', 'b->a'])
  })

  it('keeps same-depth links deterministic and never mutates the input', () => {
    const input = [
      { source: 'b', target: 'a', label: 'a-b' },
      { source: 'a', target: 'b', label: 'dup' },
    ]
    const snapshot = JSON.parse(JSON.stringify(input))
    const first = orientUndirectedLinks(nodes('a', 'b'), input)
    const second = orientUndirectedLinks(nodes('a', 'b'), input)
    expect(first).toEqual(second)
    expect(input).toEqual(snapshot)
    expect(first.map((e) => `${e.source}->${e.target}`)).toEqual(['a->b', 'a->b'])
    expect(first.map((e) => e.label)).toEqual(['a-b', 'dup'])
  })

  it('roots every connected component, not just the first', () => {
    const out = orientUndirectedLinks(
      nodes('a', 'b', 'x', 'y'),
      [
        { source: 'b', target: 'a' },   // a is degree 1, b degree 1 → 'a' wins (first)
        { source: 'y', target: 'x' },
      ],
    )
    expect(out.map((e) => `${e.source}->${e.target}`)).toEqual(['a->b', 'x->y'])
  })

  it('preserves every edge exactly once', () => {
    const edges = [
      { source: 'c', target: 'a', label: 'l1' },
      { source: 'a', target: 'b', label: 'l2' },
      { source: 'b', target: 'c', label: 'l3' },
    ]
    const out = orientUndirectedLinks(nodes('a', 'b', 'c'), edges)
    expect(out).toHaveLength(edges.length)
    expect(new Set(out.map((e) => e.label))).toEqual(new Set(['l1', 'l2', 'l3']))
    expect(out.every((e) => !edges.some((x) => x.source === e.target && x.target === e.source && x.label !== e.label))).toBe(true)
  })
})
