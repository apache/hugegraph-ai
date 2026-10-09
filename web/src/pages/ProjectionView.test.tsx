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
import { mockFetch } from '../test/setup'
import { renderWithProviders } from '../test/render'
import { ProjectionView } from './ProjectionView'

const SUMMARY = {
  configured: true,
  ok: true,
  name: 'supply-chain-graph',
  engine: 'hugegraph',
  graph: 'supply_chain',
  graphspace: 'DEFAULT',
  dialect: '1.7',
  objects: ['equipment'],
  links: ['inventory-material'],
  labels: {
    vertices: [
      { name: 'equipment', primary_keys: ['equipment_id'] },
      { name: 'inventory', primary_keys: ['inventory_id'] },
    ],
    edges: [{ name: 'inventory-material', source_label: 'material', target_label: 'inventory' }],
  },
  counts: { vertices: { equipment: 5, inventory: 7 }, edges: { 'inventory-material': 7 } },
}

const VERTICES = {
  label: 'equipment',
  rows: [{ equipment_id: 'EQ-01', name: '五面体加工中心', status: 'RUNNING', site: '__masked__' }],
  hidden: 0,
  sampled: 1,
}

const EDGES = {
  label: 'inventory-material',
  rows: [
    {
      id: 'S4:M-01>3>3>>S5:INV-01',
      link: 'inventory-material',
      source: { type: 'material', id: 'M-01', display: '铝合金板' },
      target: { type: 'inventory', id: 'INV-01', display: 'INV-01' },
    },
  ],
  hidden: 0,
  sampled: 1,
}

const render = () => renderWithProviders(<ProjectionView />, { path: '/graph', route: '/graph' })

describe('ProjectionView', () => {
  it('surfaces projection metadata, live label counts and sampled rows', async () => {
    const { calls } = mockFetch([
      { match: '/graph/projection/vertices', body: VERTICES },
      { match: '/graph/projection/edges', body: EDGES },
      { match: '/graph/projection', body: SUMMARY },
    ])
    render()

    await waitFor(() => expect(screen.getByText('hugegraph')).toBeInTheDocument())
    expect(screen.getByText('supply_chain')).toBeInTheDocument()
    expect(screen.getByText('DEFAULT')).toBeInTheDocument()
    expect(screen.getByText('1.7')).toBeInTheDocument()
    // edge direction table + sampled vertex rows (re-assembled by the engine).
    // A marked field arrives as the sentinel and renders as the app-wide masked
    // badge — never as the literal `__masked__` string.
    await waitFor(() => expect(screen.getByText('material → inventory')).toBeInTheDocument())
    expect(screen.getByTitle('masked')).toBeInTheDocument()
    expect(screen.queryByText('__masked__')).not.toBeInTheDocument()
    expect(calls.some((c) => c.url.includes('/graph/projection/vertices?label=equipment'))).toBe(true)
  })

  it('degrades gracefully when no projection is declared', async () => {
    mockFetch([
      { match: '/graph/projection', body: { configured: false, ok: false, reason: 'no projection declared' } },
    ])
    render()
    await waitFor(() => expect(screen.getByText('No graph projection configured')).toBeInTheDocument())
  })

  it('shows the rebuild action and posts to the rebuild endpoint', async () => {
    const { calls } = mockFetch([
      { match: '/graph/projection/vertices', body: VERTICES },
      { match: '/graph/projection/edges', body: EDGES },
      { match: '/graph/projection', body: SUMMARY },
      { match: '/admin/projection/rebuild', body: { vertices: 36, edges: 28 } },
    ])
    render()
    await waitFor(() => expect(screen.getByTestId('rebuild-projection')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('rebuild-projection'))
    await waitFor(() => {
      expect(calls.some((c) => c.url.includes('/admin/projection/rebuild'))).toBe(true)
    })
  })
})
