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
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { mockFetch, META } from '../test/setup'
import { renderWithProviders } from '../test/render'
import { ObjectsBrowser } from './ObjectsBrowser'

const render = () =>
  renderWithProviders(<ObjectsBrowser />, { path: '/objects/sales-order', route: '/objects/:type' })

describe('ObjectsBrowser', () => {
  it('queries with pagination and renders property columns', async () => {
    const { calls } = mockFetch([
      { match: '/meta/ontology', body: META },
      {
        match: '/objects/sales-order/query',
        body: {
          objects: [
            { so_id: 'SO-2026-0001', status: 'DRAFT', _rev: 1 },
            { so_id: 'SO-2026-0002', status: 'CONFIRMED', _rev: 1 },
          ],
          total: 2,
          latency_ms: 3.2,
        },
      },
    ])
    render()
    await waitFor(() => expect(screen.getByText('SO-2026-0001')).toBeInTheDocument())
    const body = JSON.parse(String(calls.find((c) => c.url.includes('/query'))!.init?.body))
    expect(body.limit).toBe(20)
    expect(body.sort).toEqual([['so_id', 'asc']])
    expect(screen.getByTestId('pager-next')).toBeDisabled()
  })

  it('applies built filters to the query body', async () => {
    const { calls } = mockFetch([
      { match: '/meta/ontology', body: META },
      { match: '/objects/sales-order/query', body: { objects: [], total: 0, latency_ms: 1 } },
    ])
    render()
    await waitFor(() => expect(screen.getByTestId('filter-add')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('filter-add'))
    fireEvent.change(screen.getByLabelText(/^value-/), { target: { value: 'SO-2026-0001' } })
    fireEvent.click(screen.getByTestId('apply-filter'))
    await waitFor(() => {
      const body = JSON.parse(String(calls.filter((c) => c.url.includes('/query')).at(-1)!.init?.body))
      expect(body.filter).toEqual({ field: 'so_id', op: 'eq', value: 'SO-2026-0001' })
    })
  })

  it('surfaces the structured backend error', async () => {
    mockFetch([
      { match: '/meta/ontology', body: META },
      { match: '/objects/sales-order/query', status: 404, body: { code: 'NOT_FOUND', message: 'unknown filter field' } },
    ])
    render()
    await waitFor(() => expect(screen.getByTestId('error-banner')).toBeInTheDocument())
    expect(screen.getByTestId('error-banner')).toHaveTextContent('NOT_FOUND')
  })
})
