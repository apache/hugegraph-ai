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
 * DataMountDialog — attach real data to an object type.
 *
 * Reached from the ontology browser's detail column. Four source kinds (CSV
 * file / pasted CSV / SQLite / PostgreSQL), a column→property mapping preview
 * computed client-side with the same semantics the server applies (same-name
 * implicit, unmapped columns ignored), and the sync report with quarantine
 * detail.
 *
 * Mounting publishes immediately: the store resource and the object's backing
 * land on disk and the snapshot hot-reloads, so the dialog says so up front.
 * Unsaved canvas edits are untouched (they live in the draft, like every other
 * edit on the page).
 */
import { useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useFocusTrap } from '../lib/focus'
import { useI18n } from '../i18n'
import { apiClient, ApiError } from '../api/client'
import { storageQuery } from '../api/queries'
import { Alert, Badge, Button } from './ui'
import { IconCheck, IconX } from './icons'

/** The minimum the dialog needs from an object type — deliberately structural,
 *  so the ontology browser hands it straight off the DSL resource it already
 *  holds instead of mirroring the model into a second client-side shape. */
export interface MountableObject {
  name: string
  display?: string | null
  properties: Array<{ name: string; required?: boolean }>
}

type SourceKind = 'csv-file' | 'csv-paste' | 'sqlite' | 'postgres' | 'mysql'

type MountResult = Awaited<ReturnType<typeof apiClient.mountData>>

/** Minimal CSV header parse: quoted fields tolerated, no newlines in fields
 *  (a header row cannot contain them anyway). */
function parseHeader(text: string): string[] {
  const firstLine = text.split(/\r?\n/, 1)[0] ?? ''
  const out: string[] = []
  let cur = ''
  let quoted = false
  for (let i = 0; i < firstLine.length; i += 1) {
    const ch = firstLine[i]
    if (ch === '"') {
      if (quoted && firstLine[i + 1] === '"') { cur += '"'; i += 1 } else quoted = !quoted
    } else if (ch === ',' && !quoted) { out.push(cur.trim()); cur = '' } else cur += ch
  }
  out.push(cur.trim())
  return out.filter((c) => c !== '')
}

