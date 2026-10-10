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
/** Adapters: API payloads -> FlowGraphData.
 *
 * Layouts are deterministic (BFS-depth columns, grid, radial) so tests can
 * assert on them; users rearrange by dragging afterwards. */
import type { ExploreResult, OntologyMeta, OntologyResource, ProjectionSummary, TraverseResult } from '../api/types'
import { asList, asObj, asStr, asStrList } from '../api/resources'
import { pkOf } from '../lib/rows'
import dagre from '@dagrejs/dagre'
import { fitText, measureTextWidth } from './textMetrics'
import { ENTITY_METRICS, entityHeight, entityTextWidth, entityWidth } from './EntityCardNode'
import type { FlowGraphData, FlowGraphEdge, FlowGraphNode } from './FlowGraph'

/** Instance neighbourhood from /graph/explore: BFS-depth columns from start. */
export function exploreToFlow(result: ExploreResult): FlowGraphData {
  const nodes: FlowGraphNode[] = result.nodes.map((n) => {
    const key = pkOf(n)
    return {
      id: `${n._type}/${n._id}`,
      label: String(n[key] ?? n._id),
      sublabel: n._type,
      type: n._type,
      start: n._type === result.start.type && n._id === result.start.id,
    }
  })
  return {
    nodes,
    edges: result.edges.map((e) => ({
      source: `${e.source.type}/${e.source.id}`,
      target: `${e.target.type}/${e.target.id}`,
      label: e.link,
    })),
    layout: 'layered',
  }
}

/** Walk result from /graph/traverse: one column per hop. */
export function traverseToFlow(result: TraverseResult): FlowGraphData {
  const seen = new Set<string>()
  const nodes: FlowGraphNode[] = []
  result.steps.forEach((step, depth) => {
    for (const row of step.objects) {
      const pk = pkOf(row)
      const id = `${step.type}/${row[pk]}`
      if (seen.has(id)) continue
      seen.add(id)
      nodes.push({
        id,
        label: String(row[pk]),
        sublabel: step.type,
        type: step.type,
        start: depth === 0,
      })
    }
  })
  return {
    nodes,
    edges: (result.edges ?? []).map((e) => ({
      source: `${e.source.type}/${e.source.id}`,
      target: `${e.target.type}/${e.target.id}`,
      label: e.link,
    })),
    layout: 'layered',
  }
}

/** Ontology schema: object types + their links, drawn as one card per type.
 *
 * The compiled meta lists a LinkType on every endpoint it touches, so a link
 * is emitted once and rendered undirected (see FlowGraph's schema edges). A
 * link whose other endpoint is not a declared object type is skipped — there
 * is no node to attach it to. */
export function schemaToFlow(meta: OntologyMeta): FlowGraphData {
  const nodes: FlowGraphNode[] = Object.entries(meta.objects).map(([name, obj]) => ({
    id: `type:${name}`,
    label: name,
    display: obj.display,
    sublabel: `${Object.keys(obj.properties).length}p · ${obj.links.length}l · ${obj.actions.length}a`,
    stats: {
      props: Object.keys(obj.properties).length,
      links: obj.links.length,
      actions: obj.actions.length,
    },
    type: name,
  }))
  const seen = new Set<string>()
  const edges: FlowGraphData['edges'] = []
  for (const [name, obj] of Object.entries(meta.objects)) {
    for (const link of obj.links) {
      if (seen.has(link)) continue
      seen.add(link)
      const other = Object.keys(meta.objects).find(
        (o) => o !== name && meta.objects[o].links.includes(link),
      )
      if (other) edges.push({ source: `type:${name}`, target: `type:${other}`, label: link })
    }
  }
  return { nodes, edges: orientUndirectedLinks(nodes, edges), layout: 'schema', nodeStyle: 'card' }
}

