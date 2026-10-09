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
import { DataTable } from './DataTable'

const ROWS = [
  { id: 'SO-1', status: 'DRAFT', qty: 2 },
  { id: 'SO-2', status: 'CONFIRMED', qty: 5 },
]

const render = (ui: React.ReactElement) => renderWithProviders(ui)

describe('DataTable', () => {
  it('renders the requested columns and rows', () => {
    render(<DataTable rows={ROWS} rowKey={(r) => r.id} columns={[{ key: 'id' }, { key: 'status' }]} />)
    expect(screen.getByText('SO-1')).toBeInTheDocument()
    expect(screen.getByText('CONFIRMED')).toBeInTheDocument()
    expect(screen.queryByText('qty')).not.toBeInTheDocument()
  })

  it('flags masked sentinel values with a distinct badge', () => {
    render(<DataTable rows={[{ id: 'C-1', region: '__masked__' }]} rowKey={(r) => r.id} columns={[{ key: 'id' }, { key: 'region' }]} />)
    expect(screen.getByText('▒')).toBeInTheDocument()
    expect(screen.queryByText('__masked__')).not.toBeInTheDocument()
  })

  it('disables pager buttons at the boundaries', () => {
    const onPrev = vi.fn()
    const onNext = vi.fn()
    render(
      <DataTable rows={ROWS} rowKey={(r) => r.id} columns={[{ key: 'id' }]} page={0} pageSize={2} total={2} onPrev={onPrev} onNext={onNext} />,
    )
    expect(screen.getByTestId('pager-prev')).toBeDisabled()
    expect(screen.getByTestId('pager-next')).toBeDisabled()
    fireEvent.click(screen.getByTestId('pager-prev'))
    expect(onPrev).not.toHaveBeenCalled()
  })

  it('enables next when more pages exist and fires row clicks', () => {
    const onNext = vi.fn()
    const onRowClick = vi.fn()
    render(
      <DataTable rows={ROWS} rowKey={(r) => r.id} columns={[{ key: 'id' }]} page={0} pageSize={2} total={6} onNext={onNext} onRowClick={onRowClick} />,
    )
    fireEvent.click(screen.getByTestId('pager-next'))
    expect(onNext).toHaveBeenCalled()
    fireEvent.click(screen.getByText('SO-2'))
    expect(onRowClick).toHaveBeenCalledWith(ROWS[1])
  })

  it('shows a skeleton while loading', () => {
    render(<DataTable loading rows={[]} rowKey={() => 'x'} columns={[{ key: 'id' }]} />)
    expect(screen.getByTestId('skeleton')).toBeInTheDocument()
  })
})

/** Sorting: the header click, the direction toggle, and the empty-value rule.
 *
 * Every table in the app was unsortable (Column had no `sortable`), even though
 * /audit, /data and /objects/:type are all read by column ("which revisions
 * failed?", "which type has the most rows?"). */
describe('DataTable sorting', () => {
  const rows = [
    { id: 'a', qty: 10, name: 'Beta', note: null },
    { id: 'b', qty: 2, name: 'alpha', note: 'x' },
    { id: 'c', qty: 30, name: 'Gamma', note: null },
  ]
  const columns = [
    { key: 'name', sortable: true },
    { key: 'qty', sortable: true, align: 'right' as const },
    { key: 'note', sortable: true },
  ]
  const bodyRows = (container: HTMLElement) =>
    Array.from(container.querySelectorAll('tbody tr')).map((tr) => tr.querySelector('td')!.textContent)

  it('does not make headers interactive unless asked', () => {
    const { container } = render(
      <DataTable columns={[{ key: 'name' }]} rows={rows} rowKey={(r) => r.id} />,
    )
    expect(screen.queryByTestId('sort-name')).toBeNull()
    expect(container.querySelector('th')).toHaveAttribute('scope', 'col')
  })

  it('orders numbers numerically, not as text', () => {
    const { container } = render(
      <DataTable columns={columns} rows={rows} rowKey={(r) => r.id} sortable />,
    )
    fireEvent.click(screen.getByTestId('sort-qty'))
    // 2, 10, 30 — a string sort would give 10, 2, 30
    expect(container.querySelectorAll('tbody tr')[0].querySelectorAll('td')[1].textContent).toBe('2')
    expect(container.querySelectorAll('tbody tr')[2].querySelectorAll('td')[1].textContent).toBe('30')
  })

  it('toggles direction and reports it through aria-sort', () => {
    render(<DataTable columns={columns} rows={rows} rowKey={(r) => r.id} sortable />)
    const header = screen.getByTestId('sort-name').closest('th')!
    fireEvent.click(screen.getByTestId('sort-name'))
    expect(header).toHaveAttribute('aria-sort', 'ascending')
    fireEvent.click(screen.getByTestId('sort-name'))
    expect(header).toHaveAttribute('aria-sort', 'descending')
    // a third click starts over rather than sticking on descending
    fireEvent.click(screen.getByTestId('sort-name'))
    expect(header).toHaveAttribute('aria-sort', 'ascending')
  })

  it('keeps empty cells last whichever way the column is sorted', () => {
    const { container } = render(
      <DataTable columns={columns} rows={rows} rowKey={(r) => r.id} sortable />,
    )
    fireEvent.click(screen.getByTestId('sort-note'))
    // the row with a value leads in both directions; the two nulls trail it
    expect(bodyRows(container)[0]).toBe('alpha')
    expect(bodyRows(container).slice(1).sort()).toEqual(['Beta', 'Gamma'])
    fireEvent.click(screen.getByTestId('sort-note'))
    expect(bodyRows(container)[0]).toBe('alpha')
  })

  it('sorts case-insensitively so a lowercase name does not sink', () => {
    const { container } = render(
      <DataTable columns={columns} rows={rows} rowKey={(r) => r.id} sortable />,
    )
    fireEvent.click(screen.getByTestId('sort-name'))
    expect(bodyRows(container)).toEqual(['alpha', 'Beta', 'Gamma'])
  })
})

describe('DataTable controlled sort (server-paginated tables)', () => {
  const rows = [{ id: 'a', qty: 10 }, { id: 'b', qty: 2 }, { id: 'c', qty: 30 }]

  it('reports the requested order instead of ordering the page itself', () => {
    const onSortChange = vi.fn()
    render(
      <DataTable
        columns={[{ key: 'qty', sortable: true }]}
        rows={rows}
        rowKey={(r) => r.id}
        sort={null}
        onSortChange={onSortChange}
      />,
    )
    fireEvent.click(screen.getByTestId('sort-qty'))
    expect(onSortChange).toHaveBeenCalledWith({ key: 'qty', dir: 'asc' })
    // the rows are still exactly as given: one page of many, ordered by the server
    const cells = screen.getAllByRole('cell').map((c) => c.textContent)
    expect(cells).toEqual(['10', '2', '30'])
  })

  it('shows the caller’s order in the header and toggles from it', () => {
    const onSortChange = vi.fn()
    render(
      <DataTable
        columns={[{ key: 'qty', sortable: true }]}
        rows={rows}
        rowKey={(r) => r.id}
        sort={{ key: 'qty', dir: 'desc' }}
        onSortChange={onSortChange}
      />,
    )
    const header = screen.getByTestId('sort-qty').closest('th')!
    expect(header).toHaveAttribute('aria-sort', 'descending')
    fireEvent.click(screen.getByTestId('sort-qty'))
    expect(onSortChange).toHaveBeenCalledWith({ key: 'qty', dir: 'asc' })
  })
})
