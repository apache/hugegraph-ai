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
/** The data-mounting dialog: source kinds, the mapping preview, and the sync
 *  report. The contract it must keep: the preview's mapping semantics are the
 *  server's (same-name columns bind; unmapped columns are skipped), and the
 *  report says how many rows landed and how many were quarantined — a mount
 *  that silently swallowed bad rows would be worse than no report at all. */
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { mockFetch } from '../test/setup'
import { renderWithProviders } from '../test/render'
import { DataMountDialog } from './DataMountDialog'
import type { MountableObject } from './DataMountDialog'

const OBJECTS: MountableObject[] = [
  {
    name: 'work-order', display: '维修工单',
    properties: [
      { name: 'work_order_id', required: true },
      { name: 'title', required: true },
      { name: 'priority', required: false },
    ],
  },
  {
    name: 'equipment', display: '设备',
    properties: [{ name: 'equipment_id', required: true }],
  },
]

const MOUNT_OK = {
  published: true, store: 'csv-work-order', object: 'work-order',
  mapping: { work_order_id: 'work_order_id', title: 'title', priority: 'priority' },
  sync: { inserted: 3, updated: 0, noop: 0, quarantined: 1 },
  quarantine: [{ pk: 'WO-BAD', code: 'TYPE_MISMATCH', reason: 'priority URGENT not in enum' }],
}

const render = () => renderWithProviders(
  <DataMountDialog open onClose={vi.fn()} objects={OBJECTS} />,
  { path: '/ontology', route: '/ontology' },
)

describe('DataMountDialog', () => {
  it('previews the same-name column mapping for pasted CSV', async () => {
    mockFetch([{ match: '/admin/builder/mount', body: MOUNT_OK }])
    render()

    fireEvent.click(await screen.findByTestId('mount-kind-csv-paste'))
    fireEvent.change(await screen.findByTestId('mount-paste'), { target: { value: (
      'work_order_id,title,priority,unknown_col\nWO-1,检查,HIGH,x\nWO-2,巡检,LOW,y'
    ) } })

    const preview = screen.getByTestId('mount-preview')
    // same-name columns bind, one per declared property…
    expect(preview.textContent).toContain('work_order_id → work_order_id')
    expect(preview.textContent).toContain('priority → priority')
    // …and the column nothing declares is reported as ignored
    expect(preview.textContent).toContain('unknown_col')
  })

  it('mounts pasted CSV and reports rows plus quarantine detail', async () => {
    const m = mockFetch([{ match: '/admin/builder/mount', body: MOUNT_OK }])
    render()
    fireEvent.click(await screen.findByTestId('mount-kind-csv-paste'))
    fireEvent.change(await screen.findByTestId('mount-paste'), { target: { value: 'work_order_id,title,priority\nWO-1,检查,HIGH' } })
    fireEvent.click(screen.getByTestId('mount-submit'))

    await screen.findByTestId('mount-result')
    expect(screen.getByText('Mounted — data synced')).toBeInTheDocument()
    expect(screen.getByText(/Quarantined/)).toBeInTheDocument()
    // the failed row is named, so the user can fix the source file
    expect(screen.getByText(/WO-BAD · TYPE_MISMATCH/)).toBeInTheDocument()

    const call = m.calls.find((c: { url: string }) => c.url.includes('/admin/builder/mount'))
    const body = JSON.parse(String(call!.init!.body))
    expect(body.object).toBe('work-order')
    expect(body.source.kind).toBe('csv')
    // mapping is prop -> column for every declared property the header covered
    expect(body.mapping).toEqual({ work_order_id: 'work_order_id', title: 'title', priority: 'priority' })
  })

  it('reads a chosen file like pasted text', async () => {
    mockFetch([{ match: '/admin/builder/mount', body: MOUNT_OK }])
    render()
    const file = new File(['work_order_id,title\nWO-9,内容'], 'work_orders.csv', { type: 'text/csv' })
    fireEvent.change(screen.getByTestId('mount-file'), { target: { files: [file] } })

    await waitFor(() => expect(screen.getByText(/work_orders\.csv/)).toBeInTheDocument())
    expect(screen.getByTestId('mount-preview').textContent).toContain('work_order_id → work_order_id')
  })

  it('switches to SQL fields and sends the DSN contract', async () => {
    const m = mockFetch([{ match: '/admin/builder/mount', body: { ...MOUNT_OK, sync: { inserted: 1, updated: 0, noop: 0, quarantined: 0 }, quarantine: [] } }])
    render()
    fireEvent.click(await screen.findByTestId('mount-kind-sqlite'))
    fireEvent.change(screen.getByTestId('mount-dsn'), { target: { value: 'sqlite+aiosqlite:///x.db' } })
    fireEvent.change(screen.getByTestId('mount-table'), { target: { value: 'work_orders' } })
    fireEvent.click(screen.getByTestId('mount-submit'))

    await screen.findByTestId('mount-result')
    const call = m.calls.find((c: { url: string }) => c.url.includes('/admin/builder/mount'))
    const body = JSON.parse(String(call!.init!.body))
    expect(body.source).toMatchObject({ kind: 'sqlite', dsn: 'sqlite+aiosqlite:///x.db', table: 'work_orders' })
  })

  it('surfaces server validation errors instead of pretending success', async () => {
    mockFetch([{
      match: '/admin/builder/mount', status: 400,
      body: { code: 'DSL_INVALID', message: 'ACTION-OWNER: modify-target sets source-owned property' },
    }])
    render()
    fireEvent.click(await screen.findByTestId('mount-kind-csv-paste'))
    fireEvent.change(await screen.findByTestId('mount-paste'), { target: { value: 'work_order_id,title,priority\nWO-1,检查,HIGH' } })
    fireEvent.click(screen.getByTestId('mount-submit'))

    expect(await screen.findByTestId('mount-error')).toHaveTextContent('DSL_INVALID')
    expect(screen.queryByTestId('mount-result')).toBeNull()
  })

  it('warns and disables submit when the source misses required properties', async () => {
    mockFetch([{ match: '/admin/builder/mount', body: MOUNT_OK }])
    render()
    fireEvent.click(await screen.findByTestId('mount-kind-csv-paste'))
    // work_order_id only: title is required too and absent from the source
    fireEvent.change(await screen.findByTestId('mount-paste'), { target: { value: 'work_order_id\nWO-1' } })

    expect(await screen.findByTestId('mount-missing-required')).toHaveTextContent('title')
    expect(screen.getByTestId('mount-submit')).toBeDisabled()
  })

  it('disables submit until a source is provided', async () => {
    mockFetch([])
    render()
    const submit = await screen.findByTestId('mount-submit')
    expect(submit).toBeDisabled()
    fireEvent.click(screen.getByTestId('mount-kind-csv-paste'))
    fireEvent.change(await screen.findByTestId('mount-paste'), { target: { value: 'work_order_id,title,priority\nWO-1,检查,HIGH' } })
    await waitFor(() => expect(submit).toBeEnabled())
  })
})