/** Give every undirected schema link a *meaningful* direction before layout.
 *
 * A LinkType has no recoverable source→target — the meta simply lists it on
 * both endpoints — so the loop above emits each link in whichever direction the
 * declaration order happened to produce. Layered layouts (dagre) need a DAG, so
 * an arbitrary orientation turns many links into multi-rank back-edges that
 * sweep across the whole drawing and cross everything in their path: that is
 * exactly why the schema drew with crossing lines.
 *
 * Orienting each link away from a BFS root — the best-connected type of its
 * connected component, ties broken by declaration order — makes dagre rank by
 * real hop distance from that hub, which is what lets it produce a
 * crossing-free drawing. Purely cosmetic: schema edges render without
 * arrowheads, so the direction is never shown. Deterministic: the same package
 * yields the same orientation (and therefore the same layout) every time. */
export function orientUndirectedLinks(
  nodes: FlowGraphNode[],
  edges: FlowGraphEdge[],
): FlowGraphEdge[] {
  const ids = nodes.map((n) => n.id)
  const adjacency = new Map<string, string[]>(ids.map((id) => [id, []]))
  for (const e of edges) {
    adjacency.get(e.source)?.push(e.target)
    adjacency.get(e.target)?.push(e.source)
  }

  const parent = new Map<string, string | null>()
  const depth = new Map<string, number>()
  const visited = new Set<string>()

  for (const start of ids) {
    if (visited.has(start)) continue
    // 1. the whole connected component this type belongs to
    const members = new Set<string>()
    const stack = [start]
    visited.add(start)
    while (stack.length) {
      const u = stack.pop()!
      members.add(u)
      for (const v of adjacency.get(u) ?? []) {
        if (visited.has(v)) continue
        visited.add(v)
        stack.push(v)
      }
    }
    // 2. root it at the best-connected member (ties: first declared)
    let root = start
    let bestDegree = -1
    for (const id of ids) {
      if (!members.has(id)) continue
      const degree = adjacency.get(id)?.length ?? 0
      if (degree > bestDegree) {
        bestDegree = degree
        root = id
      }
    }
    // 3. BFS from the root: tree parent + hop depth for every member
    parent.set(root, null)
    depth.set(root, 0)
    const queue = [root]
    for (let i = 0; i < queue.length; i += 1) {
      const u = queue[i]
      for (const v of adjacency.get(u) ?? []) {
        if (parent.has(v)) continue
        parent.set(v, u)
        depth.set(v, (depth.get(u) ?? 0) + 1)
        queue.push(v)
      }
    }
  }

  // Parent before child; links that close a cycle keep the shallow→deep
  // direction, and same-depth links fall back to id order so the result never
  // depends on hash iteration order.
  return edges.map((e) => {
    if (parent.get(e.source) === e.target) return { ...e, source: e.target, target: e.source }
    if (parent.get(e.target) === e.source) return e
    const ds = depth.get(e.source) ?? 0
    const dt = depth.get(e.target) ?? 0
    if (ds < dt) return e
    if (dt < ds) return { ...e, source: e.target, target: e.source }
    return e.source <= e.target ? e : { ...e, source: e.target, target: e.source }
  })
}

/** Projection schema: vertex labels + edge labels with directions. */
export function projectionToFlow(summary: ProjectionSummary): FlowGraphData {
  const nodes: FlowGraphNode[] = (summary.labels?.vertices ?? []).map((v) => ({
    id: `v:${v.name}`,
    label: v.name,
    sublabel: (v.primary_keys ?? []).join(', '),
    type: v.name,
  }))
  const edges: FlowGraphData['edges'] = (summary.labels?.edges ?? [])
    .filter((e) => e.source_label && e.target_label)
    .map((e) => ({
      source: `v:${e.source_label}`,
      target: `v:${e.target_label}`,
      label: e.name,
    }))
  return { nodes, edges, layout: 'schema' }
}

/* ------------------------------------------------- ontology workbench graph */

/** Stable id of a graph node in the ontology workbench. */
export const ontNodeId = {
  object: (name: string) => `type:${name}`,
  action: (name: string) => `action:${name}`,
  function: (name: string) => `function:${name}`,
  link: (name: string) => `link:${name}`,
  policy: (name: string) => `policy:${name}`,
  projection: (name: string) => `projection:${name}`,
}

/** What a clicked node refers to — the panel switches on this. */
export interface OntologyNodeRef {
  kind: 'object' | 'action' | 'function' | 'link' | 'policy' | 'projection'
  name: string
}

