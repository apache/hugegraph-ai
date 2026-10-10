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
 * FlowGraph — the one graph canvas every graph view shares, rendered by
 * AntV G6 v5 (best-in-class graph engine: built-in layouts, element states,
 * minimap, drag/zoom, canvas hit-testing).
 *
 * Parents describe a graph declaratively ({nodes, edges, layout, nodeStyle});
 * G6 handles the aesthetics: organic force / layered dagre / radial layouts,
 * soft labels, hover tooltips, click-to-highlight with neighbour dimming.
 *
 * Two node styles:
 *  - `dot`  (default) round instance nodes, label underneath — instance graphs;
 *  - `card` rounded schema cards carrying the type name plus a count line —
 *    the ontology/type graphs, where a node *is* a model element.
 *
 * Re-mount on data change (pass a `key`) — a new query is a new graph, and
 * drag positions should not leak across queries.
 */
import { useEffect, useRef } from 'react'
import { Graph } from '@antv/g6'
import { useTheme } from '../theme'
import { useI18n } from '../i18n'
import { typeColor, withAlpha } from '../lib/rows'
import { kindColor, kindIconSrc, type NodeKind } from './nodeKinds'
import { registerCardNode } from './CardNode'
import { registerEntityCardNode } from './EntityCardNode'
import { GraphLegend, type GraphLegendItem } from './GraphLegend'
import { IconFit, IconMinus, IconPlus } from './icons'

export interface FlowGraphNode {
  id: string
  label: string
  sublabel?: string
  /** Object type (instance graphs) — drives the colour + minimap colour. */
  type?: string
  /** Which model kind this node draws (ontology graphs): drives the colour and
   *  the icon. Absent on instance graphs, where colour comes from the type. */
  kind?: NodeKind
  /** Marks the origin/ego node with a bigger dot + halo. */
  start?: boolean
  /** Human display name (schema graph: the type's localized name, e.g. 中文名 in zh). */
  display?: string
  /** Business description, for the canvas's hover readout. */
  description?: string
  /** Short text drawn as a capsule tag on a `card` node (the ontology canvas
   *  shows the type's localized display name here, so nodes read at a
   *  glance without a tooltip). The caller must size the box for it — the tag takes a row. */
  tag?: string
  /** Count line rendered under a `card` node's title. */
  badge?: string
  /** Raw model counts behind `badge` (kept so callers can localise the text). */
  stats?: { props: number; links: number; actions: number }
  /** Explicit colour, overriding the per-type palette and the kind colour. The
   *  ontology workbench draws every object type in ONE colour (the model is one
   *  thing; colouring 15 types by name was decoration, not information) and
   *  keeps colour for the secondary nodes, where it does distinguish kinds. */
  color?: string
  /** A small satellite node (an action or a function hanging off a type). */
  small?: boolean
  /** Explicit box size `[w, h]`, overriding `cardSize`. The ontology canvas
   *  sizes every box to its own label (see graphAdapters.ontologyToFlow), so a
   *  short name gets a small box and a long one a wide box. */
  size?: [number, number]
  /** How many lines the label wraps to, as measured by whoever sized the box.
   *  `ontogeny-card` draws exactly this many — re-deriving the count from the box
   *  height over-estimates whenever a minimum-height clamp inflated the box,
   *  which pushed capsule tags out the bottom of short cards. */
  labelLines?: number
  /** The label pre-wrapped into its measured lines. When present, the card
   *  draws these verbatim (one row per entry) instead of letting the canvas
   *  re-wrap — two wrap algorithms tipping a borderline width differently is
   *  what used to bend cards out of shape. */
  labelWrapped?: string[]
  /** Pinned position, used with `layout: 'preset'`. */
  x?: number
  y?: number
}

export interface FlowGraphEdge {
  source: string
  target: string
  label?: string
  /** Direction marks to draw: `'end'` = arrowhead at the target (one-way),
   *  `'both'` = arrowheads on both ends (a pair of mutual links). Absent = no
   *  arrowhead, which is what `quietEdges` canvases ask for. */
  arrow?: 'end' | 'both'
  /** Caller-supplied identity (e.g. the LinkType name) so a click on the edge
   *  can be resolved back to the model element it draws. Falls back to its
   *  index, which is stable for a given payload but meaningless to the caller. */
  id?: string
  /** Draw this connection dashed.
   *
   * The ontology's visual contract: a solid line is an *entity relationship*
   * (a LinkType between two object types — part of the model's own structure),
   * a dashed line is every other attachment (an action targeting a type, a
   * function reading it, a policy, a projection). Making that distinction
   * visible is what lets the schema be read without clicking anything. */
  dashed?: boolean
}

