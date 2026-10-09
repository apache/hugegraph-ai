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
import { useMemo, useState, type ReactNode } from 'react'
import { useI18n } from '../i18n'
import { Button, EmptyState, Skeleton } from './ui'
import { formatCell } from '../lib/rows'
import { IconArrowLeft, IconChevron } from './icons'

export interface Column<T> {
  key: string
  label?: ReactNode
  align?: 'left' | 'right'
  render?: (row: T) => ReactNode
  /** Sort by this column. Without it the header is not interactive — a table
   *  whose rows can't be ordered is the norm here, so it stays opt-in. */
  sortable?: boolean
  /** Value to order by; defaults to the row's own field for `key`. */
  sortValue?: (row: T) => unknown
}

export type SortState = { key: string; dir: 'asc' | 'desc' }

/** Orders two non-blank cell values: numbers numerically, everything else as a
 *  locale-aware string. Blanks are handled by the caller, which must keep them
 *  at the end in both directions — folding them into this function let the sort
 *  direction negate the result and move empty cells to the top when descending. */
function compare(a: unknown, b: unknown): number {
  if (typeof a === 'number' && typeof b === 'number') return a - b
  const na = Number(a)
  const nb = Number(b)
  if (!Number.isNaN(na) && !Number.isNaN(nb)) return na - nb
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: 'base' })
}

const isBlank = (v: unknown) => v === null || v === undefined || v === ''

export function DataTable<T extends object>({
  columns, rows, rowKey, onRowClick, loading, page, pageSize, total, onPrev, onNext, empty, sortable = false,
  sort: sortProp, onSortChange,
}: {
  columns: Array<Column<T>>
  rows: T[]
  rowKey: (row: T, index: number) => string
  onRowClick?: (row: T) => void
  loading?: boolean
  page?: number
  pageSize?: number
  total?: number
  onPrev?: () => void
  onNext?: () => void
  empty?: ReactNode
  /** Turn on header-click sorting for every column unless it opts out with
   *  `sortable: false`. Off by default: most tables here are short previews
   *  where sorting would be noise. */
  sortable?: boolean
  /** Controlled sort, for a *server-paginated* table: the caller owns the order
   *  (and re-queries with it) instead of DataTable ordering the page it was
   *  handed — which would be a lie, since the rows on screen are one page of
   *  many. */
  sort?: SortState | null
  onSortChange?: (sort: SortState | null) => void
}) {
  const { t, plural } = useI18n()
  const [ownSort, setOwnSort] = useState<SortState | null>(null)
  const controlled = onSortChange !== undefined
  const sort = controlled ? (sortProp ?? null) : ownSort
  const hasPager = onPrev !== undefined || onNext !== undefined
  const pageCount = total !== undefined && pageSize ? Math.max(1, Math.ceil(total / pageSize)) : undefined

  const canSort = (c: Column<T>) => c.sortable ?? sortable

  /** Sorted copy. The pager is server-side, so paginated tables sort only the
   *  page they were given — hence `sortable` is left off where that would lie. */
  const ordered = useMemo(() => {
    // controlled: the caller has already asked the server for this order
    if (controlled || !sort) return rows
    const col = columns.find((c) => c.key === sort.key)
    if (!col) return rows
    const value = (row: T) => col.sortValue
      ? col.sortValue(row)
      : (row as Record<string, unknown>)[col.key]
    const sign = sort.dir === 'asc' ? 1 : -1
    return [...rows].sort((a, b) => {
      const va = value(a)
      const vb = value(b)
      // blanks stay at the end in BOTH directions: outside the `sign`
      // multiplication, so "descending" cannot float empty cells to the top
      const ba = isBlank(va)
      const bb = isBlank(vb)
      if (ba || bb) return ba && bb ? 0 : ba ? 1 : -1
      return sign * compare(va, vb)
    })
  }, [rows, columns, sort, controlled])

  const toggle = (key: string) => {
    const next = (prev: SortState | null): SortState =>
      prev?.key === key ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' }
    if (controlled) onSortChange(next(sort))
    else setOwnSort(next)
  }

  if (loading) return <div className="p-5"><Skeleton rows={5} /></div>

  return (
    <div className="overflow-hidden" data-testid="data-table">
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            <tr>
              {columns.map((c) => {
                const active = sort?.key === c.key
                return (
                  <th
                    key={c.key}
                    scope="col"
                    className="ontogeny-th"
                    style={{ textAlign: c.align === 'right' ? 'right' : 'left' }}
                    aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : undefined}
                  >
                    {canSort(c) ? (
                      <button
                        type="button"
                        data-testid={`sort-${c.key}`}
                        onClick={() => toggle(c.key)}
                        title={t('common.sortBy', { column: typeof c.label === 'string' ? c.label : c.key })}
                        className="inline-flex items-center gap-1 uppercase transition-colors hover:text-[var(--text-primary)]"
                        style={{ color: active ? 'var(--text-primary)' : undefined }}
                      >
                        {c.label ?? c.key}
                        <IconChevron
                          width={11}
                          height={11}
                          className="shrink-0 transition-transform"
                          style={{
                            transform: active && sort.dir === 'desc' ? 'rotate(-90deg)' : 'rotate(90deg)',
                            opacity: active ? 1 : 0.35,
                          }}
                        />
                      </button>
                    ) : (c.label ?? c.key)}
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {ordered.length === 0 ? (
              <tr>
                <td className="ontogeny-td" colSpan={columns.length}>
                  <EmptyState title={empty ?? t('common.empty')} />
                </td>
              </tr>
            ) : (
              ordered.map((row, i) => (
                <tr
                  key={rowKey(row, i)}
                  onClick={onRowClick ? () => onRowClick(row) : undefined}
                  className={`transition-colors ${onRowClick ? 'cursor-pointer' : ''} hover:bg-[var(--surface-hover)]`}
                >
                  {columns.map((c) => (
                    <td
                      key={c.key}
                      className={`ontogeny-td ${c.align === 'right' ? 'num' : ''}`}
                    >
                      {c.render ? c.render(row) : formatCell(get(row, c.key))}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      {hasPager ? (
        <div className="flex items-center justify-between px-4 py-2.5 text-[12.5px] muted" style={{ borderTop: '1px solid var(--border-subtle)' }}>
          <span>
            {total !== undefined ? plural('common.rows', total) : ''}
            {pageCount !== undefined && page !== undefined ? ` · ${t('common.page', { page: page + 1, total: pageCount })}` : ''}
          </span>
          <div className="flex gap-2">
            <Button size="sm" disabled={!page} onClick={onPrev} data-testid="pager-prev" icon={<IconArrowLeft width={13} height={13} />}>
              {t('common.prev')}
            </Button>
            <Button
              size="sm"
              disabled={page === undefined || pageCount === undefined || page + 1 >= pageCount}
              onClick={onNext}
              data-testid="pager-next"
            >
              {t('common.next')}
              <IconChevron width={13} height={13} />
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  )
}

function get(row: object, key: string): unknown {
  return (row as Record<string, unknown>)[key]
}
