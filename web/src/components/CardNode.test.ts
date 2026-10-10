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
/** CardNode geometry: what the element draws stays inside the box it was given.
 *
 * This is the invariant a screenshot cannot check and that the previous layout
 * bug violated silently: the card's border was drawn from the measured box while
 * its icon, name and tag were laid out from a top-relative offset used as a
 * centre-relative coordinate — so every card's contents sat half a card too low,
 * hanging out of the bottom edge. Asserting containment here turns that class of
 * error into a failing test instead of something to notice by eye.
 */
import { describe, expect, it } from 'vitest'
import { CardNode } from './CardNode'

type Shape = Record<string, unknown>

/** Draw one card and capture the shapes the element emits. */
function draw(box: [number, number], attrs: Shape = {}): Record<string, Shape> {
  const node = new CardNode({} as never)
  const out: Record<string, Shape> = {}
  ;(node as unknown as { upsert: unknown }).upsert =
    (key: string, _Ctor: unknown, style: unknown) => {
      if (style !== false && style !== undefined) out[key] = style as Shape
    }
  ;(node as unknown as { drawKeyShape: (a: Shape, c: unknown) => unknown })
    .drawKeyShape({ kindBox: box, labelFill: '#0f172a', ...attrs }, {} as never)
  return out
}

const HOST: [number, number] = [200, 64]
const SATELLITE: [number, number] = [168, 34]

describe('CardNode geometry', () => {
  it('draws the key rectangle as the exact box it was handed', () => {
    const shapes = draw(HOST, { labelText: 'sales-order', kindLabelLines: ['sales-order'] })
    expect(shapes.key).toMatchObject({ x: -100, y: -32, width: 200, height: 64 })
  })

  it('keeps every drawn shape inside the box — icon, name rows and tag alike', () => {
    const shapes = draw(HOST, {
      labelText: 'sales-order',
      kindLabelLines: ['sales-order'],
      labelFontSize: 13,
      kindTagText: '销售订单',
      kindTagColor: '#2e5bff',
      kindAccentColor: '#2e5bff',
      kindAccentWidth: 5,
      kindIconSrc: 'data:image/svg+xml,x',
      kindIconSize: 20,
      kindIconGap: 8,
    })

    const [, h] = HOST
    const top = -h / 2
    const bottom = h / 2
    for (const [name, s] of Object.entries(shapes)) {
      if (name === 'key' || name === 'kind-accent') continue // full-height by design
      const y = Number(s.y)
      if (typeof s.height === 'number') {
        expect(y, `${name} top`).toBeGreaterThanOrEqual(top)
        expect(y + s.height, `${name} bottom`).toBeLessThanOrEqual(bottom)
      } else {
        // text: y is its baseline centre, fontSize its extent
        const half = Number(s.fontSize ?? 13) / 2
        expect(y - half, `${name} top`).toBeGreaterThanOrEqual(top)
        expect(y + half, `${name} bottom`).toBeLessThanOrEqual(bottom)
      }
    }
  })

  it('centres the content block on the card, and the icon on the title row', () => {
    const shapes = draw(HOST, {
      labelText: 'product',
      kindLabelLines: ['product'],
      labelFontSize: 13,
      kindTagText: '产品',
      kindTagColor: '#2e5bff',
      kindIconSrc: 'x',
      kindIconSize: 20,
    })

    // the tag is the last row: block top -> tag bottom is symmetric about 0
    // (within a pixel: each shape rounds its own coordinate, so an odd row
    // height can leave a sub-pixel residual — never a visible shift)
    const nameY = Number(shapes['name-0'].y)
    const tag = shapes['tag-pill']
    const blockTop = nameY - 17 / 2
    const blockBottom = Number(tag.y) + Number(tag.height)
    expect(Math.abs(blockTop + blockBottom)).toBeLessThanOrEqual(1)

    // the icon sits on the title row, not in the gap under it
    const icon = shapes['kind-icon']
    const iconCY = Number(icon.y) + Number(icon.height) / 2
    expect(Math.abs(iconCY - nameY)).toBeLessThanOrEqual(1)
  })

  it('leaves a tagless card with its name alone, centred', () => {
    const shapes = draw(SATELLITE, {
      labelText: 'oee',
      kindLabelLines: ['oee'],
      labelFontSize: 12,
      kindAccentColor: '#0891b2',
      kindAccentWidth: 3,
    })
    expect(Math.abs(Number(shapes['name-0'].y))).toBeLessThanOrEqual(1)
    expect(shapes['tag-pill']).toBeUndefined()
    expect(shapes['tag-text']).toBeUndefined()
    // the accent bar spans the box height, inset by the 1px border
    expect(shapes['kind-accent']).toMatchObject({ y: -16, height: 32 })
  })

  it('wraps a multi-row name as one centred block, rows in order', () => {
    const shapes = draw(SATELLITE, {
      labelText: 'close-maintenance-order',
      kindLabelLines: ['close-maintenance-', 'order'],
      labelFontSize: 12,
    })
    const first = Number(shapes['name-0'].y)
    const second = Number(shapes['name-1'].y)
    expect(second - first).toBeGreaterThan(0) // reading order, top to bottom
    expect(Math.abs(first + second)).toBeLessThanOrEqual(1) // centred on the box
    expect(shapes['name-2']).toBeUndefined() // no stale rows
  })

  it('drops shapes a previous, larger wrap left behind', () => {
    const node = new CardNode({} as never)
    const removed: string[] = []
    ;(node as unknown as { upsert: unknown }).upsert =
      (key: string, _Ctor: unknown, style: unknown) => {
        if (style === false) removed.push(key)
      }
    ;(node as unknown as { drawKeyShape: (a: Shape, c: unknown) => unknown }).drawKeyShape({
      kindBox: SATELLITE,
      labelFill: '#0f172a',
      labelText: 'oee',
      kindLabelLines: ['oee'],
    }, {} as never)
    expect(removed).toContain('name-1')
    expect(removed).toContain('name-4')
  })
})
