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
 * ObjectsOverview: every declared object type with its row count and a
 * sample, read through the normal query path (derived properties + marking
 * masks apply).
 *
 * Lives in the data-preview page's "object data" tab, and fuses both halves of
 * the story per type: the model shape from the compiled meta (primary key,
 * property/link/action counts, jumps out to the type's detail and browser) and
 * the rows themselves.
 *
 * Layout: types that HAVE rows get a full-width block — header, model pills,
 * sample table — because a wide table is the point and every pixel of width
 * matters once a type has eight columns. Types with no rows collapse to one
 * compact index line (they are the majority, and a centred "no data" panel per
 * type turned the page into a screenful of grey). The two groups are ordered,
 * not separated: a type's own line says why it is quiet, so nothing needs a
 * legend.
 */
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import { useI18n } from '../i18n'
import { Alert, Badge, Button, Card, Skeleton } from '../components/ui'
import { DataTable } from '../components/DataTable'
import { ErrorBanner } from '../components/ErrorBanner'
import { columnsOf } from '../lib/rows'
import { IconRefresh, IconTable } from '../components/icons'
import type { OntologyMeta } from '../api/types'

/** field name -> the model's human name, so a table header reads 订单号 and not
 *  `so_id`. Only fields that actually have a `display:` are mapped; the rest
 *  keep the machine name (the column helper appends it as a subtitle). */
function propertyLabels(model: OntologyMeta['objects'][string] | undefined): Record<string, string | null | undefined> | undefined {
  if (!model) return undefined
  const out: Record<string, string | null | undefined> = {}
  for (const [name, def] of Object.entries(model.properties)) out[name] = def.display
  return out
}

interface PreviewType {
  type: string
  display?: string
  primary_key: string
  total: number | null
  rows: Record<string, unknown>[]
  error?: string
}

/** A type is "readable" when the sample actually came back with rows. */
const hasRows = (e: PreviewType) => !e.error && e.rows.length > 0

export function ObjectsOverview({ meta, onOpenBrowser }: {
  meta?: OntologyMeta
  /** Open a type's full browser. The dialog lives in the caller, so this
   *  component stays a pure view of the preview payload. */
  onOpenBrowser: (type: string) => void
}) {
  const { t, plural } = useI18n()
  const nav = useNavigate()
  const [limit, setLimit] = useState(3)

  const preview = useQuery({
    queryKey: ['data-preview', limit],
    queryFn: () => apiClient.dataPreview(limit),
  })

  const types = preview.data?.objects ?? []
  // the sample selector changes how much a *reader* sees, not what exists, so
  // keep the model's own declaration order inside each group
  const ordered = [...types].sort((a, b) => Number(hasRows(b)) - Number(hasRows(a)))

  return (
    <Card
      padded={false}
      /* One surface: the sample-size controls ride in the card's own toolbar
         instead of a second floating card above it. The tab strip already
         carries the type count, so this strip holds only what changes. */
      toolbar={
        <>
          <Badge tone="brand">
            {plural('data.types', types.length)} · {plural('data.rows', preview.data?.total ?? 0)}
          </Badge>
          <span className="h-5 w-px" style={{ background: 'var(--border-subtle)' }} />
          <span className="ontogeny-label" style={{ marginBottom: 0 }}>{t('data.limit')}</span>
          <div
            className="flex items-center gap-0.5 rounded-lg p-0.5"
            style={{ background: 'var(--surface-card)', border: '1px solid var(--border-subtle)' }}
            role="group"
            aria-label={t('data.limit')}
          >
            {[3, 5, 10].map((n) => (
              <button
                key={n}
                type="button"
                aria-pressed={n === limit}
                onClick={() => setLimit(n)}
                className="rounded-md px-2.5 py-[3px] font-mono text-[12px] transition-colors"
                style={n === limit
                  ? { background: 'var(--brand-tint)', color: 'var(--brand-fg)', fontWeight: 700 }
                  : { color: 'var(--text-muted)' }}
              >
                {n}
              </button>
            ))}
          </div>
          <span className="min-w-0 flex-1 truncate text-[11.5px] muted">{t('data.detailHint')}</span>
          <Button size="sm" onClick={() => preview.refetch()} icon={<IconRefresh width={14} height={14} />}>
            {t('common.refresh')}
          </Button>
        </>
      }
      bodyClassName="[&>section+section]:border-t [&>section+section]:border-[var(--border-subtle)]"
    >
      {preview.isLoading ? (
        <div className="px-5 py-4"><Skeleton rows={8} /></div>
      ) : preview.error ? (
        <div className="px-5 py-4"><ErrorBanner error={preview.error} /></div>
      ) : (
        ordered.map((entry) => {
          const model = meta?.objects[entry.type]
          const onOpen = (id: string) =>
            nav(`/objects/${encodeURIComponent(entry.type)}/${encodeURIComponent(id)}`)
          return hasRows(entry) ? (
            <TypeBlock key={entry.type} entry={entry} model={model} onOpen={onOpen} onOpenBrowser={onOpenBrowser} />
          ) : (
            <TypeRow key={entry.type} entry={entry} model={model} onOpenBrowser={onOpenBrowser} />
          )
        })
      )}
    </Card>
  )
}

/** Type facts shared by both layouts: the primary key and the model's size. */
function TypeFacts({ model, primaryKey, className }: {
  model?: OntologyMeta['objects'][string]
  primaryKey: string
  className?: string
}) {
  const { t, plural } = useI18n()
  const key = (model?.primaryKey ?? [primaryKey]).filter(Boolean)
  return (
    <div className={['flex flex-wrap items-center gap-x-2 gap-y-1.5', className].filter(Boolean).join(' ')}>
      <span className="ontogeny-label" style={{ marginBottom: 0 }}>{t('data.pk')}</span>
      {key.map((k) => <span key={k} className="ontogeny-code">{k}</span>)}
      {model ? (
        <>
          <span className="mx-0.5 h-4 w-px" style={{ background: 'var(--border-subtle)' }} />
          <Badge tone="brand">{plural('data.propCount', Object.keys(model.properties).length)}</Badge>
          <Badge tone="info">{plural('data.linkCount', model.links.length)}</Badge>
          <Badge tone="violet">{plural('data.actionCount', model.actions.length)}</Badge>
        </>
      ) : null}
    </div>
  )
}

/** A type with rows: name + counts, the model pills, then the sample table at
 *  the full width of the card (never squeezed into a side column). */
function TypeBlock({ entry, model, onOpen, onOpenBrowser }: {
  entry: PreviewType
  model?: OntologyMeta['objects'][string]
  onOpen: (id: string) => void
  onOpenBrowser: (type: string) => void
}) {
  const { t, plural } = useI18n()
  return (
    <section
      data-testid={`data-type-${entry.type}`}
      className="px-5 py-4"
    >
      <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <h3 className="flex min-w-0 flex-wrap items-center gap-2 text-[13px] font-semibold tracking-wide">
          <IconTable width={14} height={14} />
          <span className="font-mono">{entry.type}</span>
          {entry.display ? <span className="font-normal muted">{entry.display}</span> : null}
        </h3>
        <span className="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1.5">
          {entry.total !== null ? (
            <Badge tone="neutral">{plural('data.rows', entry.total)}</Badge>
          ) : null}
          <Link className="ontogeny-link text-[12px]" to={`/ontology/${entry.type}`} data-testid={`open-type-${entry.type}`}>
            {t('data.openType')}
          </Link>
          <button
            type="button"
            className="ontogeny-link text-[12px]"
            data-testid={`open-browser-${entry.type}`}
            onClick={() => onOpenBrowser(entry.type)}
          >
            {t('data.openBrowser')}
          </button>
        </span>
      </header>

      <TypeFacts model={model} primaryKey={entry.primary_key} className="mt-2.5" />

      <div className="mt-3">
        {entry.error ? (
          <Alert tone="warning">{t('data.unreadable', { code: entry.error })}</Alert>
        ) : (
          <div className="overflow-hidden rounded-lg" style={{ border: '1px solid var(--border-subtle)' }}>
            <DataTable
              columns={columnsOf(entry.rows, entry.primary_key, propertyLabels(model))}
              rows={entry.rows}
              rowKey={(row, i) => String(row[entry.primary_key] ?? i)}
              onRowClick={(row) => onOpen(String(row[entry.primary_key]))}
            />
          </div>
        )}
      </div>
    </section>
  )
}

/** A type with nothing to show: one line that still carries the model facts. */
function TypeRow({ entry, model, onOpenBrowser }: {
  entry: PreviewType
  model?: OntologyMeta['objects'][string]
  onOpenBrowser: (type: string) => void
}) {
  const { t } = useI18n()
  return (
    <section
      data-testid={`data-type-${entry.type}`}
      className="flex flex-wrap items-center gap-x-4 gap-y-1.5 px-5 py-2.5"
    >
      <h3 className="flex min-w-[190px] flex-1 items-center gap-2 text-[12.5px]">
        <IconTable width={13} height={13} className="shrink-0 muted" />
        <span className="font-mono">{entry.type}</span>
        {entry.display ? <span className="truncate font-normal muted">{entry.display}</span> : null}
      </h3>

      <TypeFacts model={model} primaryKey={entry.primary_key} />

      <span className="flex shrink-0 items-center gap-x-3">
        <span className="text-[11.5px] muted">
          {entry.error ? t('data.unreadable', { code: entry.error }) : t('data.empty')}
        </span>
        <Link className="ontogeny-link text-[12px]" to={`/ontology/${entry.type}`} data-testid={`open-type-${entry.type}`}>
          {t('data.openType')}
        </Link>
        <button
          type="button"
          className="ontogeny-link text-[12px]"
          onClick={() => onOpenBrowser(entry.type)}
        >
          {t('data.openBrowser')}
        </button>
      </span>
    </section>
  )
}
