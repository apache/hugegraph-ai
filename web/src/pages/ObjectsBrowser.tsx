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
/**
 * The object browser: one type's rows, filterable and server-paged.
 *
 * The table is the *body*; the route wraps it in a page and the type detail
 * panel opens the same body in a dialog. One implementation, two frames — the
 * reader gets the rows without leaving the model they were reading.
 */
import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import { keys, storageQuery, useMeta } from '../api/queries'
import { useI18n } from '../i18n'
import { Badge, Button, Card, Page, Skeleton } from '../components/ui'
import { DataTable, type Column } from '../components/DataTable'
import { ErrorBanner } from '../components/ErrorBanner'
import { fieldLabel } from '../lib/rows'
import { FilterBuilder, buildFilter, type Condition } from '../components/FilterBuilder'
import { IconTable } from '../components/icons'

const PAGE_SIZE = 20

export function ObjectsBrowser() {
  const { type = '' } = useParams()
  return (
    <Page>
      <h1 className="sr-only">{type}</h1>
      <ObjectsBrowserBody type={type} />
    </Page>
  )
}

/** The rows table itself, without page chrome. */
export function ObjectsBrowserBody({ type, onNavigate }: {
  type: string
  /** Called instead of routing, when the table is inside a dialog (the caller
   *  closes the dialog and navigates, so the modal never stacks on a new page). */
  onNavigate?: (to: string) => void
}) {
  const { t, plural } = useI18n()
  const nav = useNavigate()
  const meta = useMeta()
  const storage = useQuery(storageQuery())
  const [conditions, setConditions] = useState<Condition[]>([])
  const [applied, setApplied] = useState<unknown>(undefined)
  const [page, setPage] = useState(0)
  // the order lives on the server: this table shows one page of many, so
  // sorting it client-side would order only what happens to be on screen
  const [sort, setSort] = useState<{ key: string; dir: 'asc' | 'desc' } | null>(null)

  const objMeta = meta.data?.objects[type]
  const fields = useMemo(() => (objMeta ? Object.keys(objMeta.properties) : []), [objMeta])
  const pk = objMeta?.primaryKey[0] ?? 'id'

  const q = useQuery({
    // `sort` MUST be part of the key: the queryFn reads it, and React Query
    // only re-runs when the key changes. Without it, clicking a column header
    // on page 0 (where setPage(0) is a no-op) silently kept the old order.
    queryKey: keys.objects(type, applied, page, sort ? `${sort.key}:${sort.dir}` : null),
    queryFn: () => apiClient.queryObjects(type, {
      filter: applied,
      limit: PAGE_SIZE,
      offset: page * PAGE_SIZE,
      sort: [[sort?.key ?? pk, sort?.dir ?? 'asc']],
    }),
    enabled: Boolean(objMeta),
  })

  const columns: Array<Column<Record<string, unknown>>> = useMemo(
    () => fields.map((f) => ({
      key: f,
      label: fieldLabel(f, objMeta?.properties[f]?.display, f === pk),
      align: /qty|minutes|rate|score|price|cost/.test(f) ? 'right' as const : 'left' as const,
    })),
    [fields, pk, objMeta],
  )

  if (meta.isLoading) return <Skeleton rows={6} />
  if (meta.error) return <ErrorBanner error={meta.error} />
  if (!objMeta) return <ErrorBanner error={{ code: 'NOT_FOUND', message: `unknown object type: ${type}` }} />

  const go = (to: string) => { if (onNavigate) onNavigate(to); else nav(to) }

  // say exactly where this type's data is materialized: the platform db, the
  // object table, the backing source and the sync that pulls rows in
  const st = storage.data
  const stInfo = st?.objects?.[type]
  const syncLabel = stInfo
    ? (stInfo.sync === 'watermark' && stInfo.sync_watermark
        ? `${t('storage.syncWatermark')} ${stInfo.sync_watermark}${stInfo.sync_schedule ? ` · ${stInfo.sync_schedule}` : ''}`
        : (stInfo.sync ?? ''))
      .trim()
    : ''

  return (
    <>
      {st && stInfo ? (
        <div
          className="mb-5 rounded-lg px-3.5 py-2.5 text-[12px] leading-relaxed"
          style={{ background: 'var(--surface-sunken)' }}
          data-testid="storage-where"
        >
          <span className="muted">{t('storage.where')}</span>{' '}
          <span style={{ color: 'var(--text-body)' }}>
            {st.target.kind} · <span className="font-mono">{st.target.target}</span> ·{' '}
            <span className="font-mono">{stInfo.table}</span>
          </span>
          {stInfo.store ? (
            <span className="muted">
              {'  ·  '}{t('storage.source')}{': '}<span className="font-mono">{stInfo.store}.{stInfo.source_table}</span>
              {syncLabel ? `  ·  ${syncLabel}` : ''}
            </span>
          ) : null}
          {stInfo.rows != null ? (
            <span className="muted">{'  ·  '}{t('storage.rows', { rows: stInfo.rows })}</span>
          ) : null}
        </div>
      ) : null}

      <Card title={t('objects.filter')} className="mb-5">
        <FilterBuilder fields={fields} value={conditions} onChange={setConditions} />
        <div className="mt-3 flex gap-2">
          <Button
            variant="primary"
            data-testid="apply-filter"
            onClick={() => { setPage(0); setApplied(buildFilter(conditions)) }}
          >
            {t('common.apply')}
          </Button>
          <Button onClick={() => { setConditions([]); setApplied(undefined); setPage(0) }}>{t('common.clear')}</Button>
          <Button onClick={() => q.refetch()} icon={<IconTable width={14} height={14} />}>{t('common.refresh')}</Button>
        </div>
      </Card>

      {q.error ? <ErrorBanner error={q.error} /> : null}

      {/* the breadcrumb, the type and the query stats all live on the rows
          panel itself: it is the page's one primary surface */}
      <Card
        padded={false}
        title={<span className="font-mono text-[12.5px]">{type}</span>}
        description={objMeta.display}
        actions={
          q.data ? (
            <span className="flex items-center gap-2">
              <Badge tone="neutral">{t('objects.latency', { ms: q.data.latency_ms })}</Badge>
              <Badge tone="brand">{plural('objects.rowCount', q.data.total)}</Badge>
            </span>
          ) : null
        }
      >
      <DataTable
        columns={columns}
        rows={q.data?.objects ?? []}
        rowKey={(row, i) => String(row[pk] ?? i)}
        loading={q.isLoading}
        onRowClick={(row) => go(`/objects/${type}/${encodeURIComponent(String(row[pk]))}`)}
        page={page}
        pageSize={PAGE_SIZE}
        total={q.data?.total}
        onPrev={() => setPage((p) => Math.max(0, p - 1))}
        onNext={() => setPage((p) => p + 1)}
        sortable
        // server-side order: changing it re-queries from the first page, since
        // "page 3 of the new order" is not the same rows as "page 3" of the old
        sort={sort}
        onSortChange={(next) => { setSort(next); setPage(0) }}
      />
      </Card>
    </>
  )
}