export function DataMountDialog({
  open, onClose, objects, defaultObject, onMounted,
}: {
  open: boolean
  onClose: () => void
  objects: MountableObject[]
  /** Preselected target (opened from a specific type's panel). */
  defaultObject?: string
  onMounted?: (result: MountResult) => void
}) {
  const { t } = useI18n()
  const trapRef = useFocusTrap<HTMLDivElement>(open)
  const fileRef = useRef<HTMLInputElement>(null)

  const [objectName, setObjectName] = useState(defaultObject ?? objects[0]?.name ?? '')
  const [kind, setKind] = useState<SourceKind>('csv-file')
  const [csv, setCsv] = useState('')
  const [filename, setFilename] = useState('')
  const [dsn, setDsn] = useState('')
  const [table, setTable] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [result, setResult] = useState<MountResult | null>(null)

  const selected = objects.find((o) => o.name === objectName)

  /** The type's CURRENT binding, straight from the server's storage summary:
   *  store kind (csv / sqlite / postgres / …), source, materialized rows. */
  const storage = useQuery(storageQuery())
  const stInfo = storage.data?.objects?.[objectName]
  const syncSummary = stInfo
    ? (stInfo.sync === 'watermark' && stInfo.sync_watermark
        ? `${t('storage.syncWatermark')} ${stInfo.sync_watermark}${stInfo.sync_schedule ? ` · ${stInfo.sync_schedule}` : ''}`
        : (stInfo.sync ?? ''))
    : ''

  /** Same-name mapping preview — exactly what the server will bind. */
  type MappingPreview = { mapped: Array<{ column: string; prop: string }>; ignored: string[]; missingRequired: string[] }
  const mapping = useMemo<MappingPreview>(() => {
    const all: Array<{ column: string; prop: string }> = selected
      ? selected.properties.map((p) => ({ column: p.name, prop: p.name }))
      : []
    if (!selected) return { mapped: all, ignored: [] as string[], missingRequired: [] as string[] }
    if (kind === 'sqlite' || kind === 'postgres' || kind === 'mysql') {
      // SQL columns are unknown until sync; identity mapping is the contract
      return { mapped: all, ignored: [] as string[], missingRequired: [] as string[] }
    }
    const header = parseHeader(csv)
    const known = new Set(all.map((m) => m.prop))
    const mapped = all.filter((m) => header.includes(m.column))
    const ignored = header.filter((c) => !known.has(c))
    // required properties the source would not provide: the server refuses
    // this binding (NOT NULL on insert), so say so before submitting
    const missingRequired = selected
      ? selected.properties.filter((p) => p.required && !header.includes(p.name)).map((p) => p.name)
      : []
    return { mapped, ignored, missingRequired }
  }, [selected, csv, kind])

  const missingRequired = kind.startsWith('csv') && csv.trim() ? mapping.missingRequired : []
  const canSubmit = Boolean(selected) && !busy && missingRequired.length === 0 && (
    kind === 'csv-file' || kind === 'csv-paste'
      ? csv.trim().includes('\n')
      : dsn.trim() !== '' && table.trim() !== ''
  )

  const submit = async () => {
    if (!selected || busy) return
    setBusy(true)
    setError(null)
    setResult(null)
    try {
      const binding = Object.fromEntries(mapping.mapped.map((m) => [m.prop, m.column]))
      const body = kind === 'csv-file' || kind === 'csv-paste'
        ? { object: selected.name, source: { kind: 'csv' as const, filename: filename || `${selected.name}.csv`, content: csv }, mapping: binding }
        : { object: selected.name, source: { kind: kind as 'sqlite' | 'postgres' | 'mysql', dsn, table }, mapping: binding }
      const out = await apiClient.mountData(body)
      setResult(out)
      onMounted?.(out)
    } catch (e) {
      setError(e instanceof ApiError ? `${e.code}: ${e.message}` : String(e))
    } finally {
      setBusy(false)
    }
  }

  if (!open) return null

  const kinds: Array<{ id: SourceKind; label: string }> = [
    { id: 'csv-file', label: t('mount.kind.file') },
    { id: 'csv-paste', label: t('mount.kind.paste') },
    { id: 'sqlite', label: 'SQLite' },
    { id: 'mysql', label: 'MySQL' },
    { id: 'postgres', label: 'PostgreSQL' },
  ]

  return (
    /* no dimmed backdrop: the page stays fully readable behind the dialog */
    <div
      className="fixed inset-0 z-50 grid place-items-center p-4"
      onClick={(e) => { if (e.target === e.currentTarget) onClose() }}
    >
      <div
        ref={trapRef}
        role="dialog"
        aria-modal="true"
        aria-label={t('mount.title')}
        data-testid="mount-dialog"
        className="ontogeny-card ontogeny-modal flex max-h-[92vh] w-full max-w-2xl flex-col overflow-hidden"
      >
        <header className="flex shrink-0 items-start justify-between gap-3 px-5 pb-3 pt-4" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
          <div className="min-w-0">
            <h2 className="text-[14px] font-semibold">{t('mount.title')}</h2>
            <p className="mt-0.5 text-[12px] muted">{t('mount.subtitle')}</p>
          </div>
          <button onClick={onClose} data-testid="mount-close" aria-label={t('common.close')}
            className="grid size-7 shrink-0 place-items-center rounded-lg hover:bg-[var(--surface-hover)]" style={{ color: 'var(--text-muted)' }}>
            <IconX width={14} height={14} />
          </button>
        </header>

        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-5 py-4">
          {/* target object */}
          <label className="block">
            <span className="ontogeny-label">{t('mount.object')}</span>
            <select className="ontogeny-input" data-testid="mount-object" value={objectName} onChange={(e) => { setObjectName(e.target.value); setResult(null) }}>
              {objects.map((o) => <option key={o.name} value={o.name}>{o.name}{o.display && o.display !== o.name ? ` · ${o.display}` : ''}</option>)}
            </select>
          </label>

          {/* what this type is ALREADY mounted to, before anything new is chosen */}
          {stInfo ? (
            <div className="rounded-lg p-3 text-[12px]" style={{ background: 'var(--surface-sunken)' }} data-testid="mount-current">
              <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.06em] muted">{t('mount.current')}</div>
              <div className="flex flex-wrap gap-x-4 gap-y-1">
                <span>
                  {t('mount.currentKind')}:{' '}
                  <Badge tone="brand" mono>{(stInfo.store_type ?? '?').toUpperCase()}</Badge>
                </span>
                <span>
                  {t('mount.currentSource')}: <span className="font-mono">{stInfo.store}{stInfo.source_table ? `.${stInfo.source_table}` : ''}</span>
                </span>
                <span>
                  {t('mount.currentRows')}: <b className="tnum">{stInfo.rows ?? '—'}</b>
                </span>
                <span>
                  {t('mount.currentTable')}: <span className="font-mono">{stInfo.table}</span>
                </span>
              </div>
              {stInfo.sync ? (
                <div className="mt-1.5 text-[11px] muted">{syncSummary}</div>
              ) : null}
            </div>
          ) : (
            <p className="text-[12px] muted" data-testid="mount-none">{t('mount.none')}</p>
          )}

          {/* source kind */}
          <div>
            <span className="ontogeny-label">{t('mount.source')}</span>
            <div className="flex flex-wrap gap-1.5">
              {kinds.map((k) => (
                <button key={k.id} data-testid={`mount-kind-${k.id}`}
                  onClick={() => { setKind(k.id); setResult(null) }}
                  className="rounded-lg px-2.5 py-1.5 text-[12px] font-medium transition-colors"
                  style={{
                    background: kind === k.id ? 'var(--brand-tint)' : 'var(--surface-sunken)',
                    color: kind === k.id ? 'var(--brand-fg)' : 'var(--text-secondary)',
                    boxShadow: kind === k.id ? 'inset 0 0 0 1px var(--brand-tint-ring)' : 'none',
                  }}>
                  {k.label}
                </button>
              ))}
            </div>
          </div>

          {/* source input */}
          {kind === 'csv-file' ? (
            <div>
              <span className="ontogeny-label">{t('mount.pickFile')}</span>
              <input ref={fileRef} type="file" accept=".csv,text/csv" data-testid="mount-file"
                className="block w-full text-[12.5px]"
                onChange={async (e) => {
                  const f = e.target.files?.[0]
                  if (!f) return
                  setFilename(f.name)
                  setCsv(await f.text())
                  setResult(null)
                }} />
              {csv ? <p className="mt-1 text-[11.5px] muted">{filename} · {t('mount.loaded')}</p> : null}
            </div>
          ) : null}
          {kind === 'csv-paste' ? (
            <label className="block">
              <span className="ontogeny-label">{t('mount.pasteHere')}</span>
              <textarea className="ontogeny-input font-mono text-[12px]" rows={6} data-testid="mount-paste"
                placeholder={'work_order_id,title,status\nWO-1,检查,OPEN'}
                value={csv} onChange={(e) => { setCsv(e.target.value); setResult(null) }} />
            </label>
          ) : null}
          {kind === 'sqlite' || kind === 'postgres' ? (
            <div className="grid gap-3 sm:grid-cols-2">
              <label className="block">
                <span className="ontogeny-label">DSN</span>
                <input className="ontogeny-input font-mono text-[12px]" data-testid="mount-dsn"
                  placeholder={kind === 'sqlite' ? 'sqlite+aiosqlite:///path/db.sqlite' : 'postgresql+asyncpg://…'}
                  value={dsn} onChange={(e) => { setDsn(e.target.value); setResult(null) }} />
              </label>
              <label className="block">
                <span className="ontogeny-label">{t('mount.table')}</span>
                <input className="ontogeny-input font-mono text-[12px]" data-testid="mount-table"
                  value={table} onChange={(e) => { setTable(e.target.value); setResult(null) }} />
              </label>
            </div>
          ) : null}

          {/* mapping preview */}
          {kind.startsWith('csv') && csv.trim() ? (
            <div className="rounded-lg p-3" style={{ background: 'var(--surface-sunken)' }} data-testid="mount-preview">
              <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.06em] muted">{t('mount.mapping')}</div>
              <div className="flex flex-wrap gap-1.5">
                {mapping.mapped.map((m) => (
                  <Badge key={m.column} tone="brand" mono>{m.column} → {m.prop}</Badge>
                ))}
                {mapping.ignored.map((c) => <Badge key={c} mono title={t('mount.ignoredHint')}>{c} · {t('mount.ignored')}</Badge>)}
              </div>
              <p className="mt-2 text-[11px] muted">{t('mount.mappingHint')}</p>
              {missingRequired.length ? (
                <Alert tone="warning" testId="mount-missing-required">
                  {t('mount.missingRequired', { fields: missingRequired.join(', ') })}
                </Alert>
              ) : null}
            </div>
          ) : null}

          {error ? <Alert tone="danger" testId="mount-error">{error}</Alert> : null}

          {result ? (
            <div className="rounded-lg p-3" style={{ background: 'var(--tone-success-bg)', border: '1px solid var(--tone-success-ring)' }} data-testid="mount-result">
              <div className="flex items-center gap-2 text-[13px] font-semibold" style={{ color: 'var(--tone-success-fg)' }}>
                <IconCheck width={14} height={14} />{t('mount.done')}
              </div>
              <div className="mt-1.5 flex flex-wrap gap-x-4 gap-y-1 text-[12px] secondary-text">
                <span>{t('mount.inserted')}: <b className="tnum">{result.sync.inserted}</b></span>
                <span>{t('mount.updated')}: <b className="tnum">{result.sync.updated}</b></span>
                <span>{t('mount.quarantined')}: <b className="tnum">{result.sync.quarantined}</b></span>
              </div>
              {result.quarantine.length ? (
                <ul className="mt-2 space-y-1">
                  {result.quarantine.map((q, i) => (
                    <li key={i} className="font-mono text-[11px]" style={{ color: 'var(--tone-warning-fg)' }}>
                      {q.pk ?? '—'} · {q.code} · {q.reason}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : null}
        </div>

        <footer className="flex shrink-0 items-center justify-between gap-3 px-5 py-3" style={{ borderTop: '1px solid var(--border-subtle)' }}>
          <span className="text-[11px] muted">{t('mount.publishNote')}</span>
          <div className="flex gap-2">
            <Button onClick={onClose} data-testid="mount-cancel">{t('common.close')}</Button>
            <Button variant="primary" disabled={!canSubmit} onClick={submit} data-testid="mount-submit">
              {busy ? t('mount.mounting') : t('mount.confirm')}
            </Button>
          </div>
        </footer>
      </div>
    </div>
  )
}
