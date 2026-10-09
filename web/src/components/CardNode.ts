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
 * CardNode — a model element drawn as a raised, colour-keyed card.
 *
 * Every node on the ontology canvas is the same *kind* of thing: a rounded
 * rectangle with a kind accent bar, a tinted icon chip and the element's name,
 * wrapping onto as many lines as it needs. That is deliberate — an earlier
 * revision drew object types as wide cards and everything else as bare dots,
 * and the dots were unreadable: a row of circles tells you fifteen things exist
 * but not which is which.
 *
 * **Geometry is owned here, not inherited.** The box size arrives as
 * `kindBox` — the numbers `graphAdapters.ontologyToFlow` measured — and the key
 * rectangle is built from exactly those. Spreading G6's own key style used to
 * drag a framework-derived `size` into the rectangle while the contents kept
 * the measured height, so a card's tag row hung outside its own border. One
 * source of truth removes that class of bug instead of compensating for it.
 *
 * **The name is drawn from pre-wrapped rows.** `fitText` (the same measurement
 * the layout sized the box with) hands the card its lines, and the card paints
 * them verbatim. The canvas never re-wraps, so measure and draw cannot disagree
 * at a borderline width — that disagreement was cutting final letters onto a
 * second line.
 *
 * It is a real G6 element: `getKeyStyle` / `drawKeyShape` are the node
 * contract, so layout, hit-testing, states, edge routing and tooltips keep
 * working exactly as for a built-in node. G6's label/icon/badge machinery is
 * switched off (`getLabelStyle` etc. return false) because its label is centred
 * on the key shape and its icon is placed from an edge — the two overlap as soon
 * as a name is longer than the gap between them.
 */
import { Image as GImage, Rect as GRect, Text as GText, type Group } from '@antv/g'
import { Rect, register, type BaseNodeStyleProps } from '@antv/g6'
import { withAlpha } from '../lib/rows'
import { measureTextWidth } from './textMetrics'

const PAD = 12
/** The display-name tag under the title: a capsule in the kind colour. The
 *  layout (graphAdapters) reserves TAG_GAP + TAG_H of extra box height for it;
 *  this element just draws inside what was reserved. */
const TAG_GAP = 6
const TAG_H = 18
const TAG_PAD_X = 7
const TAG_FONT = 10.5
/** How many rows the "delete stale shapes" sweep covers (see drawContents). */
const MAX_ROWS = 5

/** Paint attributes passed straight through to the key rectangle. Named so the
 *  element never inherits geometry (`width`/`height`/`size`) from the runtime. */
const KEY_PAINT = [
  'fill', 'stroke', 'lineWidth', 'radius', 'opacity', 'cursor',
  'shadowColor', 'shadowBlur', 'shadowOffsetX', 'shadowOffsetY',
] as const

/** The box's own attributes, as the graph's style function emits them.
 *  Deliberately not named `iconSrc`: that is G6's own (image-or-element) icon
 *  attribute, and reusing it would fight the machinery this element bypasses. */
interface CardAttrs {
  kindIconSrc?: string
  kindIconSize?: number
  kindIconGap?: number
  kindNameFill?: string
  /** Display name drawn as a capsule tag under the title. */
  kindTagText?: string
  /** Colour the tag and the icon chip are tinted with. */
  kindTagColor?: string
  /** Accent bar down the card's left edge, in the kind colour: the face stays
   *  near-white for text contrast, the bar carries the hue. */
  kindAccentColor?: string
  kindAccentWidth?: number
  /** Measured wrap count and the wrapped rows themselves. */
  labelLines?: number
  kindLabelLines?: string[]
  /** The measured box `[w, h]` — the only source of this card's geometry. */
  kindBox?: number[]
}

/** The box size, preferring the layout's measurement over anything the runtime
 *  may have attached. */
function boxOf(attributes: Record<string, unknown>): [number, number] {
  const box = attributes.kindBox
  if (Array.isArray(box) && box.length >= 2) return [Number(box[0]), Number(box[1])]
  const size = attributes.size
  if (Array.isArray(size) && size.length >= 2) return [Number(size[0]), Number(size[1])]
  return [160, 44]
}

export class CardNode extends Rect {
  constructor(options: ConstructorParameters<typeof Rect>[0]) {
    super(options)
  }

  /** Box geometry: a rounded rectangle centred on the node's position, built
   *  from the measured box and the caller's paint — nothing inherited. */
  getKeyStyle(attributes: Required<BaseNodeStyleProps>) {
    const [width, height] = boxOf(attributes as unknown as Record<string, unknown>)
    const style: Record<string, unknown> = { x: -width / 2, y: -height / 2, width, height }
    const attrs = attributes as unknown as Record<string, unknown>
    for (const key of KEY_PAINT) if (attrs[key] !== undefined) style[key] = attrs[key]
    return style as never
  }

  getLabelStyle(): false {
    return false
  }

  getIconStyle(): false {
    return false
  }

  getBadgesStyle(): Record<string, false> {
    return {}
  }

  drawKeyShape(attributes: Required<BaseNodeStyleProps>, container: Group) {
    const key = this.upsert('key', GRect, this.getKeyStyle(attributes), container)
    this.drawContents(attributes as unknown as Required<BaseNodeStyleProps> & CardAttrs, container)
    return key
  }

