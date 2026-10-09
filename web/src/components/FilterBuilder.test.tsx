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
import { fireEvent, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { renderWithProviders } from '../test/render'
import { FilterBuilder, buildFilter, type Condition } from './FilterBuilder'

const render = (ui: React.ReactElement) => renderWithProviders(ui)

describe('buildFilter', () => {
  it('returns undefined with no active conditions', () => {
    expect(buildFilter([])).toBeUndefined()
    expect(buildFilter([{ id: 1, field: 'status', op: 'eq', value: '' }])).toBeUndefined()
  })

  it('single condition compiles to a flat clause', () => {
    expect(buildFilter([{ id: 1, field: 'status', op: 'eq', value: 'OPEN' }])).toEqual({
      field: 'status',
      op: 'eq',
      value: 'OPEN',
    })
  })

  it('multiple conditions AND together', () => {
    const ast = buildFilter([
      { id: 1, field: 'status', op: 'eq', value: 'OPEN' },
      { id: 2, field: 'priority', op: 'eq', value: 'HIGH' },
    ])
    expect(ast).toEqual({
      and: [
        { field: 'status', op: 'eq', value: 'OPEN' },
        { field: 'priority', op: 'eq', value: 'HIGH' },
      ],
    })
  })

  it('numeric strings coerce to numbers, in splits lists', () => {
    expect(buildFilter([{ id: 1, field: 'stock', op: 'ge', value: '5' }])).toEqual({
      field: 'stock',
      op: 'ge',
      value: 5,
    })
    expect(buildFilter([{ id: 1, field: 'status', op: 'in', value: 'OPEN, CLOSED' }])).toEqual({
      field: 'status',
      op: 'in',
      value: ['OPEN', 'CLOSED'],
    })
  })

  it('isnull maps to eq null regardless of value', () => {
    expect(buildFilter([{ id: 1, field: 'closed_at', op: 'isnull', value: '' }])).toEqual({
      field: 'closed_at',
      op: 'eq',
      value: null,
    })
  })
})

describe('FilterBuilder component', () => {
  const fields = ['status', 'priority', 'created_at']

  it('adds and removes condition rows', () => {
    const value: Condition[] = [{ id: 1, field: 'status', op: 'eq', value: '' }]
    const onChange = vi.fn()
    render(<FilterBuilder fields={fields} value={value} onChange={onChange} />)
    fireEvent.click(screen.getByTestId('filter-add'))
    expect(onChange).toHaveBeenCalledWith([...value, expect.objectContaining({ field: 'status' })])
    fireEvent.click(screen.getByLabelText('remove-1'))
    expect(onChange).toHaveBeenCalledWith([])
  })

  it('updates field and op through selects', () => {
    const onChange = vi.fn()
    render(<FilterBuilder fields={fields} value={[{ id: 7, field: 'status', op: 'eq', value: 'x' }]} onChange={onChange} />)
    fireEvent.change(screen.getByLabelText('field-7'), { target: { value: 'priority' } })
    expect(onChange).toHaveBeenLastCalledWith([expect.objectContaining({ field: 'priority' })])
    fireEvent.change(screen.getByLabelText('op-7'), { target: { value: 'isnull' } })
    expect(onChange).toHaveBeenLastCalledWith([expect.objectContaining({ op: 'isnull' })])
  })
})
