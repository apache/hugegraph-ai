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
 * EntityCardNode — the object-type card, drawn as real HTML.
 *
 * Object types are the nouns of the model and the only nodes a reader scans
 * first, so they get the one thing the canvas cannot give them: a DOM element.
 * `@antv/g`'s HTML shape mounts a `<div>` on top of the canvas and drives it
 * with the **world transform**, so the card scales and pans with the camera
 * while its text stays vector-crisp at every zoom — and its material (gradients,
 * hairlines, layered shadows, rounded corners) is plain CSS instead of canvas
 * approximations.
 *
 * The geometry still comes from the layout: `graphAdapters.ontologyToFlow`
 * measures the box with the SAME numbers exported here as `ENTITY_METRICS`, so
 * the reserved dagre cell and the drawn card cannot disagree. That sharing is
 * not tidiness — a previous revision measured in one coordinate convention and
 * drew in another, and every card's contents hung out of its own border.
 *
 * Only the key shape is custom: G6's HTML node already forwards DOM events into
 * the graph (`node:click` works), keeps the element's z-index in step and
 * removes the element on destroy, so the built-in class stays the base.
 */
import { HTML as GHTML, type Group } from '@antv/g'
import { HTML as HTMLNode, register, type BaseNodeStyleProps } from '@antv/g6'
import { withAlpha } from '../lib/rows'

/** The entity card's one and only source of metrics.
 *
 * Both the layout (which reserves the space) and the card (which fills it) read
 * these numbers, so a change here moves both. */
export const ENTITY_METRICS = {
  /** Accent rail down the left edge, in the kind colour. It fades downward:
   *  a solid bar top-to-bottom read as a hard divider, while one that
   *  dissolves anchors the corner where reading starts and then gets quiet. */
  rail: 4,
  /** Rail → icon. */
  padX: 12,
  /** The kind icon, drawn in the node's colour with NO plate behind it.
   *  The entity glyph is the card's hero mark, so it is the largest of the
   *  three kinds. */
  icon: 30,
  /** Icon → text column. */
  gap: 9,
  /** Text column → right edge. */
  padRight: 12,
  padY: 13,
  titleFont: 13,
  /** Whole-pixel row pitch (round(13 × 1.28)); half pixels render soft. */
  titleLine: 17,
  /** Only a floor against absurdly narrow cards: the card's width must keep
   *  following the name (a row of identical boxes tells you nothing), so this
   *  sits just above the rail + icon + padding chrome (~64px). */
  minW: 116,
  maxW: 236,
} as const

/** Width available to the title rows inside a card of width `w`. */
export const entityTextWidth = (w: number): number =>
  w - ENTITY_METRICS.rail - ENTITY_METRICS.padX - ENTITY_METRICS.icon - ENTITY_METRICS.gap - ENTITY_METRICS.padRight

/** The card's height for a title of `lines` rows. */
export const entityHeight = (lines: number): number =>
  ENTITY_METRICS.padY * 2 + lines * ENTITY_METRICS.titleLine

/** The card's width for a title column `textW` wide. */
export const entityWidth = (textW: number): number =>
  Math.min(
    ENTITY_METRICS.maxW,
    Math.max(
      ENTITY_METRICS.minW,
      ENTITY_METRICS.rail + ENTITY_METRICS.padX + ENTITY_METRICS.icon + ENTITY_METRICS.gap + ENTITY_METRICS.padRight + textW,
    ),
  )

/** Model text is user-authored: it goes into innerHTML, so it is escaped. */
function esc(s: string): string {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

interface EntityAttrs {
  /** The measured box — the only source of this card's geometry. */
  cardBox?: number[]
  /** Title rows, pre-wrapped by the layout (never re-wrapped here). */
  cardTitleRows?: string[]
  /** Kind colour: rail and glyph. */
  cardColor?: string
  cardIconSrc?: string
  /** Set by the `selected` state: drives the ring on the DOM wrapper. */
  cardSelected?: boolean
}

function boxOf(attributes: Record<string, unknown>): [number, number] {
  const box = attributes.cardBox ?? attributes.size
  if (Array.isArray(box) && box.length >= 2) return [Number(box[0]), Number(box[1])]
  return [ENTITY_METRICS.minW, entityHeight(1)]
}

/** The card's markup. Deterministic for a given identity: an identical string
 *  makes @antv/g skip the DOM write, so a re-render (a state change, a
 *  selection) does not rebuild the element under the user's cursor. */
function cardHTML(a: EntityAttrs): string {
  const color = a.cardColor ?? '#2e5bff'
  const rows = (a.cardTitleRows ?? []).filter((r) => r.length > 0)
  const rail = `<i class="ontogeny-ec-rail" style="background:linear-gradient(180deg, ${esc(color)} 0%, ${withAlpha(color, 0.14)} 100%)"></i>`
  // No plate behind the glyph: the icon is filled with the node's colour, so it
  // reads as part of the card rather than as a widget sitting on it.
  const icon = a.cardIconSrc
    ? `<img class="ontogeny-ec-img" src="${esc(a.cardIconSrc)}" alt="" draggable="false">`
    : ''
  const title = `<span class="ontogeny-ec-title">${rows.map((r) => `<span class="ontogeny-ec-line">${esc(r)}</span>`).join('')}</span>`
  return `<div class="ontogeny-ec-body">${rail}<span class="ontogeny-ec-main">` +
    `<span class="ontogeny-ec-row">${icon}${title}</span>` +
    `</span></div>`
}

export class EntityCardNode extends HTMLNode {
  /** Geometry: the measured box, centred on the node's position. */
  getKeyStyle(attributes: Required<BaseNodeStyleProps>): Record<string, unknown> & { innerHTML: string } {
    const [width, height] = boxOf(attributes as unknown as Record<string, unknown>)
    return {
      x: -width / 2,
      y: -height / 2,
      width,
      height,
      innerHTML: cardHTML(attributes as unknown as EntityAttrs),
      pointerEvents: 'auto' as const,
      cursor: 'grab' as const,
    }
  }

  drawKeyShape(attributes: Required<BaseNodeStyleProps>, container: Group) {
    const style: Record<string, unknown> = this.getKeyStyle(attributes)
    // Straight onto the element's own group: the base class nests this inside a
    // zero-opacity Rect at the same x/y, which would translate the DOM element
    // twice (the world matrix already carries its position).
    const key = this.upsert('key', GHTML, style as never, container)
    // Selection is a DOM class: the wrapper element belongs to @antv/g, its look
    // belongs to the stylesheet (`.ontogeny-ec.is-selected`).
    const el = (key as unknown as { getDomElement?: () => HTMLElement })?.getDomElement?.()
    if (el) {
      el.classList.add('ontogeny-ec')
      el.classList.toggle('is-selected', Boolean((attributes as unknown as EntityAttrs).cardSelected))
      // Identity on the element itself: the canvas cannot tell which node a DOM
      // card belongs to, and the drag handler (FlowGraph) needs exactly that.
      el.dataset.nodeId = this.id
    }
    return key
  }
}

let registered = false

/** Register the entity card once per page: G6's registry is global. */
export function registerEntityCardNode() {
  if (registered) return
  register('node', 'ontogeny-entity', EntityCardNode as never)
  registered = true
}