export function parseOntNodeId(id: string): OntologyNodeRef | null {
  const [prefix, ...rest] = id.split(':')
  const name = rest.join(':')
  if (!name) return null
  if (prefix === 'type') return { kind: 'object', name }
  if (prefix === 'action') return { kind: 'action', name }
  if (prefix === 'function') return { kind: 'function', name }
  if (prefix === 'link') return { kind: 'link', name }
  if (prefix === 'policy') return { kind: 'policy', name }
  if (prefix === 'projection') return { kind: 'projection', name }
  return null
}

/** The ontology as one graph: object types, their actions and their functions.
 *
 * **What is drawn.** Object types (the nouns) plus the actions and functions
 * attached to them. Policies and projections are deliberately NOT nodes: a
 * policy is a property of an action ("who may run it") and a projection is a
 * property of a set of object types, so they are shown *on* those nodes — in
 * the detail panel, and in the action's own label — instead of floating beside
 * them as more boxes to read. Six kinds of box in one drawing was the single
 * biggest source of visual noise; two kinds plus their satellites is a model
 * you can follow.
 *
 * **Size follows text.** Each box is measured (textMetrics.ts, with the font
 * the canvas draws with) and handed to G6 as its size, so a short name gets a
 * small box and `equipment-maintenance-orders` a wide one.
 *
 * **Line style carries the model's own distinction**: a LinkType between two
 * object types is an *entity relationship* (solid, ink); an action targeting a
 * type or a function reading it is auxiliary (dashed, orange).
 *
 * **Layout minimises crossings.** Nodes are placed by a layered (Sugiyama-style)
 * pass — entity links decide the layers, a barycenter sweep orders each layer —
 * rather than dropped into a grid. A grid puts a type and the type it links to
 * in arbitrary cells, which is exactly how a drawing ends up with a dozen long
 * diagonal lines through everything.
 */
