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
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import { keys, useMeta } from '../api/queries'
import { useI18n } from '../i18n'
import { Badge, Button, Card, Page, toneForStatus } from '../components/ui'
import { DataTable, type Column } from '../components/DataTable'
import { ErrorBanner } from '../components/ErrorBanner'
import { ObjectDetailDialog } from '../components/ObjectDetailDialog'
import { fmtDate } from '../lib/rows'
import type { RevisionRow } from '../api/types'

export function Audit() {
  const { t, lang, plural } = useI18n()
  const meta = useMeta()
  const [objectType, setObjectType] = useState('')
  const [action, setAction] = useState('')
  const [applied, setApplied] = useState<{ object_type?: string; action?: string }>({})
  // clicking a target object inspects it in place: a large dialog over the
  // audit trail, not a navigation away from it
  const [inspect, setInspect] = useState<{ type: string; id: string } | null>(null)

  const revisions = useQuery({
    queryKey: keys.revisions(applied),
    queryFn: () => apiClient.revisions({ object_type: applied.object_type || undefined, action: applied.action || undefined }),
  })

  const columns: Array<Column<RevisionRow>> = [
    { key: 'id', label: '#', render: (r) => <span className="num muted">{r.id}</span> },
    { key: 'action', label: t('audit.action'), render: (r) => <span className="font-mono text-[12px]">{r.action}</span> },
    {
      key: 'object_id',
      label: t('action.target'),
      render: (r) => (
        <>
          <button
            type="button"
            className="ontogeny-link font-mono text-[12px]"
            data-testid={`inspect-object-${r.id}`}
            title={t('drawer.openDetail')}
            onClick={() => setInspect({ type: r.object_type, id: r.object_id })}
          >
            {r.object_id}
          </button>
          <div className="muted text-[11px]">{r.object_type}</div>
        </>
      ),
    },
    { key: 'principal', label: t('audit.principal'), render: (r) => <span className="font-mono text-[12px]">{r.principal}</span> },
    { key: 'outcome', label: t('audit.outcome'), render: (r) => <Badge tone={toneForStatus(r.outcome)}>{t(`audit.outcome.${r.outcome}`)}</Badge> },
    { key: 'message', label: t('common.details'), render: (r) => (r.message ? <span className="text-[12px] secondary-text">{r.message}</span> : <span className="muted">—</span>) },
    { key: 'created_at', label: t('tour.generatedAt'), render: (r) => <span className="text-[12px] muted">{fmtDate(r.created_at, lang)}</span> },
  ]

  return (
    <Page>
      <h1 className="sr-only">{t('audit.title')}</h1>

      {revisions.error ? <ErrorBanner error={revisions.error} /> : null}

      <Card
        title={t('audit.log')}
        description={t('audit.subtitle')}
        padded={false}
        actions={<Badge tone="neutral" mono>{revisions.data ? plural('common.rows', revisions.data.revisions.length) : '—'}</Badge>}
        toolbar={
          <>
            <select
              aria-label={t('audit.objectType')}
              className="ontogeny-input w-56"
              value={objectType}
              onChange={(e) => setObjectType(e.target.value)}
            >
              <option value="">{t('audit.objectType')} — {t('audit.all')}</option>
              {Object.keys(meta.data?.objects ?? {}).map((o) => <option key={o}>{o}</option>)}
            </select>
            <select
              aria-label={t('audit.action')}
              className="ontogeny-input w-56"
              value={action}
              onChange={(e) => setAction(e.target.value)}
            >
              <option value="">{t('audit.action')} — {t('audit.all')}</option>
              {Object.keys(meta.data?.actions ?? {}).map((a) => <option key={a}>{a}</option>)}
            </select>
            <Button variant="primary" size="sm" data-testid="audit-apply" onClick={() => setApplied({ object_type: objectType, action })}>
              {t('common.apply')}
            </Button>
            <Button size="sm" className="ml-auto" onClick={() => { setObjectType(''); setAction(''); setApplied({}) }} data-testid="audit-clear">
              {t('common.clear')}
            </Button>
          </>
        }
      >
        {revisions.error ? (
          <div className="px-5 pb-5"><ErrorBanner error={revisions.error} /></div>
        ) : (
          <DataTable
            columns={columns}
            rows={(revisions.data?.revisions ?? []) as unknown as RevisionRow[]}
            rowKey={(r) => String(r.id)}
            loading={revisions.isLoading}
            sortable
          />
        )}
      </Card>

      <ObjectDetailDialog type={inspect?.type ?? null} id={inspect?.id ?? null} onClose={() => setInspect(null)} />
    </Page>
  )
}