export interface FlowGraphData {
  nodes: FlowGraphNode[]
  edges: FlowGraphEdge[]
  layout?: 'layered' | 'grid' | 'radial' | 'schema' | 'preset'
  /** `card` = rounded schema card (type graphs), `dot` = instance circle. */
  nodeStyle?: 'dot' | 'card'
  /** Draw the entity (host) nodes as HTML cards. Only meaningful when the
   *  caller measured each box per node (ontology workbench); a canvas that
   *  hands every card the same fixed size keeps the canvas element, whose
   *  metrics match that size. */
  entityCards?: boolean
  /** Draw connections as quiet structure: thinner, lighter, no arrowheads.
   *  For a dense model the edges are context, not the subject — the selected
   *  node's own connections still light up (that is the `active` state). */
  quietEdges?: boolean
}

const ACCENT = '#2e5bff'

// The ontology card is a custom element (see CardNode.ts): the built-in
// rect+label+icon composition overlaps the two as soon as a name is longer than
// the gap between them. Registering is global and idempotent.
registerCardNode()
// Object types are HTML cards (see EntityCardNode): a real DOM element over the
// canvas, transformed by the camera, which is what lets them carry CSS material
// (gradients, layered shadows) and stay text-crisp at every zoom.
registerEntityCardNode()

/** Below this the card labels stop being comfortably readable — see the
 *  render() clamp: fit-to-view is only honoured down to here. A 15-type model
 *  lands near 0.7 on a laptop, and clamping it back up pushed the bottom row
 *  off screen; the floor sits where "the whole model on one screen" still wins
 *  over the last half point of type size. */
const MIN_CARD_ZOOM = 0.66

/** A small neighbourhood may be magnified by the fit, but not all the way:
 *  past this the dots and their labels start colliding. */
const MAX_DOT_ZOOM = 1.25

/** Minimap box, in CSS px. */
const MINIMAP_SIZE: [number, number] = [132, 84]