export function ontologyToFlow(
  resources: OntologyResource[],
  positions: Record<string, { x: number; y: number }> = {},
  objectColor = '#2e5bff',
): FlowGraphData {
  const nodes: FlowGraphNode[] = []
  const edges: FlowGraphEdge[] = []
  const objects = resources.filter((r) => r.kind === 'ObjectType')
  const actions = resources.filter((r) => r.kind === 'Action')
  const functions = resources.filter((r) => r.kind === 'Function')
  const linkTypes = resources.filter((r) => r.kind === 'LinkType')

  const objectNames = new Set(objects.map((r) => r.metadata.name))
  const actionsOf = (type: string) => actions.filter((a) => asStr(a.spec.target) === type)
  const functionsOf = (type: string) => functions.filter((f) => functionReads(f).includes(type))

  /* ---- geometry ---------------------------------------------------------
   * A box is as wide as its name needs, within limits, and always one grid
   * cell tall so the layout is a grid rather than a ragged pile. */
  const FONT = 13
  const PAD = 12
  const ICON = 20
  const GAP = 7
  const MIN_W = 116
  const MAX_W = 208
  /** Vertical breathing room above and below the text block. */
  const PAD_Y = 14
  /** A one-line box is this tall; taller labels grow by whole lines. */
  const MIN_H = 40
  /** The display-name tag row under the title (same numbers as CardNode's
   *  drawing code — the layout reserves the room that the element draws into). */
  const TAG_GAP = 6
  const TAG_H = 18
  const TAG_PAD_X = 7
  const TAG_FONT = 10.5

  const boxWidth = (name: string, max = MAX_W, font = FONT, icon = ICON, minW = MIN_W) => {
    const inner = measureTextWidth(name, font) + icon + GAP
    return Math.round(Math.min(max, Math.max(minW, inner + PAD * 2)))
  }

  /** A box's real footprint: width from the longest word, height from how many
   *  lines the name actually wraps to.
   *
   * This is what stops a box looking empty. A fixed 60px box gave `bom` 43px of
   * dead space above and below its one line of text, while
   * `close-maintenance-order` needed three lines and got clipped. Height now
   * follows the wrapped line count, so every box is exactly as tall as its
   * content plus padding — and the same `fitText` the element wraps with is
   * what decides it, so the reserved cell and the drawing cannot agree. A
   * `tag` (the display-name capsule) adds one more row, and its own width can
   * widen a short box so the capsule is not truncated for nothing.
   *
   * The measured `lines` ride along: the card element draws exactly this many
   * instead of re-deriving a count from the box height (a min-height clamp
   * would otherwise read as an extra wrapped line and shove the tag out of the
   * box). */
  const boxDims = (label: string, max = MAX_W, tag?: string, minH = MIN_H, font = FONT, icon = ICON, minW = MIN_W) => {
    let w = boxWidth(label, max, font, icon, minW)
    // the tag's own width can widen a short box so the capsule is not
    // truncated for nothing (it still respects the max)
    if (tag) {
      const tagW = Math.ceil(measureTextWidth(tag, TAG_FONT)) + TAG_PAD_X * 2 + PAD * 2 + icon + GAP
      w = Math.round(Math.min(max, Math.max(w, tagW)))
    }
    // Measured with the SAME font and icon the card will DRAW (hosts: 13px +
    // 20px icon; satellites draw smaller, see below) — a size measured at one
    // scale and drawn at another is what left phantom empty rows inside cards.
    // `rows` are the pre-wrapped lines: the card draws them verbatim instead of
    // letting the canvas re-wrap, so measure and draw cannot disagree at a
    // borderline width. The +1 slack keeps a name whose measured width lands
    // within a rounding step of the box from spilling its last letter onto a
    // second line (rows may paint a hair into the padding — invisible).
    const innerW = w - PAD * 2 - icon - GAP
    const { lines, rows } = fitText(label, innerW + 1, font, 3)
    const h = Math.max(minH, Math.round(lines * font * 1.28 + PAD_Y)) + (tag ? TAG_GAP + TAG_H : 0)
    return { w, h, lines, rows }
  }

  /** The object-type (HTML) card's footprint, measured with EntityCardNode's
   *  own metrics: title rows wrapped to the text column, the display-name
   *  capsule row under them, the rail + chip column on the left.
   *
   * Width and wrap are mutually dependent (a narrower card wraps more, which is
   * narrower still). Solving it from the widest column downwards converges in a
   * couple of steps and always terminates: wrapping can only shorten the
   * longest row, so the computed width only ever decreases. */
  const entityBoxDims = (text: string) => {
    const M = ENTITY_METRICS
    let w: number = M.maxW
    let fit = fitText(text, entityTextWidth(w), M.titleFont, 3)
    for (let i = 0; i < 3; i += 1) {
      const longest = fit.rows.reduce((n, r) => Math.max(n, measureTextWidth(r, M.titleFont)), 0)
      const next = entityWidth(longest)
      if (next === w) break
      w = next
      fit = fitText(text, entityTextWidth(w), M.titleFont, 3)
    }
    return { w, h: entityHeight(fit.lines), lines: fit.lines, rows: fit.rows }
  }

  /* ---- layout -----------------------------------------------------------
   * Dagre does the layered pass. Hand-rolling it (BFS layering + one barycenter
   * sweep) produced a vertical cascade with long crossing edges: layering by
   * longest path puts every node with no incoming link in rank 0, which for a
   * supply chain is half the model. Dagre runs the real Sugiyama pipeline
   * (acyclic → layering → ordering → positioning), and the existing
   * `orientUndirectedLinks` gives it the DAG it needs by orienting each
   * undirected LinkType away from the best-connected type in its component.
   *
   * Each host reserves the space for its satellites by entering dagre with an
   * inflated box, so dagre's crossing minimisation sees the *real* footprint
   * and never overlaps a satellite with the next rank.
   */
  const BOX_GAP_X = 92
  const BOX_GAP_Y = 26
  /** Gap between a host box and its first satellite. */
  const SAT_TOP = 12
  /** Gap between two stacked satellites. */
  const SAT_GAP = 10

  /** Satellites of one host, in draw order: actions then functions. `display`
   *  is what the card prints (the human name), `label` stays the kebab id. */
  const satellitesOf = (type: string) => [
    ...actionsOf(type).map((a) => ({
      id: ontNodeId.action(a.metadata.name),
      label: a.metadata.name,
      display: a.metadata.display?.trim() || a.metadata.name,
      description: a.metadata.description?.trim() || undefined,
      kind: 'action' as const,
      sublabel: asStr(a.spec.policy) || type,
    })),
    ...functionsOf(type).map((f) => ({
      id: ontNodeId.function(f.metadata.name),
      label: f.metadata.name,
      display: f.metadata.display?.trim() || f.metadata.name,
      description: f.metadata.description?.trim() || undefined,
      kind: 'function' as const,
      sublabel: asStr(f.spec.entry),
    })),
  ]

  // A function that reads several types is ONE node. Decide *once*, up front,
  // which host draws it — the alphabetically first type that reads it, so the
  // choice is deterministic — and keep that map. (Deciding lazily inside a
  // filter made the helper stateful: a second call would return a different
  // answer, which is exactly the kind of thing that breaks on a later edit.)
  const owner = new Map<string, string>()
  for (const o of objects) {
    for (const sat of satellitesOf(o.metadata.name)) {
      const current = owner.get(sat.id)
      if (current === undefined || o.metadata.name < current) owner.set(sat.id, o.metadata.name)
    }
  }
  const satsFor = (type: string) => satellitesOf(type).filter((sat) => owner.get(sat.id) === type)

  const dagreGraph = new dagre.graphlib.Graph()
  dagreGraph.setGraph({ rankdir: 'LR', nodesep: BOX_GAP_Y, ranksep: BOX_GAP_X, marginx: 0, marginy: 0 })
  dagreGraph.setDefaultEdgeLabel(() => ({}))

  const entityEdges = linkTypes
    .map((l) => ({ source: asStr(l.spec.source), target: asStr(l.spec.target) }))
    .filter((e) => objectNames.has(e.source) && objectNames.has(e.target) && e.source !== e.target)

  // Orient the undirected links into a DAG (reuses the schema-graph helper).
  const oriented = orientUndirectedLinks(
    objects.map((o) => ({ id: o.metadata.name, label: o.metadata.name })),
    entityEdges.map((e) => ({ source: e.source, target: e.target })),
  )

  /** Every box's own footprint, plus the block it reserves in the layout. */
  interface Box { w: number; h: number; lines: number; rows: string[]; sats: Array<{ id: string; label: string; display: string; description?: string; kind: 'action' | 'function'; sublabel: string; w: number; h: number; lines: number; rows: string[] }> }
  const boxOf = new Map<string, Box>()
  for (const o of objects) {
    const name = o.metadata.name
    // the card's text is the DISPLAY name (维修工单, not maintenance-order):
    // it is what the modeller named the thing for humans. Falls back to the id.
    const display = o.metadata.display?.trim()
    // OBJECT TYPES are drawn as HTML cards (EntityCardNode), whose metrics live
    // in that module: measuring them with the satellite numbers here would size
    // a card the element then fills differently. One source feeds both sides.
    const dims = entityBoxDims(display && display.length ? display : name)
    // satellites are DRAWN at 12px with a per-kind glyph (action 21, function
    // 20 — bigger than before, the function a step under the action), so they
    // are measured with exactly those numbers
    const sats = satsFor(name).map((x) => ({
      ...x,
      // measure the DISPLAY text: it is what the card prints
      ...boxDims(x.display, 168, undefined, 34, 12, x.kind === 'action' ? 21 : 20),
    }))
    // the reserved cell is as wide as the widest thing drawn in it, and as tall
    // as the host plus its satellite stack
    const w = Math.max(dims.w, ...sats.map((x) => x.w))
    const h = dims.h + (sats.length ? SAT_TOP + sats.reduce((n, x) => n + x.h + SAT_GAP, 0) - SAT_GAP : 0)
    boxOf.set(name, { w: dims.w, h: dims.h, lines: dims.lines, rows: dims.rows, sats })
    dagreGraph.setNode(name, { width: w, height: h })
  }
  for (const e of oriented) dagreGraph.setEdge(e.source, e.target)

  dagre.layout(dagreGraph)

  objects.forEach((r) => {
    const name = r.metadata.name
    const box = boxOf.get(name)!
    const { w: cellW, sats } = box
    const cellH = box.h + (sats.length ? SAT_TOP + sats.reduce((n, x) => n + x.h + SAT_GAP, 0) - SAT_GAP : 0)
    const pos = dagreGraph.node(name) ?? { x: 0, y: 0 }
    // dagre reports the CENTRE of the reserved cell; the host box sits at its
    // top and the satellites stack below it
    const hostCx = pos.x
    const hostCy = pos.y - cellH / 2 + box.h / 2
    const pinned = positions[ontNodeId.object(name)]
    const props = Object.keys(asObj(r.spec.properties))
    // the description rides on the node for the canvas's hover readout
    const description = r.metadata.description?.trim() || undefined
    void cellW

    nodes.push({
      id: ontNodeId.object(name),
      label: name,
      display: r.metadata.display ?? undefined,
      description,
      type: name,
      kind: 'object',
      color: objectColor,
      sublabel: `${props.length}p`,
      stats: { props: props.length, links: 0, actions: actionsOf(name).length },
      size: [box.w, box.h],
      labelLines: box.lines,
      labelWrapped: box.rows,
      x: pinned?.x ?? hostCx,
      y: pinned?.y ?? hostCy,
    })

    // stack the satellites, each at its own height
    let cursor = hostCy + box.h / 2 + SAT_TOP
    sats.forEach((sat) => {
      const sp = positions[sat.id]
      const cy = cursor + sat.h / 2
      cursor += sat.h + SAT_GAP
      nodes.push({
        id: sat.id,
        label: sat.label,
        display: sat.display,
        description: sat.description,
        sublabel: sat.sublabel,
        type: sat.kind,
        kind: sat.kind,
        size: [sat.w, sat.h],
        labelLines: sat.lines,
        labelWrapped: sat.rows,
        x: sp?.x ?? hostCx,
        y: sp?.y ?? cy,
      })
      // An action targets exactly one type, so its host owns the edge. A
      // function may read several, so its edges are emitted once, below.
      if (sat.kind === 'action') {
        // the ACTION acts on the object: the arrow points at the object
        edges.push({ source: sat.id, target: ontNodeId.object(name), dashed: true, arrow: 'end' })
      }
    })
  })

  // every type a function reads gets its own dashed edge, wherever the function
  // box ended up: the capability is the relationship, not the placement
  for (const f of functions) {
    const id = ontNodeId.function(f.metadata.name)
    if (!nodes.some((n) => n.id === id)) continue
    for (const ty of functionReads(f)) {
      if (objectNames.has(ty)) edges.push({ source: ontNodeId.object(ty), target: id, dashed: true, arrow: 'end' })
    }
  }

  // links: one directed edge per LinkType, drawn solid (an entity relationship)
  const linkEdges: FlowGraphEdge[] = []
  for (const l of linkTypes) {
    const source = asStr(l.spec.source)
    const target = asStr(l.spec.target)
    if (!objectNames.has(source) || !objectNames.has(target)) continue
    linkEdges.push({
      id: ontNodeId.link(l.metadata.name),
      source: ontNodeId.object(source),
      target: ontNodeId.object(target),
      label: l.metadata.name,
      dashed: false,
    })
  }

  // Direction marks: every link gets an arrowhead at its target; when the model
  // also declares the REVERSE link between the same pair, both ends carry one —
  // the pair reads as two-way at a glance instead of looking like a missing
  // arrowhead.
  const directed = new Set(linkEdges.map((e) => `${e.source}\u0000${e.target}`))
  for (const e of linkEdges) {
    e.arrow = directed.has(`${e.target}\u0000${e.source}`) ? 'both' : 'end'
  }
  edges.push(...linkEdges)

  // `entityCards`: object types are drawn as HTML cards here, which is only
  // sound because every box above was measured per node (see entityBoxDims).
  // Arrowheads are WANTED on this canvas — direction is part of the model — so
  // `quietEdges` is no longer set.
  return { nodes, edges, layout: 'preset', nodeStyle: 'card', entityCards: true }
}

function functionReads(f: OntologyResource): string[] {
  const out: string[] = []
  for (const cap of asList(f.spec.capabilities)) {
    for (const ty of asStrList(asObj(cap)['read-objects'])) out.push(ty)
  }
  return out
}
