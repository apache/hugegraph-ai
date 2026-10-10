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
/** EntityCardNode: the HTML card's geometry and markup.
 *
 * Two things are worth pinning here, because both have already gone wrong once
 * in this canvas:
 *
 *  1. **The card fills exactly the box the layout measured.** The metrics live
 *     in this module and `graphAdapters` measures with them, so a card can never
 *     be drawn at a size dagre did not reserve — the failure mode that made
 *     every node's contents hang out of its own border.
 *  2. **Model text is escaped.** Names come from user-authored resources and go
 *     into `innerHTML`.
 */
import { describe, expect, it } from 'vitest'
import {
  ENTITY_METRICS as M, entityHeight, entityTextWidth, entityWidth, EntityCardNode,
} from './EntityCardNode'

type Shape = Record<string, unknown>

function draw(
  box: [number, number],
  attrs: Shape = {},
  id = 'type:bom',
): { shapes: Record<string, Shape>; el: FakeEl } {
  const shapes: Record<string, Shape> = {}
  const el = new FakeEl()
  const node = new EntityCardNode({} as never)
  // G6 assigns the element id; the card stamps it on the DOM wrapper
  ;(node as unknown as { id: string }).id = id
  ;(node as unknown as { upsert: unknown }).upsert =
    (key: string, _Ctor: unknown, style: unknown) => {
      if (style && style !== false) shapes[key] = style as Shape
      return { getDomElement: () => el }
    }
  ;(node as unknown as { drawKeyShape: (a: Shape, c: unknown) => unknown })
    .drawKeyShape({ cardBox: box, cardColor: '#2e5bff', ...attrs }, {} as never)
  return { shapes, el }
}

class FakeEl {
  classes = new Set<string>()
  /** Real elements carry the node id the drag handler reads back. */
  dataset: Record<string, string> = {}
  classList = {
    add: (c: string) => { this.classes.add(c) },
    toggle: (c: string, on?: boolean) => { if (on === undefined ? !this.classes.has(c) : on) this.classes.add(c); else this.classes.delete(c) },
    contains: (c: string) => this.classes.has(c),
  }
}

describe('entity card metrics', () => {
  it('sizes the box from the metrics the drawing uses', () => {
    const textW = 120
    const w = entityWidth(textW)
    expect(w).toBe(M.rail + M.padX + M.icon + M.gap + M.padRight + textW)
    // the text column is what the card's own markup gets, by construction
    expect(entityTextWidth(w)).toBe(textW)
    expect(entityHeight(1)).toBe(M.padY * 2 + M.titleLine)
    expect(entityHeight(2)).toBe(M.padY * 2 + 2 * M.titleLine)
  })

  it('keeps the width following the name, floor and ceiling included', () => {
    expect(entityWidth(10)).toBe(M.minW) // absurdly short: floored
    expect(entityWidth(10_000)).toBe(M.maxW) // absurdly long: capped
    expect(entityWidth(80)).toBeGreaterThan(entityWidth(40)) // the invariant
  })
})

describe('entity card rendering', () => {
  it('centres the world-transform box on the node position', () => {
    const { shapes } = draw([200, 64], { cardTitleRows: ['sales-order'] })
    expect(shapes.key).toMatchObject({ x: -100, y: -32, width: 200, height: 64 })
  })

  it('draws the rail, the glyph and the title rows — and no capsule', () => {
    const { shapes } = draw([200, 64], {
      cardTitleRows: ['close-maintenance-', 'order'],
      cardIconSrc: 'data:image/svg+xml,%3Csvg%3E',
    })
    const html = String(shapes.key.innerHTML)
    expect(html).toContain('ontogeny-ec-rail')
    expect(html).toContain('ontogeny-ec-img')
    // no plate behind the glyph: the icon is filled in the node's colour, and a
    // second shape behind it would compete with the rail
    expect(html).not.toContain('ontogeny-ec-chip')
    expect(html).toContain('close-maintenance-')
    expect(html).toContain('order')
    // the tag capsule is gone entirely: the card's text IS the display name,
    // and the description lives in the hover readout instead
    expect(html).not.toContain('ontogeny-ec-tag')
    // two rows, each its own element: the layout wrapped them, not the browser
    expect(html.match(/ontogeny-ec-line/g)).toHaveLength(2)
  })

  it('omits the glyph entirely when the node has none', () => {
    const { shapes } = draw([140, 43], { cardTitleRows: ['bom'] })
    const html = String(shapes.key.innerHTML)
    expect(html).not.toContain('ontogeny-ec-img')
    expect(html).toContain('bom')
  })

  it('escapes model text: a name is data, not markup', () => {
    const { shapes } = draw([200, 64], {
      cardTitleRows: ['<img src=x onerror=alert(1)>'],
    })
    const html = String(shapes.key.innerHTML)
    expect(html).not.toContain('<img')
    expect(html).toContain('&lt;img')
  })

  it('stamps the node id on the wrapper, which is how a press becomes a drag', () => {
    // FlowGraph's drag handler receives a DOM pointerdown and has to resolve it
    // back to a graph node: the id on the element is that link.
    const { el } = draw([200, 64], { cardTitleRows: ['bom'] }, 'type:sales-order')
    expect(el.dataset.nodeId).toBe('type:sales-order')
  })

  it('toggles the selection class on the DOM wrapper the state asks for', () => {
    const on = draw([200, 64], { cardTitleRows: ['bom'], cardSelected: true })
    expect(on.el.classes.has('ontogeny-ec')).toBe(true)
    expect(on.el.classes.has('is-selected')).toBe(true)

    const off = draw([200, 64], { cardTitleRows: ['bom'] })
    expect(off.el.classes.has('ontogeny-ec')).toBe(true)
    expect(off.el.classes.has('is-selected')).toBe(false)
  })
})