export function FlowGraph({
  data, height = 460, fill = false, onNodeClick, onNodeDoubleClick, onNodeDragEnd, onEdgeClick,
  onCanvasClick, selectedId, selectedEdgeId, testId = 'flow-graph', cardSize = [176, 58],
  controlsInset,
  legendItems,
}: {
  data: FlowGraphData
  height?: number
  /** Size to the parent box instead of a fixed pixel height (full-bleed pages). */
  fill?: boolean
  onNodeClick?: (node: FlowGraphNode) => void
  /** Double-click opens a *deeper* view of one node (the graph page's 2-hop
   *  neighbourhood popup). Kept separate from click so the single-click
   *  highlight/inspect flow is unchanged. */
  onNodeDoubleClick?: (node: FlowGraphNode) => void
  /** Fired once a drag settles, with the node's new model position — the
   *  workbench persists it, so a hand-arranged layout survives a reload. */
  onNodeDragEnd?: (node: FlowGraphNode) => void
  /** A click on a connection: the caller resolves it by the edge's own id. */
  onEdgeClick?: (edge: FlowGraphEdge) => void
  onCanvasClick?: () => void
  /** Externally controlled highlight (legend clicks, detail-panel navigation). */
  selectedId?: string | null
  /** Externally controlled edge highlight (selecting a link in the panel). */
  selectedEdgeId?: string | null
  testId?: string
  /** Card footprint in CSS px; the ontology workbench asks for a compact one so
   *  a 15-type model fits without shrinking past legibility. */
  cardSize?: [number, number]
  /** Where the zoom controls sit from the LEFT edge. Defaults to the
   *  bottom-right corner; the ontology canvas pins them bottom-left with the
   *  legend beside them, so every canvas control lives in one cluster instead
   *  of one in each corner. */
  controlsInset?: string
  /** What the colours mean. When set, a small always-on legend renders beside
   *  the zoom cluster — every graph speaks this same visual language. */
  legendItems?: GraphLegendItem[]
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const minimapRef = useRef<HTMLDivElement>(null)
  const graphRef = useRef<any>(null)
  const highlightRef = useRef<(id: string | null) => void>(() => {})
  const [theme] = useTheme() // rebuild on light/dark switch (canvas reads computed colours)
  const { t } = useI18n()
  // Destructured so the canvas effect can depend on the *numbers*: callers pass
  // a literal (`cardSize={[172, 54]}`), and depending on the array itself would
  // tear down and rebuild the whole G6 canvas on every parent render.
  const [cardW, cardH] = cardSize
  const onNodeClickRef = useRef(onNodeClick)
  onNodeClickRef.current = onNodeClick
  const onNodeDoubleClickRef = useRef(onNodeDoubleClick)
  onNodeDoubleClickRef.current = onNodeDoubleClick
  const onNodeDragEndRef = useRef(onNodeDragEnd)
  onNodeDragEndRef.current = onNodeDragEnd
  const onEdgeClickRef = useRef(onEdgeClick)
  onEdgeClickRef.current = onEdgeClick
  const onCanvasClickRef = useRef(onCanvasClick)
  onCanvasClickRef.current = onCanvasClick
  const selectedIdRef = useRef(selectedId)
  selectedIdRef.current = selectedId
  const selectedEdgeRef = useRef(selectedEdgeId)
  selectedEdgeRef.current = selectedEdgeId
  const highlightEdgeRef = useRef<(id: string | null) => void>(() => {})

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const css = getComputedStyle(document.documentElement)
    const v = (name: string, fallback: string) =>
      css.getPropertyValue(name).trim() || fallback
    const dark = theme === 'dark'
    const C = {
      text: v('--text-primary', '#0f172a'),
      textMuted: v('--text-muted', '#94a3b8'),
      border: v('--border-strong', '#94a3b8'),
      surface: v('--surface-card', '#ffffff'),
      // graph edge colours: structural vs auxiliary (see the edge style below)
      edge: v('--graph-edge', dark ? '#d7dee9' : '#1f2733'),
      edgeAlt: v('--graph-edge-alt', dark ? '#f0a94c' : '#d9730d'),
    }

    const byId = new Map(data.nodes.map((n) => [n.id, n]))
    const layout = data.layout ?? 'layered'
    const isSchema = layout === 'schema' || layout === 'grid'
    const card = data.nodeStyle === 'card'
    // The schema canvas auto-fits the whole model, so a minimap has nothing to
    // navigate — and G6's minimap computes its camera once at init, so it goes
    // blank when this canvas is resized (which happens whenever the detail
    // column opens). Instance/projection graphs keep it: they are not resized
    // after mount, and their graphs routinely exceed the viewport.
    const showMinimap = !card && Boolean(minimapRef.current)
    // `preset` is NOT a G6 v5 layout: there is no such registration, and asking
    // for one only produced "The layout of preset is not registered" on every
    // build. Omitting the layout is the v5 way to say it — the runtime then
    // leaves every node exactly where the data put it (see runtime/layout.ts:
    // no options -> no layout pass), which is what a hand-arranged canvas is.
    const g6Layout = layout === 'preset'
      ? undefined
      : isSchema
      ? {
        type: 'antv-dagre',
        ...(card
          ? {
            // Ontology schema: one card per object type.
            //
            // Top-down rather than left-to-right. Every link carries its name as
            // horizontal text, and a left-to-right drawing puts that text in a
            // horizontal rank gap narrower than the label itself, so names like
            // `equipment-maintenance-orders` spill across the next card.
            // Stacking ranks vertically puts labels in a horizontal band
            // between rows, where they always fit.
            rankdir: 'TB',
            // Cards are wide and short, so rows need air while cards within a
            // row can sit close: this packing fits a whole schema on screen at
            // a readable zoom instead of shrinking it past legibility.
            nodesep: 26,
            ranksep: 50,
            // A link that closes a cycle always spans an extra rank (a layered
            // drawing of a cycle needs one long edge), and dagre already
            // reserves a route for it *around* the cards in between. Without
            // control points the canvas draws that edge straight end to end
            // instead, cutting through whatever card sits on the line.
            controlPoints: true,
          }
          : { rankdir: 'LR', nodesep: 48, ranksep: 170 }),
      }
      : layout === 'radial'
        ? { type: 'radial', unitRadius: 90, linkDistance: 100, preventOverlap: true }
        : { type: 'd3-force', preventOverlap: true, nodeSize: 64, linkDistance: 82, collide: 64 }

    const measure = () => (fill
      ? { w: container.clientWidth || 900, h: container.clientHeight || 560 }
      : { w: container.clientWidth || 800, h: height })

    const graph = new Graph({
      container,
      width: measure().w,
      height: measure().h,
      // `when: 'overflow'` keeps a small graph at 1:1 instead of magnifying it:
      // with plain 'view' an 8-node neighbourhood gets zoomed to ~1.8x, which
      // turns the dots into overlapping blobs with colliding labels.
      autoFit: 'view',
      // [top, right, bottom, left]: the schema canvas floats zoom controls
      // (bottom-right, shifted left of the agent dock) and the legend chip
      // (bottom-left) over the graph, so the fitted content reserves those
      // corners instead of ending up underneath them. The left inset is the
      // wider one because the legend expands into a tall panel when opened.
      padding: card ? [36, 96, 56, 104] : 28,
      animation: false,
      data: {
        nodes: data.nodes.map((n) => ({
          id: n.id,
          // a preset layout reads x/y off the element itself
          ...(layout === 'preset' && n.x !== undefined && n.y !== undefined
            ? { style: { x: n.x, y: n.y } }
            : {}),
          data: {
            label: n.label, sublabel: n.sublabel, type: n.type, start: n.start,
            display: n.display, description: n.description, tag: n.tag, badge: n.badge,
            color: n.color, small: n.small,
            kind: n.kind, size: n.size, labelLines: n.labelLines, labelWrapped: n.labelWrapped,
          },
        })),
        edges: data.edges.map((e, i) => ({
          id: e.id ?? `e-${i}`,
          source: e.source,
          target: e.target,
          data: { label: e.label, dashed: e.dashed },
        })),
      },
      node: {
        // `ontogeny-card` for a card canvas (including the ontology's satellites,
        // which are boxes too — see graphAdapters.ontologyToFlow), `circle` for
        // an instance graph. A node that carries its own `size` is a box.
        type: ((d: any) => {
          if (!card) return 'circle'
          const host = !d.data?.kind || d.data?.kind === 'object'
          return host && data.entityCards ? 'ontogeny-entity' : 'ontogeny-card'
        }) as any,
        style: (d: any) => {
          const meta = d.data ?? {}
          const kind = meta.kind as NodeKind | undefined
          // colour precedence: the caller's explicit colour, then the model
          // kind's own colour, then the per-type palette of an instance graph
          const color = meta.color ?? (kind ? kindColor(kind) : typeColor(meta.type))
          if (card) {
            // Host cards (object types; schema canvases carry no kind at all)
            // are the ENTITIES of the drawing, satellites (actions/functions)
            // their verbs. On the light theme's white sheet the hierarchy is
            // carried by WEIGHT, not by hue: hosts get a tinted face, a full
            // accent bar, a heavier border and a taller, softer drop shadow —
            // they read as raised panels. Satellites stay plain white with a
            // hairline border and a whisper of shadow, so the nouns visibly
            // stand in front of the verbs. The colour itself lives in the accent
            // bar and icon chip (drawn by CardNode.ts), which keeps the name at
            // full text contrast on every card.
            const host = !kind || kind === 'object'
            const box = meta.size ?? [cardW, cardH]
            // An HTML entity card: the box is the measured one, and every part
            // of its look (surface, rail, chip, capsule, states) is CSS — see
            // EntityCardNode.ts + the .ontogeny-ec rules. Its size still comes from
            // the layout, so dagre's reservation and the drawing agree.
            if (host && data.entityCards) {
              return {
                size: box,
                cardBox: box,
                cardTitleRows: meta.labelWrapped,
                cardColor: color,
                cardIconSrc: kind ? kindIconSrc(kind, color, dark) : undefined,
              }
            }
            if (!dark) {
              return {
                size: box,
                // geometry: the box the layout measured, and nothing else
                kindBox: box,
                radius: host ? 14 : 10,
                fill: host ? '#f7faff' : '#ffffff',
                stroke: withAlpha(color, host ? 0.55 : 0.3),
                lineWidth: host ? 1.8 : 1.1,
                shadowColor: host ? 'rgba(15, 23, 42, 0.18)' : 'rgba(15, 23, 42, 0.07)',
                shadowBlur: host ? 24 : 8,
                shadowOffsetY: host ? 7 : 2,
                // Drawn by the box element itself (CardNode.ts): the accent bar,
                // the icon in its tinted chip, the pre-wrapped name rows and the
                // display name as a capsule tag under them. G6's own label/icon
                // pair is switched off there because it centres the label on the
                // key shape and the two then overlap.
                labelText: meta.label,
                labelFill: C.text,
                labelFontWeight: 700,
                labelFontSize: host ? 13 : 12,
                labelLines: meta.labelLines,
                kindLabelLines: meta.labelWrapped,
                // the rail is the ENTITY card's device. A satellite is small —
                // a bar on it is a third of the card — so its kind is carried
                // by the tinted border and the glyph alone
                kindAccentColor: host ? color : undefined,
                kindAccentWidth: 5,
                kindIconSrc: kind ? kindIconSrc(kind, color, dark) : undefined,
                // no plate behind the glyph, so it carries the kind on its
                // own; per-kind sizes match the measurement in graphAdapters
                kindIconSize: host ? 20 : kind === 'action' ? 21 : 20,
                kindIconGap: 8,
                kindTagText: meta.tag ? String(meta.tag) : undefined,
                kindTagColor: color,
              }
            }
            return {
              size: box,
              kindBox: box,
              radius: 12,
              fill: withAlpha(color, 0.26),
              stroke: withAlpha(color, 0.9),
              lineWidth: 1.8,
              shadowColor: withAlpha(color, 0.4),
              shadowBlur: 14,
              shadowOffsetY: 2,
              labelText: meta.label,
              labelFill: C.text,
              labelFontWeight: 700,
              labelFontSize: host ? 13 : 12,
              labelLines: meta.labelLines,
              kindLabelLines: meta.labelWrapped,
              kindIconSrc: kind ? kindIconSrc(kind, color, dark) : undefined,
              kindIconSize: host ? 20 : kind === 'action' ? 21 : 20,
              kindIconGap: 8,
              kindTagText: meta.tag ? String(meta.tag) : undefined,
              kindTagColor: color,
            }
          }
          const size = meta.start ? 52 : 40
          return {
            size,
            fill: withAlpha(color, dark ? 0.22 : 0.12),
            stroke: color,
            lineWidth: meta.start ? 3 : 1.6,
            shadowColor: dark ? 'rgba(0,0,0,.55)' : withAlpha(color, 0.22),
            shadowBlur: 8,
            shadowOffsetY: 2,
            halo: Boolean(meta.start),
            haloLineWidth: 10,
            haloOpacity: 0.22,
            labelText: meta.label,
            labelPlacement: 'bottom',
            labelOffsetY: 2,
            labelMaxWidth: 132,
            labelFontWeight: 700,
            labelFontSize: 13.5,
            labelFill: C.text,
            labelBackground: true,
            labelBackgroundFill: C.surface,
            labelBackgroundOpacity: 0.88,
            labelBackgroundRadius: 4,
            labelPadding: [1, 4],
          }
        },
        state: {
          // Selection reads as *weight*, never as fading the rest:
          //  - every node should keep its colours at all times;
          //  - and G6 v5 does not restore `opacity` when a state is removed
          //    (verified: the shape stays at 0.16 forever), so a dimming state
          //    is a one-way ratchet that fades more nodes with every click.
          selected: card
            ? {
              stroke: ACCENT,
              lineWidth: 3,
              shadowColor: withAlpha(ACCENT, 0.38),
              shadowBlur: 22,
              shadowOffsetY: 6,
              // HTML entity cards paint themselves through CSS, so the state
              // reaches them as a flag the element turns into a class
              cardSelected: true,
            }
            : { halo: true, haloLineWidth: 6, haloOpacity: 0.3, lineWidth: 3.5, stroke: ACCENT },
          active: card ? { lineWidth: 2.4 } : { lineWidth: 2.8 },
        },
      },
      edge: {
        type: isSchema ? 'polyline' : 'line',
        style: (d: any) => {
          // Two line languages, and the caller picks one per edge:
          //   solid + ink    = an entity relationship (a LinkType)
          //   dashed + orange = an auxiliary attachment (action/function/…)
          // Both are opaque. The old grey-on-grey was technically visible and
          // practically not: at the zoom a 15-type model fits at, a 1.1px
          // 55%-alpha line disappears into the canvas grid.
          const dashed = Boolean(d.data?.dashed)
          const stroke = dashed ? C.edgeAlt : C.edge
          // Arrowheads state direction. A canvas that asks for a quiet mesh
          // (schema views) opts out; every other edge carries at least a target
          // arrowhead, and a pair of mutual links reads two-way via `startArrow`.
          const arrows = !isSchema && !data.quietEdges
          return {
            stroke,
            lineWidth: dashed ? 1.6 : 1.9,
            endArrow: arrows,
            endArrowSize: dashed ? 6 : 8,
            endArrowFill: stroke,
            startArrow: arrows && d.data?.arrow === 'both',
            startArrowSize: dashed ? 6 : 8,
            startArrowFill: stroke,
            // 5 on / 4 off: dense enough to read as a dash at fit zoom without
            // turning a short edge into a dotted line
            ...(dashed ? { lineDash: [5, 4] } : {}),
            // schema edges keep their link name visible (dagre spreads them);
            // instance-graph labels stay in the node drawer to avoid clutter
            labelText: isSchema ? d.data?.label : undefined,
            // G6 rotates edge labels along the edge by default: link names are
            // long and would read as slanted text, so schema labels stay upright
            labelAutoRotate: false,
            labelFontSize: 10,
            labelFill: stroke,
            labelBackground: true,
            labelBackgroundFill: C.surface,
            labelBackgroundOpacity: 0.92,
            labelBackgroundRadius: 4,
            labelPadding: [1, 4],
            ...(isSchema ? { radius: 16 } : {}),
          }
        },
        state: {
          active: { stroke: ACCENT, lineWidth: 2.6, endArrowFill: ACCENT, labelFill: ACCENT },
          // gentle: the selected node's edges stand out without erasing the
          // rest of the model (these two props do restore cleanly)
          inactive: { strokeOpacity: 0.22, labelOpacity: 0.3 },
        },
      },
      layout: g6Layout,
      behaviors: ['drag-canvas', 'zoom-canvas', 'drag-element'],
      plugins: [
        ...(showMinimap
          ? [{
            type: 'minimap',
            key: 'minimap',
            size: MINIMAP_SIZE,
            // An explicit host keeps the minimap pinned by CSS. G6's built-in
            // container derives left/top once from the graph size, so it drifts
            // outside the canvas as soon as the canvas is resized — e.g. when a
            // neighbouring column opens.
            container: minimapRef.current ?? undefined,
            maskStyle: {
              border: `1px solid ${withAlpha(ACCENT, 0.75)}`,
              background: withAlpha(ACCENT, dark ? 0.18 : 0.12),
            },
          }]
          : []),
        {
          type: 'tooltip',
          key: 'tooltip',
          trigger: 'hover',
          itemTypes: ['node', 'edge'],
          getContent: (_e: unknown, items: any[]) => {
            const d = items?.[0]?.data
            if (!d) return ''
            const wrap = 'white-space:normal;line-height:1.45;max-width:260px'
            // an edge's datum carries only its label: no description line
            if (!d.type && !d.sublabel) {
              return `<div style="font:600 12px sans-serif">${d.label ?? ''}</div>`
            }
            // nodes WITH a description (entity cards): the card shows the
            // display name, so hover answers the next question — what it IS
            if (d.description) {
              return `<div style="font:600 12px sans-serif">${d.display ?? d.label}</div>` +
                `<div style="font:11px sans-serif;color:${C.textMuted};${wrap}">${d.description}</div>`
            }
            return `<div style="font:600 12px sans-serif">${d.label}</div>` +
              (d.display ? `<div style="font:11px sans-serif;color:${C.textMuted}">${d.display}</div>` : '') +
              (d.badge ? `<div style="font:11px sans-serif;color:${C.border}">${d.badge}</div>`
                : d.sublabel ? `<div style="font:11px sans-serif;color:${C.textMuted}">${d.sublabel}</div>` : '')
          },
        },
      ],
    })

    // click a node: highlight its neighbourhood + open the info drawer
    const adjacency = new Map<string, Set<string>>()
    for (const e of data.edges) {
      if (!adjacency.has(e.source)) adjacency.set(e.source, new Set())
      if (!adjacency.has(e.target)) adjacency.set(e.target, new Set())
      adjacency.get(e.source)!.add(e.target)
      adjacency.get(e.target)!.add(e.source)
    }

    // setElementState() reaches into the renderer, which does not exist until
    // the first render resolves: calling it earlier throws internally (once per
    // node and edge, so a whole schema's worth of console noise). Gate every
    // highlight on this flag and apply the initial selection once render lands.
    let ready = false
    // Set by the cleanup below. A rebuild (theme switch, data refresh, resize)
    // destroys this graph while `render()` may still be in flight; its promise
    // then resolves into a graph that no longer exists, and G6 answers every
    // late call with "the graph instance has been destroyed".
    let disposed = false

    const highlight = (id: string | null) => {
      if (!ready || disposed) return
      for (const n of data.nodes) {
        const adjacent = id !== null && adjacency.get(n.id)?.has(id)
        // nodes are only ever marked selected/active; everything else is left
        // untouched, so no node is ever faded out
        const states = n.id === id ? ['selected'] : adjacent ? ['active'] : []
        graph.setElementState(n.id, id === null ? [] : states)
      }
      data.edges.forEach((e, i) => {
        const touches = id !== null && (e.source === id || e.target === id)
        graph.setElementState(e.id ?? `e-${i}`, id === null ? [] : touches ? ['active'] : ['inactive'])
      })
    }

    const nodeOf = (id: string): FlowGraphNode => {
      const meta = byId.get(id)
      return {
        id,
        label: meta?.label ?? id,
        sublabel: meta?.sublabel,
        type: meta?.type ?? meta?.sublabel,
        kind: meta?.kind,
        start: meta?.start,
        display: meta?.display,
        badge: meta?.badge,
      }
    }

    graph.on('node:click', (evt: any) => {
      const id = evt.target?.id
      if (!id) return
      highlight(id)
      onNodeClickRef.current?.(nodeOf(id))
    })
    graph.on('node:dblclick', (evt: any) => {
      const id = evt.target?.id
      if (!id) return
      onNodeDoubleClickRef.current?.(nodeOf(id))
    })
    // a hand-arranged layout is user work: report the settled position so the
    // caller can persist it
    graph.on('node:dragend', (evt: any) => {
      const id = evt.target?.id
      if (!id || !onNodeDragEndRef.current) return
      let pos: { x?: number; y?: number } = {}
      try {
        pos = graph.getNodeData(id)?.style ?? {}
      } catch {
        pos = {}
      }
      onNodeDragEndRef.current({ ...nodeOf(id), x: pos.x, y: pos.y })
    })
    // selecting a connection: highlight exactly it, so the panel's subject is
    // obvious on a canvas that may draw fifteen of them
    const highlightEdge = (edgeId: string | null) => {
      if (!ready || disposed) return
      data.edges.forEach((e, i) => {
        const id = e.id ?? `e-${i}`
        graph.setElementState(id, edgeId === null ? [] : id === edgeId ? ['active'] : ['inactive'])
      })
    }
    highlightEdgeRef.current = highlightEdge

    graph.on('edge:click', (evt: any) => {
      const id = evt.target?.id
      if (!id || !onEdgeClickRef.current) return
      const edge = data.edges.find((e, i) => (e.id ?? `e-${i}`) === id)
      if (edge) onEdgeClickRef.current(edge)
    })
    graph.on('canvas:click', () => {
      highlight(null)
      onCanvasClickRef.current?.()
    })

    // Fit-to-view is right at both extremes, but its scale can land somewhere
    // useless, so clamp it once the fit has settled (the graph stays centred):
    //  - a 15+ type schema shrinks the cards below legibility      -> floor;
    //  - a small instance neighbourhood gets magnified to ~1.8x, which turns
    //    the dots into overlapping blobs with colliding labels -> ceil 1.25.
    // Panning, the minimap and "fit to canvas" still give full control.
    const rendered: any = graph.render()
    const settle = () => {
      if (disposed) return
      ready = true
      highlight(selectedIdRef.current ?? null)
      highlightEdge(selectedEdgeRef.current ?? null)
      try {
        if (typeof graph.getZoom !== 'function' || typeof graph.zoomTo !== 'function') return
        const z = graph.getZoom()
        if (!z) return
        if (card && z < MIN_CARD_ZOOM) graph.zoomTo(MIN_CARD_ZOOM)
        else if (!card && z > MAX_DOT_ZOOM) graph.zoomTo(MAX_DOT_ZOOM)
      } catch {
        /* nothing rendered yet: keep the fitted zoom */
      }
    }
    if (rendered && typeof rendered.then === 'function') {
      rendered.then(settle).catch(() => { /* render failed: the empty canvas speaks for itself */ })
    } else {
      settle()
    }

    highlightRef.current = highlight
    graphRef.current = graph

    /* ---- dragging a DOM card ---------------------------------------------
     * HTML entity cards are DOM elements above the canvas. G6's drag behavior
     * is driven by the canvas's own pointer gestures, so a card receives the
     * click (events are forwarded) but never the drag: pressing on one starts
     * nothing. The press is therefore handled here, with window-level listeners
     * so the pointer may leave the card mid-gesture, and the node is moved
     * through the same API the canvas behavior uses — so the page's
     * `onNodeDragEnd` (which persists the layout) hears one story either way. */
    const DRAG_THRESHOLD = 4
    let stopCardDrag: (() => void) | null = null
    const onCardPointerDown = (ev: PointerEvent) => {
      if (ev.button !== 0) return
      const card = (ev.target as HTMLElement | null)?.closest?.('.ontogeny-ec') as HTMLElement | null
      const id = card?.dataset?.nodeId
      if (!id) return
      ev.preventDefault()
      const startX = ev.clientX
      const startY = ev.clientY
      const from = graph.getElementPosition(id) as [number, number]
      let latest: [number, number] = from
      let dragging = false
      const move = (e: PointerEvent) => {
        const dx = e.clientX - startX
        const dy = e.clientY - startY
        if (!dragging && Math.hypot(dx, dy) < DRAG_THRESHOLD) return
        dragging = true
        const zoom = graph.getZoom() || 1
        latest = [from[0] + dx / zoom, from[1] + dy / zoom]
        void graph.translateElementTo(id, latest, false)
      }
      const finish = () => {
        stopCardDrag?.()
        stopCardDrag = null
        // same payload the canvas behavior hands the page, so a persisted
        // layout cannot tell which kind of node was dragged
        if (dragging) onNodeDragEndRef.current?.({ ...nodeOf(id), x: latest[0], y: latest[1] })
      }
      const cancel = () => { stopCardDrag?.(); stopCardDrag = null }
      stopCardDrag = () => {
        window.removeEventListener('pointermove', move)
        window.removeEventListener('pointerup', finish)
        window.removeEventListener('pointercancel', cancel)
      }
      window.addEventListener('pointermove', move)
      window.addEventListener('pointerup', finish)
      window.addEventListener('pointercancel', cancel)
    }
    container.addEventListener('pointerdown', onCardPointerDown)

    // full-bleed canvases follow their container; G6 has no built-in observer
    let ro: ResizeObserver | undefined
    if (fill && typeof ResizeObserver !== 'undefined') {
      ro = new ResizeObserver(() => {
        if (disposed) return
        const el = containerRef.current
        if (!el) return
        const w = el.clientWidth
        const h = el.clientHeight
        if (!w || !h) return
        try {
          graph.setSize(w, h)
        } catch {
          /* renderer without resize support: keep the initial size */
        }
      })
      ro.observe(container)
    }

    // e2e/test + debug handle
    ;(window as any).__ooG6 = graph

    return () => {
      disposed = true
      stopCardDrag?.()
      container.removeEventListener('pointerdown', onCardPointerDown)
      ro?.disconnect()
      try {
        graph.destroy()
      } finally {
        // A tooltip that was visible when the graph was rebuilt (a theme switch,
        // a data refresh under the cursor) survives `destroy()`: the plugin only
        // hides it on mouseleave, which never fires for a node that has been
        // thrown away. Sweep it here — AFTER destroy, so the plugin's own
        // teardown still finds the element it wants to remove; removing it first
        // made G6 throw inside destroy() and left a half-destroyed instance that
        // answered every later call with "the graph instance has been destroyed".
        for (const tip of container.querySelectorAll(':scope > .tooltip')) tip.remove()
        if (graphRef.current === graph) graphRef.current = null
        if ((window as any).__ooG6 === graph) delete (window as any).__ooG6
      }
    }
  }, [data, height, fill, theme, cardW, cardH])

  // legend / panel driven selection (outside the canvas)
  useEffect(() => {
    highlightRef.current(selectedId ?? null)
  }, [selectedId])

  useEffect(() => {
    highlightEdgeRef.current(selectedEdgeId ?? null)
  }, [selectedEdgeId])

  const zoomBy = (factor: number) => {
    const g = graphRef.current
    if (!g || typeof g.getZoom !== 'function' || typeof g.zoomTo !== 'function') return
    try {
      g.zoomTo(Math.max(0.2, Math.min(4, g.getZoom() * factor)))
    } catch {
      /* ignore: nothing to zoom yet */
    }
  }

  // A canvas is opaque to assistive technology: G6 paints into a bitmap, so
  // there are no nodes to focus and nothing to read. `role="img"` with a summary
  // at least states what is on screen, and points at the keyboard path (the type
  // index on /ontology, the resource lists on /knowledge and /action) — the same text the
  // legend above the canvas already shows.
  const canvasLabel = t('graph.canvasLabel', {
    nodes: data.nodes.length,
    edges: data.edges.length,
  })

  return (
    <div className="relative h-full w-full" data-testid={testId}>
      <div
        ref={containerRef}
        role="img"
        aria-label={canvasLabel}
        className="h-full w-full"
        style={fill ? undefined : { height, width: '100%' }}
      />
      {/* the minimap mounts inside this shell, so CSS keeps it in the corner
          across resizes. The shell must own the positioning: G's canvas sets
          `container.style.position = 'relative'` on its host element, which
          would defeat an `absolute` class on the host itself. Schema canvases
          have no minimap (see `showMinimap`). */}
      {data.nodeStyle === 'card' ? null : (
        <div className="absolute right-2.5 top-2.5 z-10">
          <div
            ref={minimapRef}
            data-testid={`${testId}-minimap`}
            className="overflow-hidden rounded-[10px]"
            style={{
              width: MINIMAP_SIZE[0],
              height: MINIMAP_SIZE[1],
              background: 'var(--surface-card)',
              border: '1px solid var(--border-subtle)',
            }}
          />
        </div>
      )}
      {fill ? (
        <>
          {/* zoom stack: bottom-left by default (clear of the agent dock's
              floating button bottom-right); a caller may move it */}
          <div
            className="ontogeny-glass absolute bottom-4 z-10 flex flex-col gap-1 rounded-xl p-1"
            style={controlsInset ? { left: controlsInset } : { right: 86 }}
          >
            <CanvasButton label={t('graph.zoomIn')} onClick={() => zoomBy(1.25)}>
              <IconPlus width={14} height={14} />
            </CanvasButton>
            <CanvasButton label={t('graph.zoomOut')} onClick={() => zoomBy(0.8)}>
              <IconMinus width={14} height={14} />
            </CanvasButton>
            <CanvasButton
              label={t('graph.fit')}
              onClick={() => {
                const g = graphRef.current
                if (g && typeof g.fitView === 'function') {
                  try {
                    g.fitView()
                  } catch {
                    /* ignore */
                  }
                }
              }}
            >
              <IconFit width={14} height={14} />
            </CanvasButton>
          </div>
          {/* the colour key: top-left, always on, no plate */}
          {legendItems?.length ? (
            <div className="absolute left-4 top-4 z-10" style={controlsInset ? { left: controlsInset } : undefined}>
              <GraphLegend items={legendItems} />
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  )
}

function CanvasButton({ label, onClick, children }: {
  label: string
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={onClick}
      className="grid size-7 place-items-center rounded-lg transition-colors hover:bg-[var(--surface-hover)]"
      style={{ color: 'var(--text-secondary)' }}
    >
      {children}
    </button>
  )
}
