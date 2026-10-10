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
import { GraphExplorer } from './GraphExplorer'

const EXPLORE = {
  start: { type: 'equipment', id: 'EQ-01' },
  n_requested: 5,
  depth: 3,
  nodes: [
    { _type: 'equipment', _id: 'EQ-01', equipment_id: 'EQ-01', name: '加工中心' },
    { _type: 'maintenance-order', _id: 'MO-1', mo_id: 'MO-1', equipment_id: 'EQ-01' },
    { _type: 'work-center', _id: 'WC-01', work_center_id: 'WC-01' },
  ],
  edges: [
    { link: 'equipment-maintenance-orders', source: { type: 'equipment', id: 'EQ-01' }, target: { type: 'maintenance-order', id: 'MO-1' } },
  ],
  truncated: false,
}

const render = () => renderWithProviders(<GraphExplorer />, { path: '/graph', route: '/graph' })

describe('GraphExplorer — explore mode', () => {
  it('defaults to explore mode and runs a random exploration', async () => {
    const { calls } = mockFetch([
      { match: '/meta/ontology', body: META },
      { match: '/graph/explore', body: EXPLORE },
    ])
    render()
    await waitFor(() => expect(screen.getByTestId('run-explore')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('run-explore'))
    await waitFor(() => expect(screen.getByTestId('explore-result')).toBeInTheDocument())
    const body = JSON.parse(String(calls.find((c) => c.url.includes('/graph/explore'))!.init?.body))
    expect(body.n).toBe(12)          // defaults
    expect(body.max_depth).toBe(3)
    expect(body.start_type).toBeUndefined() // random: no start sent
    expect(screen.getAllByText(/EQ-01/).length).toBeGreaterThan(0)
  })

  it('seeded runs send the seed and are labelled reproducible', async () => {
    const { calls } = mockFetch([
      { match: '/meta/ontology', body: META },
      { match: '/graph/explore', body: EXPLORE },
    ])
    render()
    await waitFor(() => expect(screen.getByTestId('run-explore')).toBeInTheDocument())
    fireEvent.change(screen.getByLabelText(/随机种子|Seed/), { target: { value: '42' } })
    fireEvent.click(screen.getByTestId('run-explore'))
    await waitFor(() => expect(screen.getByTestId('explore-result')).toBeInTheDocument())
    const body = JSON.parse(String(calls.find((c) => c.url.includes('/graph/explore'))!.init?.body))
    expect(body.seed).toBe(42)
  })

  it('manual start sends type and id', async () => {
    const { calls } = mockFetch([
      { match: '/meta/ontology', body: META },
      { match: '/graph/explore', body: EXPLORE },
    ])
    render()
    await waitFor(() => expect(screen.getByTestId('run-explore')).toBeInTheDocument())
    fireEvent.click(screen.getByLabelText(/随机起点|Random start/)) // uncheck
    fireEvent.change(screen.getByLabelText(/start type|起点类型/i), { target: { value: 'customer' } })
    fireEvent.change(screen.getByLabelText(/start ids|起点 ID/i), { target: { value: 'EQ-05' } })
    fireEvent.click(screen.getByTestId('run-explore'))
    await waitFor(() => expect(screen.getByTestId('explore-result')).toBeInTheDocument())
    const body = JSON.parse(String(calls.find((c) => c.url.includes('/graph/explore'))!.init?.body))
    expect(body.start_type).toBe('customer')
    expect(body.start_id).toBe('EQ-05')
  })

  it('truncation notice appears when the engine flags it', async () => {
    mockFetch([
      { match: '/meta/ontology', body: META },
      { match: '/graph/explore', body: { ...EXPLORE, truncated: true } },
    ])
    render()
    await waitFor(() => expect(screen.getByTestId('run-explore')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('run-explore'))
    await waitFor(() => expect(screen.getByText(/仍有未探索分支|branches remain/)).toBeInTheDocument())
  })

  it('path mode still works via the tab', async () => {
    mockFetch([
      { match: '/meta/ontology', body: META },
      {
        match: '/graph/traverse',
        body: { steps: [{ type: 'equipment', ids: ['EQ-01'], objects: [{ equipment_id: 'EQ-01' }] }], final_ids: ['EQ-01'] },
      },
    ])
    render()
    await waitFor(() => expect(screen.getByTestId('tab-path')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('tab-path'))
    fireEvent.change(screen.getByLabelText(/起点 ID|Start ids/), { target: { value: 'EQ-01' } })
    fireEvent.click(screen.getByTestId('run-traverse'))
    await waitFor(() => expect(screen.getByTestId('traverse-result')).toBeInTheDocument())
  })
})
