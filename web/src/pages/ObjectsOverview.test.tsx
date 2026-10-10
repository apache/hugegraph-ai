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
import { ObjectsOverview } from './ObjectsOverview'

const PREVIEW = {
  objects: [
    {
      type: 'equipment',
      display: '设备',
      primary_key: 'equipment_id',
      total: 5,
      rows: [
        { equipment_id: 'EQ-01', name: '五面体加工中心', status: 'RUNNING' },
        { equipment_id: 'EQ-02', name: '数控车床 CL-20', status: 'DOWN' },
      ],
    },
    {
      type: 'material',
      display: '物料',
      primary_key: 'material_id',
      total: 6,
      rows: [],
      error: 'POLICY_DENIED',
    },
  ],
  total: 11,
}

describe('ObjectsOverview', () => {
  it('lists every object type with its row count and sample rows', async () => {
    const { calls } = mockFetch([{ match: '/data/preview', body: PREVIEW }])
    renderWithProviders(<ObjectsOverview onOpenBrowser={() => {}} />, { path: '/data', route: '/data' })

    await waitFor(() => expect(screen.getByText('五面体加工中心')).toBeInTheDocument())
    expect(screen.getByText('equipment')).toBeInTheDocument()
    expect(screen.getByText('数控车床 CL-20')).toBeInTheDocument()
    expect(screen.getAllByText('5 rows total').length).toBeGreaterThan(0)
    // header badge carries the grand total
    expect(screen.getByText(/2 object types · 11 rows total/)).toBeInTheDocument()
    // an unreadable type reports the error instead of blanking the page
    expect(screen.getByText(/not readable right now \(POLICY_DENIED\)/)).toBeInTheDocument()
    expect(calls.some((c) => c.url.includes('/api/v1/data/preview?limit=3'))).toBe(true)
  })

  it('switches the sample size and refetches with the new limit', async () => {
    const { calls } = mockFetch([{ match: '/data/preview', body: PREVIEW }])
    renderWithProviders(<ObjectsOverview onOpenBrowser={() => {}} />, { path: '/data', route: '/data' })
    await waitFor(() => expect(screen.getByText('五面体加工中心')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: '10' }))
    await waitFor(() =>
      expect(calls.some((c) => c.url.includes('/api/v1/data/preview?limit=10'))).toBe(true),
    )
  })

  it('offers each type its own browser, as a dialog rather than a route', async () => {
    // "open the browser" used to be a link to /objects/:type, which left the
    // page you were reading; it is now a callback the caller opens a dialog on
    mockFetch([{ match: '/data/preview', body: PREVIEW }])
    const opened: string[] = []
    renderWithProviders(<ObjectsOverview onOpenBrowser={(ty) => opened.push(ty)} />, { path: '/knowledge' })
    await waitFor(() => expect(screen.getByText('五面体加工中心')).toBeInTheDocument())

    const button = screen.getAllByText('Open the type browser')[0]
    expect(button.closest('a')).toBeNull()
    fireEvent.click(button)
    expect(opened).toEqual(['equipment'])
  })

  it('fuses the compiled model shape into each type card', async () => {
    mockFetch([{ match: '/data/preview', body: PREVIEW }])
    renderWithProviders(
      <ObjectsOverview onOpenBrowser={() => {}} meta={{
        package: 'p', content_hash: 'h',
        objects: {
          equipment: {
            display: '设备',
            primaryKey: ['equipment_id'],
            properties: { equipment_id: { type: 'string', required: true, marking: null } },
            links: ['work-center-equipment'],
            actions: ['start-maintenance'],
          },
        },
        actions: {}, functions: {}, projections: {},
      }} />,
      { path: '/data', route: '/data' },
    )
    await waitFor(() => expect(screen.getByText('五面体加工中心')).toBeInTheDocument())
    expect(screen.getByText('1 prop')).toBeInTheDocument()
    expect(screen.getByText('1 link')).toBeInTheDocument()
    expect(screen.getByText('1 action')).toBeInTheDocument()
    expect(screen.getByTestId('open-type-equipment').closest('a')).toHaveAttribute('href', '/ontology/equipment')
  })
})
