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
/** Contract for the shared row helpers.
 *
 * Regression: `pkOf` existed as 4 copies in 2 semantics (`_id` allowed or not,
 * `'id'` vs `'_id'` fallback), so the same graph node opened a different object
 * URL depending on which panel you clicked it in; `typeColor` had a private fork
 * in the builder, so one object type was two colours; dates rendered 24-hour on
 * one page and `2:03:22 PM` on another.
 */
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { columnsOf, fmtDate, formatCell, pkOf, typeColor, typeTint, withAlpha } from './rows'

describe('pkOf', () => {
  it('prefers the model-declared primary key', () => {
    const row = { _id: 'a1', _type: 'sales-order', so_id: 'SO-1', customer_id: 'C-9' }
    expect(pkOf(row, ['so_id'])).toBe('so_id')
    // a declared key that is absent from the row is skipped, not returned
    expect(pkOf(row, ['nope', 'customer_id'])).toBe('customer_id')
  })

  it('never mistakes the store key for the business key', () => {
    // the API emits _id first; `'_id'.endsWith('_id')` is true, which is how two
    // of the old copies pointed every link at the internal id
    const row = { _id: 'a1', _type: 'sales-order', so_id: 'SO-1' }
    expect(pkOf(row)).toBe('so_id')
  })

  it('falls back in a defined order', () => {
    expect(pkOf({ _id: 'a1', _type: 't', id: 'x' })).toBe('id')
    expect(pkOf({ _id: 'a1', _type: 't' })).toBe('_id')
  })
})

describe('typeColor / typeTint', () => {
  it('is stable per type and shared by every surface', () => {
    expect(typeColor('sales-order')).toBe(typeColor('sales-order'))
    // the builder used to hash its own palette: same type, different colour
    expect(typeTint('sales-order').dot).toBe(typeColor('sales-order'))
    expect(typeTint('a-type-nobody-declared').dot).toBe(typeColor('a-type-nobody-declared'))
  })

  it('gives an unknown type a palette slot instead of a fixed grey', () => {
    expect(typeColor('brand-new-type')).toMatch(/^#[0-9a-f]{6}$/)
    expect(typeColor()).toBe('#64748b')
  })

  it('tints from the same hex (alpha is derived, never re-declared)', () => {
    const tint = typeTint('customer')
    expect(tint.fill).toBe(withAlpha(tint.dot, 0.07))
    expect(tint.stroke).toBe(withAlpha(tint.dot, 0.55))
  })
})

describe('fmtDate', () => {
  it('is 24-hour in both languages', () => {
    const iso = '2026-09-20T14:03:22'
    // the bug was a bare toLocaleString(): AM/PM in one place, not in another
    expect(fmtDate(iso, 'en')).not.toMatch(/AM|PM/)
    expect(fmtDate(iso, 'zh')).not.toMatch(/AM|PM/)
    expect(fmtDate(iso, 'en')).toContain('14:03')
  })

  it('renders a missing or unparseable timestamp without throwing', () => {
    expect(fmtDate(null)).toBe('—')
    expect(fmtDate(undefined)).toBe('—')
    expect(fmtDate('not a date')).toBe('not a date')
  })
})

describe('formatCell', () => {
  it('truncates a nested object instead of blowing out the column', () => {
    const wide = { a: 'x'.repeat(200) }
    const { container } = renderText(formatCell(wide))
    expect(container.textContent).toHaveLength(73) // 72 chars + the ellipsis
    expect(container.textContent?.endsWith('…')).toBe(true)
  })

  it('masks, and shows an em dash for null', () => {
    expect(renderText(formatCell('__masked__')).container.textContent).toContain('▒')
    expect(renderText(formatCell(null)).container.textContent).toBe('—')
  })
})

describe('columnsOf', () => {
  const rows = [{ _id: 'a', so_id: 'SO-1', qty: 3 }, { _id: 'b', so_id: 'SO-2', qty: 4 }]

  it('trims internal fields and puts the primary key first', () => {
    const cols = columnsOf(rows, 'so_id')
    expect(cols.map((c) => c.key)).toEqual(['so_id', 'qty'])
  })

  it('shows the model display name beside the machine name', () => {
    const [first] = columnsOf(rows, 'so_id', { so_id: '订单号' })
    expect(renderText(first.label).container.textContent).toContain('订单号')
    expect(renderText(first.label).container.textContent).toContain('so_id')
  })

  it('falls back to the machine name when the model has no display name', () => {
    const [first] = columnsOf(rows, 'so_id', { so_id: null })
    expect(renderText(first.label).container.textContent).toBe('so_id')
  })

  it('leaves cell rendering to the shared formatter (no private render)', () => {
    // columnsOf must not ship a private render: the DataTable's `formatCell` is
    // the app-wide cell contract (masked ▒ badge, local timestamps, truncated
    // JSON). A preview table that stringified everything is how raw
    // `__masked__` and ISO timestamps reached the data preview while the object
    // browser showed the formatted forms.
    const cols = columnsOf(
      [{ so_id: 'SO-1', site: '__masked__', due: '2026-11-15T00:00:00+00:00' }],
      'so_id',
    )
    expect(cols.map((c) => c.key)).toEqual(['so_id', 'site', 'due'])
    for (const c of cols) expect(Object.keys(c).sort()).toEqual(['key', 'label'])
  })
})

/** The helpers return ReactNode, so asserting on their text needs a render. */
function renderText(node: ReactNode) {
  return render(<>{node}</>)
}