  /** Accent bar, icon chip, name rows, tag capsule — laid out as ONE centred
   *  content block, so a one-line card never looks top-heavy and a three-line
   *  one never pushes its tag out the bottom. */
  private drawContents(attributes: Required<BaseNodeStyleProps> & CardAttrs, container: Group) {
    const [width, height] = boxOf(attributes as unknown as Record<string, unknown>)
    const iconSrc = attributes.kindIconSrc
    const iconSize = attributes.kindIconSize ?? 20
    const gap = attributes.kindIconGap ?? 7
    const left = -width / 2
    const top = -height / 2
    const hasIcon = Boolean(iconSrc)
    const tag = String(attributes.kindTagText ?? '')
    const color = attributes.kindTagColor ?? attributes.kindNameFill ?? attributes.labelFill

    // Accent bar: the kind colour as a structural element, a full capsule down
    // the left edge, inset 1px so it sits inside the border.
    const barW = Math.round(Number(attributes.kindAccentWidth ?? 4))
    if (attributes.kindAccentColor) {
      this.upsert('kind-accent', GRect, {
        x: Math.round(left + 1),
        y: Math.round(top + 1),
        width: barW,
        height: Math.round(height - 2),
        radius: barW / 2,
        fill: attributes.kindAccentColor,
      }, container)
    } else {
      this.upsert('kind-accent', GRect, false, container)
    }

    const fontSize = Number(attributes.labelFontSize ?? 13)
    // Rows land on WHOLE pixels: 1.28 line-height leaves every second row on a
    // half-pixel, and half-pixel canvas text renders soft.
    const rowH = Math.round(fontSize * 1.28)
    const wrapped = attributes.kindLabelLines?.filter((r) => r.length > 0)
    const lines = wrapped && wrapped.length
      ? wrapped.length
      : Math.max(1, Number(attributes.labelLines ?? 1))
    // One centred content block: the name rows, then the tag row.
    //
    // `contentTop` is a LOCAL y (the card's own origin is its centre), so the
    // top-relative centring offset must be added to `top`. Without it every
    // card drew its icon, name and tag half a card lower — the border sat in the
    // right place while the contents hung out of the bottom edge.
    const nameH = lines * rowH
    const contentH = nameH + (tag ? TAG_GAP + TAG_H : 0)
    // kept EXACT (it may land on a half pixel): rounding the centring offset
    // first shifts the whole block off centre, which is what made the icon and
    // the tag sit 1px low. Each shape rounds its own coordinate instead.
    const contentTop = top + (height - contentH) / 2

    const textX = Math.round(hasIcon ? left + PAD + iconSize + gap : 0)
    const textW = hasIcon ? width - PAD * 2 - iconSize - gap : width - PAD * 2

    // The kind glyph, centred on the NAME rows — the card's title row. Centring
    // it on the whole content block (name + tag) floated it into the gap between
    // them, so it read as belonging to neither line. A card whose icon sits
    // beside its title and whose tag hangs under it is the grammar this canvas
    // follows.
    //
    // No plate behind it (matching the entity cards): the icon is filled with
    // the node's own colour, and a tinted square behind it would just be a
    // second, competing shape.
    const chipCY = Math.round(contentTop + nameH / 2)
    this.upsert('kind-chip', GRect, false, container)
    if (hasIcon) {
      this.upsert('kind-icon', GImage, {
        src: iconSrc,
        x: Math.round(left + PAD),
        y: chipCY - iconSize / 2,
        width: iconSize,
        height: iconSize,
        opacity: 1,
      }, container)
    } else {
      this.upsert('kind-icon', GImage, false, container)
    }

    // A kebab-case name has no spaces, so a canvas word-wrap would have to
    // guess where to break. The wrapped rows were measured with this exact font
    // and width, so they are drawn verbatim, one shape per row.
    const label = String(attributes.labelText ?? '')
    const rows = wrapped && wrapped.length ? wrapped : [label.replace(/-/g, '-\u200b')]
    this.upsert('name', GText, false, container)
    rows.slice(0, MAX_ROWS).forEach((row, i) => {
      this.upsert(`name-${i}`, GText, {
        text: row,
        x: textX,
        y: Math.round(contentTop + i * rowH + rowH / 2),
        textAlign: hasIcon ? 'left' : 'center',
        textBaseline: 'middle',
        fontSize,
        fontWeight: attributes.labelFontWeight ?? 700,
        fill: attributes.kindNameFill ?? attributes.labelFill,
        ...(wrapped && wrapped.length ? {} : {
          wordWrap: true, wordWrapWidth: textW, maxLines: 1, textOverflow: '…',
        }),
      }, container)
    })
    // a previous draw may have laid down more rows than the current wrap needs
    // (state redraws reuse the same element)
    for (let i = rows.length; i < MAX_ROWS; i += 1) this.upsert(`name-${i}`, GText, false, container)

    if (tag) {
      const pillW = Math.min(textW, Math.ceil(measureTextWidth(tag, TAG_FONT)) + TAG_PAD_X * 2)
      const pillY = Math.round(contentTop + nameH + TAG_GAP + TAG_H / 2)
      this.upsert('tag-pill', GRect, {
        x: textX,
        y: pillY - TAG_H / 2,
        width: pillW,
        height: TAG_H,
        radius: TAG_H / 2,
        fill: withAlpha(String(color), 0.16),
        stroke: withAlpha(String(color), 0.45),
        lineWidth: 1,
      }, container)
      this.upsert('tag-text', GText, {
        text: tag,
        x: textX + TAG_PAD_X,
        y: pillY,
        textAlign: 'left',
        textBaseline: 'middle',
        fontSize: TAG_FONT,
        fontWeight: 600,
        fill: color,
        wordWrap: true,
        wordWrapWidth: Math.max(8, pillW - TAG_PAD_X * 2),
        maxLines: 1,
        textOverflow: '…',
      }, container)
    } else {
      this.upsert('tag-pill', GRect, false, container)
      this.upsert('tag-text', GText, false, container)
    }

  }
}

let registered = false

/** Register the box element once per page: G6's registry is global. */
export function registerCardNode() {
  if (registered) return
  register('node', 'ontogeny-card', CardNode as never)
  registered = true
}
