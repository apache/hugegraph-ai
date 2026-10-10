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
 * The sample rows of one object type, shown under its editor.
 *
 * The Knowledge page's whole point is that the *model* and the *data* are two
 * views of one thing: you edit a property and immediately see the rows it
 * describes, read through the normal query path (derived properties computed,
 * marked fields masked). Rows are read-only — a governed write goes through an
 * action, which is what the Action page is for.
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../../api/client'
import { useI18n } from '../../i18n'
import { Badge, Button, EmptyState, Panel, Skeleton } from '../../components/ui'
import { DataTable } from '../../components/DataTable'
import { ErrorBanner } from '../../components/ErrorBanner'
import { columnsOf } from '../../lib/rows'
import { ObjectsDialog } from '../../components/ObjectsDialog'
import { IconRefresh, IconTable } from '../../components/icons'

export function SampleRows({ type }: { type: string }) {
  const { t, plural } = useI18n()
  // the full browser opens over the page: the rows are the same subject as the
  // model being edited, so leaving the editor to read them is the wrong move
  const [browse, setBrowse] = useState(false)
  const preview = useQuery({
    queryKey: ['data-preview', 'single', type, 5],
    queryFn: () => apiClient.dataPreview(5),
  })

  const entry = preview.data?.objects.find((o) => o.type === type)

  return (
    <Panel className="p-0">
      <header
        className="flex flex-wrap items-center gap-2 px-3.5 py-2.5"
        style={{ borderBottom: '1px solid var(--border-subtle)' }}
      >
        <h3 className="text-[12px] font-semibold tracking-wide">{t('ed.sampleRows')}</h3>
        {entry?.total !== null && entry?.total !== undefined ? (
          <Badge tone="neutral">{plural('data.rows', entry.total)}</Badge>
        ) : null}
        <span className="ml-auto flex items-center gap-2">
          <Button
            size="sm"
            data-testid="open-objects-dialog"
            onClick={() => setBrowse(true)}
            icon={<IconTable width={13} height={13} />}
          >
            {t('data.openBrowser')}
          </Button>
          <Button
            size="sm"
            square
            data-testid="sample-refresh"
            title={t('common.refresh')}
            aria-label={t('common.refresh')}
            onClick={() => preview.refetch()}
            icon={<IconRefresh width={13} height={13} />}
          />
        </span>
      </header>

      <div className="p-3">
        {preview.isLoading ? <Skeleton rows={3} />
        : preview.error ? <ErrorBanner error={preview.error} />
        : !entry ? <EmptyState bare compact title={t('data.empty')} />
        : entry.error ? <EmptyState bare compact title={t('data.unreadable', { code: entry.error })} />
        : entry.rows.length === 0 ? <EmptyState bare compact title={t('data.empty')} />
        : (
          <div className="overflow-hidden rounded-lg" style={{ border: '1px solid var(--border-subtle)' }}>
            <DataTable
              columns={columnsOf(entry.rows, entry.primary_key)}
              rows={entry.rows}
              rowKey={(row, i) => String(row[entry.primary_key] ?? i)}
            />
          </div>
        )}
      </div>

      <ObjectsDialog type={browse ? type : null} onClose={() => setBrowse(false)} />
    </Panel>
  )
}
