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
 * The resource editors behind Knowledge and Action.
 *
 * One form per DSL resource, all built from the same small kit so a field looks
 * and behaves the same everywhere: a label, an input, and — where the DSL holds
 * a map (`properties`, `parameters`, `include.objects`) — a repeatable row list
 * with an explicit add and remove.
 *
 * Every editor works on the resource verbatim: `update` returns a new resource
 * with exactly one branch replaced, which is what keeps the save lossless.
 * Nothing here invents defaults for fields it does not show — that is the whole
 * point of editing the compiled resource instead of a mirror of it.
 */
import { useEffect, useId, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useI18n } from '../../i18n'
import { Alert, Badge, Button, Skeleton } from '../../components/ui'
import { ErrorBanner } from '../../components/ErrorBanner'
import { apiClient } from '../../api/client'
import { keys, storageQuery, useMeta } from '../../api/queries'
import { IconPlus, IconTrash } from '../../components/icons'
import { PythonEditor } from '../../components/CodeEditor'
import {
  CARDINALITIES, CAPABILITY_KINDS, FUNCTION_RUNTIMES, PROPERTY_TYPES, STEP_KINDS,
  asNamed, asObj, asStr, asStrList, fromNamed, uniqueName,
} from '../../api/resources'
import type { OntologyResource } from '../../api/types'

export interface EditorProps {
  resource: OntologyResource
  /** Replace this resource (marks it dirty). */
  update: (next: (res: OntologyResource) => OntologyResource) => void
  /** Rename this resource (the draft cascades object-type references). */
  rename: (to: string) => void
  /** Object-type names, for the selects that point at one. */
  objectNames: string[]
  /** Policy-set names, for an action's policy select. */
  policyNames: string[]
  /** Link-type names, for an action's modify-linked / set-link selects. */
  linkNames?: string[]
}

const spec = (r: OntologyResource) => r.spec
const withSpec = (r: OntologyResource, patch: Record<string, unknown>): OntologyResource => ({
  ...r, spec: { ...r.spec, ...patch },
})
const withMeta = (r: OntologyResource, patch: Record<string, unknown>): OntologyResource => ({
  ...r, metadata: { ...r.metadata, ...patch },
})

/* ------------------------------------------------------------------- kit */

function Field({ label, hint, children, wide = false }: {
  label: string
  hint?: string
  children: React.ReactNode
  wide?: boolean
}) {
  return (
    <label className={wide ? 'col-span-2 block min-w-0' : 'block min-w-0'}>
      <span className="ontogeny-label" style={{ marginBottom: 4 }}>{label}</span>
      {children}
      {hint ? <span className="mt-1 block text-[11px] muted">{hint}</span> : null}
    </label>
  )
}

function TextInput({ value, onChange, mono, placeholder, disabled, ...rest }: {
  value: string
  onChange: (v: string) => void
  mono?: boolean
  placeholder?: string
  disabled?: boolean
} & Omit<React.InputHTMLAttributes<HTMLInputElement>, 'value' | 'onChange' | 'placeholder' | 'disabled'>) {
  return (
    <input
      {...rest}
      className={`ontogeny-input ${mono ? 'font-mono text-[12px]' : ''}`}
      value={value}
      placeholder={placeholder}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
    />
  )
}

function Select({ value, onChange, options, allowEmpty, ...rest }: {
  value: string
  onChange: (v: string) => void
  options: Array<{ value: string; label: string }>
  allowEmpty?: string
} & Omit<React.SelectHTMLAttributes<HTMLSelectElement>, 'value' | 'onChange'>) {
  return (
    <select {...rest} className="ontogeny-input" value={value} onChange={(e) => onChange(e.target.value)}>
      {allowEmpty !== undefined ? <option value="">{allowEmpty}</option> : null}
      {options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  )
}

function Check({ label, checked, onChange, title }: {
  label: string
  checked: boolean
  onChange: (v: boolean) => void
  title?: string
}) {
  return (
    <label className="flex cursor-pointer items-center gap-2 py-1 text-[12.5px]" title={title}>
      <input type="checkbox" className="size-3.5" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {label}
    </label>
  )
}

/** A titled block inside a form (the DSL's own groupings). */
function Group({ title, count, action, children, hint }: {
  title: string
  count?: number
  action?: React.ReactNode
  hint?: string
  children: React.ReactNode
}) {
  return (
    <section className="rounded-xl p-3" style={{ background: 'var(--surface-sunken)' }}>
      <header className="mb-2.5 flex flex-wrap items-center gap-2">
        <h4 className="text-[11px] font-bold uppercase tracking-[0.08em] muted">{title}</h4>
        {count !== undefined ? <Badge tone="neutral" mono>{count}</Badge> : null}
        <span className="ml-auto flex items-center gap-2">{action}</span>
      </header>
      {hint ? <p className="mb-2 text-[11px] muted">{hint}</p> : null}
      {children}
    </section>
  )
}

/** One editable row of a map-shaped DSL collection. */
function Row({ children, onRemove, removeLabel }: {
  children: React.ReactNode
  onRemove: () => void
  removeLabel: string
}) {
  return (
    <div className="flex items-center gap-1.5">
      {children}
      <button
        type="button"
        aria-label={removeLabel}
        title={removeLabel}
        onClick={onRemove}
        className="grid size-7 shrink-0 place-items-center rounded-lg transition-colors hover:bg-[var(--surface-hover)]"
        style={{ color: 'var(--tone-danger-fg)' }}
      >
        <IconTrash width={13} height={13} />
      </button>
    </div>
  )
}

function AddButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <Button size="sm" onClick={onClick} icon={<IconPlus width={13} height={13} />}>{label}</Button>
  )
}

/** The resource's identity: name (renameable), display and description. */
function Identity({ resource, update, rename }: Pick<EditorProps, 'resource' | 'update' | 'rename'>) {
  const { t } = useI18n()
  const id = useId()
  return (
    <>
      <div className="grid grid-cols-2 gap-2.5">
        <Field label={t('ed.name')} hint={t('ed.nameHint')}>
          <TextInput mono value={resource.metadata.name} onChange={(v) => rename(v.trim())} />
        </Field>
        <Field label={t('ed.display')}>
          <TextInput
            value={asStr(resource.metadata.display)}
            onChange={(v) => update((r) => withMeta(r, { display: v || null }))}
          />
        </Field>
      </div>
      <Field label={t('ed.description')}>
        <input
          id={id}
          className="ontogeny-input"
          value={asStr(resource.metadata.description)}
          onChange={(e) => update((r) => withMeta(r, { description: e.target.value || null }))}
        />
      </Field>
    </>
  )
}

/* ------------------------------------------------------------- ObjectType */

interface PropRow extends Record<string, unknown> { name: string; type: string; required: boolean; display: string; marking: string; owner: string }

export function ObjectTypeEditor({ resource, update, rename, stores }: EditorProps & {
  stores?: string[]
}) {
  const { t } = useI18n()
  const s = spec(resource)
  const rows = asNamed<PropRow>(s.properties, { type: 'string', required: false, display: '', marking: '', owner: '' })
  const pk = asStrList(s.primaryKey)
  const backing = asObj(s.backing)
  // where materialized data physically lands, for the "say where" hint below
  const storage = useQuery(storageQuery())
  const storageInfo = storage.data?.objects?.[resource.metadata.name]
  const meta = useMeta()?.data
  const graph = storage.data?.graph
  // projection inclusion is a fact of the PACKAGE (from its compiled snapshot),
  // independent of whether the graph layer is wired — the console must show it
  // either way, or "why is my type not in the graph" becomes unanswerable
  const graphNames = Object.entries(meta?.projections ?? {})
    .filter(([, prj]) => (prj.objects?.length ?? 0) === 0 || prj.objects?.includes(resource.metadata.name))
    .map(([name]) => name)
  const graphWired = Boolean(graph?.wired)
  const graphEndpoint = graph?.endpoint ?? (graph?.endpoint_configured ? t('ed.mountEndpointSet') : '')

  const setRows = (next: PropRow[]) => update((r) => withSpec(r, {
    properties: fromNamed(next.map((p) => ({
      name: p.name,
      type: p.type || 'string',
      ...(p.required ? { required: true } : {}),
      ...(p.display ? { display: p.display } : {}),
      ...(p.marking ? { marking: p.marking } : {}),
      ...(p.owner ? { owner: p.owner } : {}),
    }))),
  }))
  const patchRow = (i: number, patch: Partial<PropRow>) =>
    setRows(rows.map((row, j) => (j === i ? { ...row, ...patch } : row)))

  // ---- data mount: source, sync cadence, and where rows land (editors for
  // the backing block; the Materialized checkbox above only flips it on) ----
  // Enabling the mount attaches the FIRST declared store of this package (the
  // old 'scenario-store' placeholder failed BACKING-STORE validation).
  const mounted = Boolean(backing.store)
  const virtual = mounted && asStr(backing.mode) === 'virtual'
  // Mounting is INLINE: the source type + connection live in
  // backing.store_spec and the server materializes the Store sidecar on save.
  // One editing surface, no dialog; every field is explicit.
  const sourceKind = asStr(asObj(backing.store_spec).kind, 'sqlite')
  const sourceConn = asStr(asObj(backing.store_spec).connection)
  const syncCfg = asObj(backing.sync)
  const sourceTable = asObj(backing.source)
  const sourceShown = sourceTable.schema
    ? `${sourceTable.schema}.${sourceTable.table}`
    : asStr(sourceTable.table)
  const setSync = (patch: Record<string, unknown>) =>
    setBacking({ sync: { strategy: 'watermark', ...syncCfg, ...patch } })
  const setMounted = (on: boolean) => {
    if (on) {
      update((r) => withSpec(r, {
        backing: {
          store: `${r.metadata.name}-source`, mode: 'materialized',
          source: { schema: '', table: r.metadata.name.replace(/-/g, '_') },
          mapping: {}, sync: { strategy: 'watermark' },
          store_spec: { kind: 'sqlite', connection: '' },
        },
      }))
    } else {
      update((r) => withSpec(r, { backing: undefined }))
    }
  }
  const setBacking = (patch: Record<string, unknown>) => update((r) => {
    const cur = asObj(asObj(r.spec).backing)
    const next: Record<string, unknown> = {
      store: stores?.[0] ?? 'scenario-store', mode: 'materialized',
      source: { schema: '', table: r.metadata.name.replace(/-/g, '_') },
      mapping: {}, sync: { strategy: 'watermark' },
      ...cur, ...patch,
    }
    return withSpec(r, { backing: next })
  })
  const mount = (
    <Group
      title={t('ed.mount')}
      hint={t('ed.mountHint')}
    >
      {/* ---- 数据从哪里来 ---- */}
      <div className="text-[10.5px] font-bold uppercase tracking-[0.08em] muted">{t('ed.mountFrom')}</div>
      <label className="flex cursor-pointer items-center gap-2 py-1 text-[12.5px]">
        <input
          type="checkbox"
          className="size-3.5"
          data-testid="mount-toggle"
          checked={mounted}
          onChange={(e) => setMounted(e.target.checked)}
        />
        {t('ed.mountExternal')}
      </label>
      {!mounted ? (
        <p className="text-[11.5px] muted">{t('ed.mountModeNoneDesc')}</p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2.5">
            <Field label={t('ed.mountSourceKind')}>
              <Select
                data-testid="mount-source-kind"
                value={sourceKind}
                onChange={(v) => {
                  const connByKind: Record<string, string> = {
                    sqlite: '/absolute/path/to/source.db',
                    postgresql: 'postgresql://user:password@host:5432/dbname',
                    mysql: 'mysql://user:password@host:3306/dbname',
                    csv: '/absolute/path/to/data.csv',
                  }
                  setBacking({ store_spec: { kind: v, connection: connByKind[v] ?? '' } })
                }}
                options={[
                  { value: 'sqlite', label: 'SQLite (database file)' },
                  { value: 'postgres', label: 'PostgreSQL (DSN)' },
                  { value: 'mysql', label: 'MySQL (DSN)' },
                  { value: 'csv', label: 'CSV (file path)' },
                ]}
              />
            </Field>
            <Field label={t('ed.mountStore')} hint={t('ed.mountStoreHint')}>
              <TextInput
                mono
                data-testid="mount-store-name"
                value={asStr(backing.store)}
                onChange={(v) => setBacking({ store: v.trim() })}
              />
            </Field>
            <Field
              label={t('ed.mountConn')}
              hint={sourceKind === 'csv'
                ? t('ed.mountConnPhCsv')
                : sourceKind === 'sqlite'
                  ? t('ed.mountConnPhDb')
                  : 'postgresql://user:password@host:5432/dbname'}
            >
              <TextInput
                mono
                data-testid="mount-conn"
                value={sourceConn}
                placeholder={sourceKind === 'csv' ? '/data/parts.csv' : sourceKind === 'sqlite' ? '/data/erp.db' : 'postgresql://…'}
                onChange={(v) => setBacking({ store_spec: { kind: sourceKind, connection: v } })}
              />
            </Field>
            <Field label={t('ed.mountSource')} hint={t('ed.mountSourcePh')}>
              <TextInput
                mono
                data-testid="mount-source"
                value={sourceShown}
                placeholder="schema.table"
                onChange={(v) => {
                  const [schema, table = ''] = v.split(/\.(?=[^.]*$)/)
                  setBacking({ source: { schema: schema ?? '', table } })
                }}
              />
            </Field>
          </div>

          {virtual ? (
            <p className="text-[11.5px] muted">{t('ed.mountVirtualNote')}</p>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-2.5">
                <Field label={t('ed.mountStrategy')}>
                  <Select
                    data-testid="mount-strategy"
                    value={asStr(syncCfg.strategy, 'snapshot')}
                    onChange={(v) => setSync({ strategy: v })}
                    options={[
                      { value: 'watermark', label: 'watermark' },
                      { value: 'snapshot', label: 'snapshot' },
                      { value: 'changelog', label: 'changelog' },
                    ]}
                  />
                </Field>
                <Field label={t('ed.mountSchedule')} hint={t('ed.mountSchedulePh')}>
                  <TextInput
                    mono
                    data-testid="mount-schedule"
                    value={asStr(syncCfg.schedule)}
                    placeholder="*/5 * * * *"
                    onChange={(v) => setSync({ schedule: v || undefined })}
                  />
                </Field>
              </div>
              {asStr(syncCfg.strategy, 'watermark') === 'watermark' ? (
                <Field label={t('ed.mountWatermark')} hint={t('ed.mountWatermarkPh')}>
                  <TextInput
                    mono
                    data-testid="mount-watermark"
                    value={asStr(asObj(syncCfg.watermark).column)}
                    onChange={(v) => setSync({ watermark: v ? { column: v } : undefined })}
                  />
                </Field>
              ) : null}
            </>
          )}
        </>
      )}

      {/* ---- 落到哪里（当前存储——由部署的 storage provider 决定，只读展示） ---- */}
      <div className="mt-1 text-[10.5px] font-bold uppercase tracking-[0.08em] muted">{t('ed.mountTo')}</div>
      <div className="rounded-lg px-3 py-2.5 text-[11.5px] leading-relaxed" style={{ background: 'var(--surface-sunken)' }} data-testid="mount-persist">
        {graphWired ? (
          <>
            <div className="flex items-center gap-2">
              <span className="font-bold">{t('ed.mountCurrentGraph')}</span>
            </div>
            <div className="mt-0.5 font-mono">
              hugegraph · {graphEndpoint} · {t('ed.mountGraph')} {graphNames.join(', ')}
            </div>
            <div className="mt-0.5 muted">{t('ed.mountGraphActiveNote')}</div>
            <div className="mt-1 text-[11px] muted">{t('ed.mountGraphSyncNote')}</div>
          </>
        ) : (
          <>
            <div className="font-bold">{t('ed.mountRel')}</div>
            <div className="mt-0.5">
              <span className="muted">{t('ed.mountPersist')}</span>{' '}
              <span className="font-mono">
                {storage.data?.target.kind} · {storage.data?.target.target}
                {mounted ? <> · {storageInfo?.table ?? '…'}</> : null}
              </span>
              {storageInfo?.rows != null ? (
                <span className="muted">  ·  {t('storage.rows', { rows: storageInfo.rows })}</span>
              ) : null}
            </div>
            <div className="mt-0.5 muted">{t('ed.mountRelNote')}</div>
            {graphNames.length ? (
              <div className="mt-0.5">
                <span className="muted">{t('ed.mountGraph')}</span>{' '}
                <span className="font-mono">{graphNames.join(', ')}</span>
              </div>
            ) : null}
            {!graph?.declared ? (
              <div className="mt-0.5 muted">{t('ed.mountGraphDisabled')}</div>
            ) : (
              <div className="mt-0.5" style={{ color: 'var(--tone-warning-fg)' }}>
                {graph?.blocked_by === 'provider-sqlite'
                  ? t('ed.mountGraphBlockedProvider')
                  : graph?.blocked_by === 'endpoint-unresolved'
                    ? t('ed.mountGraphBlockedEndpoint')
                    : t('ed.mountGraphBlockedExtension')}
              </div>
            )}
          </>
        )}
      </div>
    </Group>
  )

  return (
    <div className="flex flex-col gap-3" data-testid="object-type-editor">
      <Identity resource={resource} update={update} rename={rename} />

      <div className="grid grid-cols-2 gap-2.5">
        <Field label={t('ed.primaryKey')} hint={t('ed.primaryKeyHint')}>
          <Select
            value={pk[0] ?? ''}
            onChange={(v) => update((r) => withSpec(r, { primaryKey: v ? [v] : [] }))}
            options={rows.filter((p) => p.name).map((p) => ({ value: p.name, label: p.name }))}
            allowEmpty={t('ed.primaryKeyEmpty')}
          />
        </Field>
      </div>

      {mount}

      <Group
        title={t('ed.properties')}
        count={rows.length}
        action={<AddButton label={t('ed.addProperty')} onClick={() => setRows([
          ...rows,
          {
            name: uniqueName('prop', rows.map((p) => p.name)),
            type: 'string', required: false, display: '', marking: '', owner: '',
          },
        ])} />}
      >
        {rows.length === 0 ? <p className="text-[12px] muted">{t('ed.emptyList')}</p> : (
          <div className="flex flex-col gap-1.5">
            {rows.map((row, i) => (
              <div key={i} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto] items-center gap-1.5">
                <TextInput mono value={row.name} onChange={(v) => patchRow(i, { name: v })} />
                <input
                  className="ontogeny-input font-mono text-[12px]"
                  list="ontogeny-ed-property-types"
                  value={row.type}
                  onChange={(e) => patchRow(i, { type: e.target.value })}
                />
                <Check label={t('ed.required')} checked={Boolean(row.required)} onChange={(v) => patchRow(i, { required: v })} />
                <button
                  type="button"
                  aria-label={t('ed.removeProperty')}
                  onClick={() => setRows(rows.filter((_, j) => j !== i))}
                  className="grid size-7 place-items-center rounded-lg transition-colors hover:bg-[var(--surface-hover)]"
                  style={{ color: 'var(--tone-danger-fg)' }}
                >
                  <IconTrash width={13} height={13} />
                </button>
              </div>
            ))}
          </div>
        )}
        <datalist id="ontogeny-ed-property-types">
          {PROPERTY_TYPES.map((p) => <option key={p} value={p} />)}
        </datalist>
      </Group>
    </div>
  )
}

/* --------------------------------------------------------------- LinkType */

export function LinkTypeEditor({ resource, update, rename, objectNames }: EditorProps) {
  const { t } = useI18n()
  const s = spec(resource)
  const opts = objectNames.map((n) => ({ value: n, label: n }))
  return (
    <div className="flex flex-col gap-3" data-testid="link-type-editor">
      <Identity resource={resource} update={update} rename={rename} />
      <div className="grid grid-cols-2 gap-2.5">
        <Field label={t('ed.source')}>
          <Select value={asStr(s.source)} onChange={(v) => update((r) => withSpec(r, { source: v }))} options={opts} />
        </Field>
        <Field label={t('ed.target')}>
          <Select value={asStr(s.target)} onChange={(v) => update((r) => withSpec(r, { target: v }))} options={opts} />
        </Field>
      </div>
      <Field label={t('ed.cardinality')}>
        <Select
          value={asStr(s.cardinality, 'ONE_TO_MANY')}
          onChange={(v) => update((r) => withSpec(r, { cardinality: v }))}
          options={CARDINALITIES.map((c) => ({ value: c, label: t(`data.card.${c}`) }))}
        />
      </Field>
      <p className="text-[11.5px] muted">{t('ed.linkJoinHint')}</p>
    </div>
  )
}

/* ------------------------------------------------------------- Projection */

export function ProjectionEditor({ resource, update, rename, objectNames }: EditorProps) {
  const { t } = useI18n()
  const s = spec(resource)
  const include = asObj(s.include)
  const objects = asNamed<{ name: string; properties: string[] }>(include.objects, { properties: [] })
  const links = asStrList(include.links)
  const indexes = (Array.isArray(s.indexes) ? s.indexes : []).map((ix) => {
    const o = asObj(ix)
    return { object: asStr(o.object), property: asStr(o.property) }
  })

  const setInclude = (patch: { objects?: Record<string, unknown>; links?: string[] }) =>
    update((r) => withSpec(r, { include: { ...asObj(asObj(r.spec).include), ...patch } }))
  const setIndexes = (next: Array<{ object: string; property: string }>) =>
    update((r) => withSpec(r, {
      indexes: next.filter((ix) => ix.object && ix.property).map((ix) => ({ object: ix.object, property: ix.property })),
    }))

  const objOpts = objectNames.map((n) => ({ value: n, label: n }))

  return (
    <div className="flex flex-col gap-3" data-testid="projection-editor">
      <Identity resource={resource} update={update} rename={rename} />
      <div className="grid grid-cols-2 gap-2.5">
        <Field label={t('ed.endpoint')} hint={t('ed.endpointHint')}>
          <TextInput mono value={asStr(s.endpoint)} onChange={(v) => update((r) => withSpec(r, { endpoint: v }))} placeholder="${HUGEGRAPH_URL}" />
        </Field>
        <Field label={t('ed.graph')}>
          <TextInput mono value={asStr(s.graph)} onChange={(v) => update((r) => withSpec(r, { graph: v }))} />
        </Field>
        <Field label={t('ed.graphspace')}>
          <TextInput mono value={asStr(s.graphspace, 'DEFAULT')} onChange={(v) => update((r) => withSpec(r, { graphspace: v }))} />
        </Field>
        <Field label={t('ed.deletion')}>
          <Select
            value={asStr(s.deletion, 'remove')}
            onChange={(v) => update((r) => withSpec(r, { deletion: v }))}
            options={[
              { value: 'remove', label: t('ed.deletion.remove') },
              { value: 'keep-flagged', label: t('ed.deletion.keep') },
            ]}
          />
        </Field>
      </div>

      <Group
        title={t('ed.includeObjects')}
        count={objects.length}
        hint={t('ed.includeObjectsHint')}
        action={<AddButton label={t('ed.addObject')} onClick={() => setInclude({
          objects: { ...fromNamed(objects), [uniqueName('object', objects.map((o) => o.name))]: { properties: [] } },
        })} />}
      >
        {objects.length === 0 ? <p className="text-[12px] muted">{t('ed.emptyList')}</p> : (
          <div className="flex flex-col gap-1.5">
            {objects.map((o) => (
              <Row
                key={o.name}
                removeLabel={t('ed.removeObject')}
                onRemove={() => {
                  const next = { ...fromNamed(objects) }
                  delete next[o.name]
                  setInclude({ objects: next })
                }}
              >
                <select
                  className="ontogeny-input w-44 shrink-0 font-mono text-[12px]"
                  value={o.name}
                  onChange={(e) => {
                    const next = { ...fromNamed(objects) }
                    next[e.target.value] = { properties: o.properties }
                    delete next[o.name]
                    setInclude({ objects: next })
                  }}
                >
                  {objOpts.map((opt) => <option key={opt.value} value={opt.value}>{opt.label}</option>)}
                </select>
                <input
                  className="ontogeny-input font-mono text-[12px]"
                  value={o.properties.join(', ')}
                  placeholder={t('ed.propertiesPlaceholder')}
                  onChange={(e) => setInclude({
                    objects: {
                      ...fromNamed(objects),
                      [o.name]: { properties: e.target.value.split(',').map((x) => x.trim()).filter(Boolean) },
                    },
                  })}
                />
              </Row>
            ))}
          </div>
        )}
      </Group>

      <Group
        title={t('ed.includeLinks')}
        count={links.length}
        action={<AddButton label={t('ed.addLink')} onClick={() => setInclude({ links: [...links, ''] })} />}
      >
        {links.length === 0 ? <p className="text-[12px] muted">{t('ed.emptyList')}</p> : (
          <div className="flex flex-col gap-1.5">
            {links.map((link, i) => (
              <Row key={i} removeLabel={t('ed.removeLink')} onRemove={() => setInclude({ links: links.filter((_, j) => j !== i) })}>
                <TextInput mono value={link} onChange={(v) => setInclude({ links: links.map((l, j) => (j === i ? v : l)) })} />
              </Row>
            ))}
          </div>
        )}
      </Group>

      <Group
        title={t('ed.indexes')}
        count={indexes.length}
        hint={t('ed.indexesHint')}
        action={<AddButton label={t('ed.addIndex')} onClick={() => setIndexes([...indexes, { object: objectNames[0] ?? '', property: '' }])} />}
      >
        {indexes.length === 0 ? <p className="text-[12px] muted">{t('ed.emptyList')}</p> : (
          <div className="flex flex-col gap-1.5">
            {indexes.map((ix, i) => (
              <Row key={i} removeLabel={t('ed.removeIndex')} onRemove={() => setIndexes(indexes.filter((_, j) => j !== i))}>
                <select
                  className="ontogeny-input w-44 shrink-0 font-mono text-[12px]"
                  value={ix.object}
                  onChange={(e) => setIndexes(indexes.map((x, j) => (j === i ? { ...x, object: e.target.value } : x)))}
                >
                  {objOpts.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
                <TextInput mono value={ix.property} onChange={(v) => setIndexes(indexes.map((x, j) => (j === i ? { ...x, property: v } : x)))} />
              </Row>
            ))}
          </div>
        )}
      </Group>
    </div>
  )
}

/* ----------------------------------------------------------------- Action */

interface ParamRow extends Record<string, unknown> { name: string; type: string; required: boolean }

/* --------------------------------------------------------------- Action */

/** All seven effect kinds the engine executes, in authoring order:
 *  transactional row effects first, outbox-delivered (webhook / event) last. */
const EFFECT_KINDS = [
  'modify-target', 'modify-linked', 'create-object', 'archive-object',
  'set-link', 'webhook', 'emit-event',
] as const

/** One editable key→value dict (a `set` map, a `payload`, …). */
function DictRowsEditor({ rows, rowsLabel, addLabel, onChange }: {
  rows: Array<{ k: string; v: string }>
  rowsLabel: string
  addLabel: string
  onChange: (rows: Array<{ k: string; v: string }>) => void
}) {
  const { t } = useI18n()
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] font-semibold uppercase tracking-[0.06em] muted">{rowsLabel}</span>
      {rows.map((row, i) => (
        <div key={i} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_auto] items-center gap-1.5">
          <TextInput mono value={row.k} onChange={(v) => onChange(rows.map((x, j) => (j === i ? { ...x, k: v } : x)))} />
          <TextInput mono value={row.v} onChange={(v) => onChange(rows.map((x, j) => (j === i ? { ...x, v } : x)))} />
          <button
            type="button"
            aria-label={t('ed.removeSet')}
            onClick={() => onChange(rows.filter((_, j) => j !== i))}
            className="grid size-7 place-items-center rounded-lg transition-colors hover:bg-[var(--surface-hover)]"
            style={{ color: 'var(--tone-danger-fg)' }}
          >
            <IconTrash width={13} height={13} />
          </button>
        </div>
      ))}
      <div>
        <AddButton label={addLabel} onClick={() => onChange([...rows, { k: '', v: '' }])} />
      </div>
    </div>
  )
}

export function ActionEditor({ resource, update, rename, objectNames, policyNames, linkNames = [] }: EditorProps) {
  const { t } = useI18n()
  const s = spec(resource)
  const target = asStr(s.target)
  const params = asNamed<ParamRow>(s.parameters, { type: 'string', required: false })
  const rules = (Array.isArray(s.rules) ? s.rules : []).map((r) => {
    const o = asObj(r)
    return { expr: asStr(o.expr), message: asStr(o.message) }
  })
  const effects = Array.isArray(s.effects) ? s.effects.map(asObj) : []

  const updateEffects = (next: Array<Record<string, unknown>>) => update((r) => withSpec(r, { effects: next }))

  /** Switch one effect's kind, carrying the guard and whatever fields map. */
  const changeKind = (i: number, kind: string) => updateEffects(effects.map((e, j) => {
    if (j !== i) return e
    const when = e.when
    if (kind === 'modify-target') return { kind, when, set: asObj(e.set ?? e.properties) }
    if (kind === 'create-object') return { kind, when, properties: asObj(e.properties ?? e.set) }
    if (kind === 'modify-linked') return { kind, when, link: asStr(e.link), set: asObj(e.set ?? e.properties) }
    if (kind === 'set-link') return { kind, when, link: asStr(e.link), add: Array.isArray(e.add) ? e.add : [], remove: Array.isArray(e.remove) ? e.remove : [] }
    if (kind === 'webhook') return { kind, when, url: asStr(e.url) }
    if (kind === 'emit-event') return { kind, when, payload: asObj(e.payload) }
    return { kind, when } // archive-object: no fields
  }))

  /** key→value rows of a dict-valued effect field (set / properties / payload). */
  const dictRows = (e: Record<string, unknown>, field: string): Array<{ k: string; v: string }> =>
    Object.entries(asObj(e[field])).map(([k, v]) => ({ k, v: asStr(v) }))
  const writeDict = (i: number, field: string, rows: Array<{ k: string; v: string }>) =>
    updateEffects(effects.map((e, j) => (j === i
      ? { ...e, [field]: Object.fromEntries(rows.filter((x) => x.k).map((x) => [x.k, x.v])) }
      : e)))

  /** single-key entries of a set-link add/remove list */
  const entryRows = (e: Record<string, unknown>, field: 'add' | 'remove'): Array<{ k: string; v: string }> =>
    (Array.isArray(e[field]) ? e[field] : []).map((raw) => {
      const o = asObj(raw)
      const k = Object.keys(o)[0] ?? ''
      return { k, v: asStr(o[k]) }
    })
  const writeEntries = (i: number, field: 'add' | 'remove', rows: Array<{ k: string; v: string }>) =>
    updateEffects(effects.map((e, j) => (j === i
      ? { ...e, [field]: rows.filter((x) => x.k).map((x) => ({ [x.k]: x.v })) }
      : e)))

  const effectBody = (e: Record<string, unknown>, i: number) => {
    const kind = asStr(e.kind)
    if (kind === 'archive-object') {
      return <p className="text-[11px] leading-relaxed muted">{t('ed.archiveHint')}</p>
    }
    if (kind === 'webhook') {
      return (
        <div className="flex flex-col gap-1">
          <TextInput
            mono value={asStr(e.url)} placeholder={t('ed.webhookUrlPh')}
            onChange={(v) => updateEffects(effects.map((x, j) => (j === i ? { ...x, url: v || undefined } : x)))}
          />
          <p className="text-[11px] leading-relaxed muted">{t('ed.webhookAllowlist')}</p>
        </div>
      )
    }
    if (kind === 'modify-linked' || kind === 'set-link') {
      return (
        <div className="flex flex-col gap-1.5">
          <Select
            value={asStr(e.link)}
            onChange={(v) => updateEffects(effects.map((x, j) => (j === i ? { ...x, link: v } : x)))}
            options={linkNames.map((n) => ({ value: n, label: n }))}
            allowEmpty={t('ed.pickLink')}
          />
          {kind === 'modify-linked' ? (
            <DictRowsEditor rows={dictRows(e, 'set')} rowsLabel={t('ed.setFields')}
              onChange={(rows) => writeDict(i, 'set', rows)} addLabel={t('ed.addField')} />
          ) : (
            <>
              <DictRowsEditor rows={entryRows(e, 'add')} rowsLabel={t('ed.addMembers')}
                onChange={(rows) => writeEntries(i, 'add', rows)} addLabel={t('ed.addMember')} />
              <DictRowsEditor rows={entryRows(e, 'remove')} rowsLabel={t('ed.removeMembers')}
                onChange={(rows) => writeEntries(i, 'remove', rows)} addLabel={t('ed.addRemove')} />
            </>
          )}
        </div>
      )
    }
    if (kind === 'emit-event') {
      return (
        <div className="flex flex-col gap-1">
          <DictRowsEditor rows={dictRows(e, 'payload')} rowsLabel={t('ed.payload')}
            onChange={(rows) => writeDict(i, 'payload', rows)} addLabel={t('ed.addField')} />
          <p className="text-[11px] leading-relaxed muted">{t('ed.emitHint')}</p>
        </div>
      )
    }
    // modify-target / create-object: the dict of column writes
    const field = kind === 'create-object' ? 'properties' : 'set'
    return (
      <DictRowsEditor rows={dictRows(e, field)} rowsLabel={t('ed.setFields')}
        onChange={(rows) => writeDict(i, field, rows)} addLabel={t('ed.addField')} />
    )
  }

  return (
    <div className="flex flex-col gap-3" data-testid="action-editor">
      <Identity resource={resource} update={update} rename={rename} />
      <div className="grid grid-cols-2 gap-2.5">
        <Field label={t('ed.target')}>
          <Select value={target} onChange={(v) => update((r) => withSpec(r, { target: v }))} options={objectNames.map((n) => ({ value: n, label: n }))} />
        </Field>
        <Field label={t('ed.policy')}>
          <Select
            value={asStr(s.policy)}
            onChange={(v) => update((r) => withSpec(r, { policy: v || undefined }))}
            options={policyNames.map((n) => ({ value: n, label: n }))}
            allowEmpty={t('ed.defaultPolicy')}
          />
        </Field>
      </div>

      <Group
        title={t('ed.parameters')}
        count={params.length}
        action={<AddButton label={t('ed.addParameter')} onClick={() => update((r) => withSpec(r, {
          parameters: {
            ...fromNamed(params),
            [uniqueName('param', params.map((p) => p.name))]: { type: 'string', required: true },
          },
        }))} />}
      >
        {params.length === 0 ? <p className="text-[12px] muted">{t('ed.emptyList')}</p> : (
          <div className="flex flex-col gap-1.5">
            {params.map((p, i) => (
              <div key={i} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto] items-center gap-1.5">
                <TextInput
                  mono value={p.name}
                  onChange={(v) => update((r) => withSpec(r, {
                    parameters: fromNamed(params.map((x, j) => (j === i ? { ...x, name: v } : x))),
                  }))}
                />
                <input
                  className="ontogeny-input font-mono text-[12px]"
                  list="ontogeny-ed-property-types"
                  value={p.type}
                  onChange={(e) => update((r) => withSpec(r, {
                    parameters: fromNamed(params.map((x, j) => (j === i ? { ...x, type: e.target.value } : x))),
                  }))}
                />
                <Check
                  label={t('ed.required')}
                  checked={Boolean(p.required)}
                  onChange={(v) => update((r) => withSpec(r, {
                    parameters: fromNamed(params.map((x, j) => (j === i ? { ...x, required: v } : x))),
                  }))}
                />
                <button
                  type="button"
                  aria-label={t('ed.removeParameter')}
                  onClick={() => update((r) => {
                    const next = { ...fromNamed(params) }
                    delete next[p.name]
                    return withSpec(r, { parameters: next })
                  })}
                  className="grid size-7 place-items-center rounded-lg transition-colors hover:bg-[var(--surface-hover)]"
                  style={{ color: 'var(--tone-danger-fg)' }}
                >
                  <IconTrash width={13} height={13} />
                </button>
              </div>
            ))}
          </div>
        )}
      </Group>

      <Group
        title={t('ed.rules')}
        count={rules.length}
        hint={t('ed.rulesHint')}
        action={<AddButton label={t('ed.addRule')} onClick={() => update((r) => withSpec(r, { rules: [...rules, { expr: '', message: '' }] }))} />}
      >
        {rules.length === 0 ? <p className="text-[12px] muted">{t('ed.emptyList')}</p> : (
          <div className="flex flex-col gap-1.5">
            {rules.map((rule, i) => (
              <Row key={i} removeLabel={t('ed.removeRule')} onRemove={() => update((r) => withSpec(r, { rules: rules.filter((_, j) => j !== i) }))}>
                <TextInput
                  mono value={rule.expr} placeholder="target.qty > 0"
                  onChange={(v) => update((r) => withSpec(r, { rules: rules.map((x, j) => (j === i ? { ...x, expr: v } : x)) }))}
                />
                <TextInput
                  value={rule.message} placeholder={t('ed.ruleMessage')}
                  onChange={(v) => update((r) => withSpec(r, { rules: rules.map((x, j) => (j === i ? { ...x, message: v } : x)) }))}
                />
              </Row>
            ))}
          </div>
        )}
      </Group>

      <Group title={t('ed.effects')} count={effects.length} hint={t('ed.effectsHint')}
        action={<AddButton label={t('ed.addEffect')} onClick={() => updateEffects([...effects, { kind: 'modify-target', set: {} }])} />}>
        {effects.length === 0 ? <p className="text-[12px] muted">{t('ed.effectsEmpty')}</p> : (
          <div className="flex flex-col gap-2.5">
            {effects.map((e, i) => {
              const kind = asStr(e.kind)
              return (
                <div key={i} className="rounded-xl p-2.5 flex flex-col gap-1.5" style={{ background: 'var(--surface-sunken)' }} data-testid={`effect-${i}`}>
                  <div className="grid grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_auto] items-center gap-1.5">
                    <select
                      className="ontogeny-input font-mono text-[12px]"
                      value={kind}
                      data-testid={`effect-kind-${i}`}
                      onChange={(ev) => changeKind(i, ev.target.value)}
                    >
                      {EFFECT_KINDS.map((k) => <option key={k} value={k}>{t(`ed.kind.${k}`)}</option>)}
                    </select>
                    <TextInput
                      mono value={asStr(e.when)} placeholder={t('ed.whenPh')}
                      onChange={(v) => updateEffects(effects.map((x, j) => (j === i ? { ...x, when: v || undefined } : x)))}
                    />
                    <button
                      type="button"
                      aria-label={t('ed.removeEffect')}
                      onClick={() => updateEffects(effects.filter((_, j) => j !== i))}
                      className="grid size-7 place-items-center rounded-lg transition-colors hover:bg-[var(--surface-hover)]"
                      style={{ color: 'var(--tone-danger-fg)' }}
                    >
                      <IconTrash width={13} height={13} />
                    </button>
                  </div>
                  {effectBody(e, i)}
                </div>
              )
            })}
          </div>
        )}
      </Group>
    </div>
  )
}

/* --------------------------------------------------------------- Function */

/** The Apache license header every function file carries on disk.
 *
 * It is legal text, not logic: the editor strips it from the displayed buffer
 * (see splitLicenseHeader) and re-attaches the exact same lines on save, so
 * the file keeps its compliance header while the author sees only code. */
const LICENSE_FIRST = '# Copyright'
const LICENSE_LAST = '# limitations under the License.'

export function splitLicenseHeader(src: string): { header: string | null; body: string } {
  const lines = src.split('\n')
  if (!lines[0]?.startsWith(LICENSE_FIRST)) return { header: null, body: src }
  const end = lines.findIndex((l) => l.startsWith(LICENSE_LAST))
  // the block must be contiguous comments from the first line to the last
  if (end < 1 || !lines.slice(0, end + 1).every((l) => l === '' || l.startsWith('#'))) {
    return { header: null, body: src }
  }
  return { header: lines.slice(0, end + 1).join('\n'), body: lines.slice(end + 1).join('\n') }
}

/** A starting point for a function whose file nobody has written yet.
 *
 * Shaped exactly like the declaration beside it — the entry's function name,
 * the declared parameters as keyword arguments — and commented in the interface
 * language, so the box never opens empty: what the file is, what `ontogeny` can do,
 * what Test run does versus Save. Keeping it runnable (a real object type when
 * one is declared) means the first Test run teaches something instead of
 * merely failing. */
function pythonSkeleton(
  resource: OntologyResource,
  t: (k: string, p?: Record<string, string | number>) => string,
): string {
  const s = spec(resource)
  const entry = asStr(s.entry)
  const fn = (entry.includes(':') ? entry.split(':')[1] : resource.metadata.name)
    .trim().replace(/-/g, '_') || 'run'
  const params = asNamed<{ name: string; type: string; required: boolean }>(
    s.parameters, { type: 'string', required: false })
  const pyType = (ty: string): string => {
    const base = ty.replace(/\(.*\)/, '')
    if (base === 'string' || base === 'date' || base === 'timestamp' || base.startsWith('enum[')) return 'str'
    if (base === 'integer') return 'int'
    if (base === 'decimal') return 'float'
    if (base === 'boolean') return 'bool'
    return base // a type we cannot map: keep it, the author knows their DSL
  }
  const sig = params
    .filter((p) => p.name)
    .map((p) => {
      const ty = pyType(p.type)
      const annotated = ty ? `${p.name}: ${ty}` : p.name
      return p.required ? annotated : `${annotated} = None`
    })
    .join(', ')
  const caps = (Array.isArray(s.capabilities) ? s.capabilities : []).map(asObj)
  const objType = caps.flatMap((c) => (Array.isArray(c['read-objects']) ? (c['read-objects'] as string[]) : []))[0]
    ?? '<readable-object-type>'

  return [
    '# Copyright 2026 Apache HugeGraph Authors',
    '#',
    '# Licensed under the Apache License, Version 2.0 (the "License");',
    '# you may not use this file except in compliance with the License.',
    '# You may obtain a copy of the License at',
    '#',
    '#     http://www.apache.org/licenses/LICENSE-2.0',
    '#',
    '# Unless required by applicable law or agreed to in writing, software',
    '# distributed under the License is distributed on an "AS IS" BASIS,',
    '# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.',
    '# See the License for the specific language governing permissions and',
    '# limitations under the License.',
    '',
    '# ' + '─'.repeat(64),
    `# ${t('ed.tplTitle', { name: fn })}`,
    `# ${t('ed.tplTest')}`,
    `# ${t('ed.tplSave')}`,
    '# ' + '─'.repeat(64),
    '',
    `def ${fn}(${sig}):`,
    `    """${t('ed.tplDoc')}"""`,
    `    # ${t('ed.tplQuery')}`,
    `    rows = ontogeny.query("${objType}", limit=100)`,
    '',
    `    # ${t('ed.tplLlm')}`,
    `    # answer = ontogeny.llm("...")["content"]`,
    '',
    `    # ${t('ed.tplReturn')}`,
    `    return {"count": len(rows)}`,
    '',
  ].join('\n')
}

export function FunctionEditor({ resource, update, rename }: EditorProps) {
  const { t } = useI18n()
  const s = spec(resource)
  const params = asNamed<ParamRow>(s.parameters, { type: 'string', required: false })
  const returns = asObj(s.returns)
  const caps = (Array.isArray(s.capabilities) ? s.capabilities : []).map(asObj)
  const runtime = asStr(s.runtime, 'python')
  const fnName = resource.metadata.name
  // The DSL only *names* the code; the code is a file in the package. A
  // declarative body IS the spec — no file, nothing to show — so this whole
  // section (and the query feeding it) exists only for the python runtime.
  const source = useQuery({
    queryKey: keys.functionSource(fnName),
    queryFn: () => apiClient.functionSource(fnName),
    retry: false,
    enabled: runtime === 'python',
  })
  const qc = useQueryClient()
  // the buffer holds the text being edited; it is seeded from the file — or,
  // when that file does not exist yet, from a commented skeleton — and
  // re-seeded whenever a save (or an external change) changes what is on disk.
  // The skeleton key is `exists === false`, NOT an empty string: a file that
  // exists and is empty is real (someone touched a placeholder) and must show
  // as empty, not be silently swapped for generated code the moment Save is
  // within reach.
  const disk = source.data?.source ?? ''
  const fileMissing = source.data?.exists === false
  const [code, setCode] = useState<string | null>(null)
  useEffect(() => { setCode(null) }, [fnName, disk])
  // the buffer edits the file MINUS its license header: the header is legal
  // text, not logic, so it is hidden here and stitched back on save/test —
  // the file on disk always keeps it. The header survives verbatim (never
  // re-flowed), which is what keeps round-trips byte-stable for unchanged
  // bodies.
  const diskParts = splitLicenseHeader(disk)
  const skeleton = fileMissing ? pythonSkeleton(resource, t) : ''
  const skeletonParts = splitLicenseHeader(skeleton)
  const header = diskParts.header ?? (fileMissing ? skeletonParts.header : null)
  const diskBody = diskParts.body || (fileMissing ? skeletonParts.body : '')
  const buffer = code ?? diskBody
  const restored = header ? `${header}\n${buffer}` : buffer
  const save = useMutation({
    mutationFn: () => apiClient.saveFunctionSource(fnName, restored),
    onSuccess: () => {
      setCode(null)
      qc.invalidateQueries({ queryKey: keys.functionSource(fnName) })
      qc.invalidateQueries({ queryKey: keys.meta })
    },
  })
  // Test is save's mirror: one throwaway run of the buffer — the platform
  // invents inputs (each labelled with where it came from) and reports the
  // value or the failure, but writes nothing. A save is what leaves a record.
  const test = useMutation({
    mutationFn: () => apiClient.testFunctionSource(fnName, restored),
  })
  const saving = save.isPending
  const testing = test.isPending

  const setParams = (rows: ParamRow[]) => update((r) => withSpec(r, {
    parameters: fromNamed(rows.map((p) => ({
      name: p.name, type: p.type || 'string', ...(p.required ? { required: true } : {}),
    }))),
  }))

  const setCaps = (next: Array<Record<string, unknown>>) => update((r) => withSpec(r, { capabilities: next }))
  const capKind = (c: Record<string, unknown>) => asStr(Object.keys(c)[0])

  const steps = (Array.isArray(s.steps) ? s.steps : []).map(asObj)
  // raw text for each read step's filter while it is being typed
  const [filterText, setFilterText] = useState<Record<number, string>>({})
  const setSteps = (next: Array<Record<string, unknown>>) => update((r) => withSpec(r, { steps: next }))
  const patchStep = (i: number, patch: Record<string, unknown>) =>
    setSteps(steps.map((x, j) => (j === i ? { ...x, ...patch } : x)))

  return (
    <div className="flex flex-col gap-3" data-testid="function-editor">
      <Identity resource={resource} update={update} rename={rename} />
      <div className="grid grid-cols-2 gap-2.5">
        <Field label={t('ed.runtime')} hint={t('ed.runtimeHint')}>
          <Select
            value={runtime}
            onChange={(v) => update((r) => withSpec(r, v === 'declarative'
              // switching to a declared body drops the file reference: a
              // declarative function has no file, and the validator refuses one
              ? { runtime: v, entry: undefined, steps: steps.length ? steps : [{ id: 'step1', kind: 'llm', prompt: '' }] }
              : { runtime: v, steps: [] }))}
            options={FUNCTION_RUNTIMES.map((k) => ({ value: k, label: k }))}
          />
        </Field>
        {runtime === 'python' ? (
          <Field label={t('ed.entry')} hint={t('ed.entryHint')}>
            <TextInput mono value={asStr(s.entry)} onChange={(v) => update((r) => withSpec(r, { entry: v }))} placeholder="file.py:function_name" />
          </Field>
        ) : (
          <Field label={t('ed.returnsStep')} hint={t('ed.returnsStepHint')}>
            <Select
              value={asStr(s.returns_step)}
              onChange={(v) => update((r) => withSpec(r, { returns_step: v || undefined }))}
              options={[{ value: '', label: t('ed.returnsStepAll') },
                        ...steps.map((x) => ({ value: asStr(x.id), label: asStr(x.id) }))]}
            />
          </Field>
        )}
      </div>

      <Group
        title={t('ed.parameters')}
        count={params.length}
        action={<AddButton label={t('ed.addParameter')} onClick={() => setParams([
          ...params,
          { name: uniqueName('param', params.map((p) => p.name)), type: 'string', required: true },
        ])} />}
      >
        {params.length === 0 ? <p className="text-[12px] muted">{t('ed.emptyList')}</p> : (
          <div className="flex flex-col gap-1.5">
            {params.map((p, i) => (
              <div key={i} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto] items-center gap-1.5">
                <TextInput mono value={p.name} onChange={(v) => setParams(params.map((x, j) => (j === i ? { ...x, name: v } : x)))} />
                <input
                  className="ontogeny-input font-mono text-[12px]"
                  list="ontogeny-ed-property-types"
                  value={p.type}
                  onChange={(e) => setParams(params.map((x, j) => (j === i ? { ...x, type: e.target.value } : x)))}
                />
                <Check label={t('ed.required')} checked={Boolean(p.required)} onChange={(v) => setParams(params.map((x, j) => (j === i ? { ...x, required: v } : x)))} />
                <button
                  type="button"
                  aria-label={t('ed.removeParameter')}
                  onClick={() => setParams(params.filter((_, j) => j !== i))}
                  className="grid size-7 place-items-center rounded-lg transition-colors hover:bg-[var(--surface-hover)]"
                  style={{ color: 'var(--tone-danger-fg)' }}
                >
                  <IconTrash width={13} height={13} />
                </button>
              </div>
            ))}
          </div>
        )}
      </Group>

      {/* A declarative body IS the logic: a short pipeline, editable here. The
          order is the execution order, and `${...}` refers to a parameter or to
          a step defined ABOVE the one using it (the validator enforces that, so
          a typo fails at save rather than at invoke). */}
      {runtime === 'declarative' ? (
        <Group
          title={t('ed.steps')}
          count={steps.length}
          hint={t('ed.stepsHint')}
          action={<AddButton label={t('ed.addStep')} onClick={() => setSteps([
            ...steps,
            { id: uniqueName('step', steps.map((x) => asStr(x.id))), kind: 'llm', prompt: '' },
          ])} />}
        >
          {steps.length === 0 ? <p className="text-[12px] muted">{t('ed.emptyList')}</p> : (
            <div className="flex flex-col gap-2" data-testid="function-steps">
              {steps.map((step, i) => {
                const kind = asStr(step.kind, 'llm')
                return (
                  <div key={i} className="rounded-lg p-2.5" style={{ background: 'var(--surface-sunken)' }}>
                    <div className="flex items-center gap-1.5">
                      <TextInput mono value={asStr(step.id)} placeholder="step-id"
                                 onChange={(v) => patchStep(i, { id: v })} />
                      <select
                        className="ontogeny-input w-28 shrink-0 font-mono text-[12px]"
                        aria-label={`step-kind-${i}`}
                        value={kind}
                        onChange={(e) => patchStep(i, e.target.value === 'read'
                          ? { kind: 'read', object: undefined, filter: undefined, prompt: undefined }
                          : e.target.value === 'llm'
                            ? { kind: 'llm', prompt: '' }
                            : { kind: 'http', method: 'POST', url: '' })}
                      >
                        {STEP_KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
                      </select>
                      <button
                        type="button"
                        aria-label={t('ed.removeStep')}
                        data-testid={`step-remove-${i}`}
                        onClick={() => setSteps(steps.filter((_, j) => j !== i))}
                        className="grid size-7 shrink-0 place-items-center rounded-lg transition-colors hover:bg-[var(--surface-hover)]"
                        style={{ color: 'var(--tone-danger-fg)' }}
                      >
                        <IconTrash width={13} height={13} />
                      </button>
                    </div>

                    {kind === 'read' ? (
                      <div className="mt-2 grid grid-cols-2 gap-1.5">
                        <TextInput mono value={asStr(step.object)} placeholder="object-type"
                                   onChange={(v) => patchStep(i, { object: v })} />
                        <input
                          className="ontogeny-input font-mono text-[12px]"
                          aria-label={`step-filter-${i}`}
                          value={filterText[i] ?? (step.filter ? JSON.stringify(step.filter) : '')}
                          placeholder='{"equipment_id": "${param}"}'
                          onChange={(e) => {
                            const text = e.target.value
                            // keep what was typed even while it is not valid JSON,
                            // so the field does not fight the person editing it
                            setFilterText((prev) => ({ ...prev, [i]: text }))
                            if (!text.trim()) { patchStep(i, { filter: undefined }); return }
                            try {
                              const parsed = JSON.parse(text)
                              if (parsed && typeof parsed === 'object') patchStep(i, { filter: parsed })
                            } catch { /* still typing */ }
                          }}
                        />
                      </div>
                    ) : null}

                    {kind === 'llm' ? (
                      <div className="mt-2 flex flex-col gap-1.5">
                        <TextInput value={asStr(step.system)} placeholder={t('ed.stepSystem')}
                                   onChange={(v) => patchStep(i, { system: v || undefined })} />
                        <textarea
                          className="ontogeny-input min-h-[110px] w-full font-mono text-[11.5px] leading-relaxed"
                          spellCheck={false}
                          data-testid={`step-prompt-${i}`}
                          value={asStr(step.prompt)}
                          placeholder={t('ed.stepPromptPh')}
                          onChange={(e) => patchStep(i, { prompt: e.target.value })}
                        />
                      </div>
                    ) : null}

                    {kind === 'http' ? (
                      <div className="mt-2 grid grid-cols-[7rem_minmax(0,1fr)] gap-1.5">
                        <TextInput mono value={asStr(step.method, 'POST')}
                                   onChange={(v) => patchStep(i, { method: v })} />
                        <TextInput mono value={asStr(step.url)}
                                   placeholder={t('ed.httpUrlPh')}
                                   onChange={(v) => patchStep(i, { url: v })} />
                      </div>
                    ) : null}
                  </div>
                )
              })}
            </div>
          )}
        </Group>
      ) : null}

      <Group title={t('ed.returns')} hint={t('ed.returnsHint')}>
        <div className="grid grid-cols-2 gap-2.5">
          <Field label={t('ed.type')}>
            <input
              className="ontogeny-input font-mono text-[12px]"
              list="ontogeny-ed-property-types"
              value={asStr(returns.type)}
              onChange={(e) => update((r) => withSpec(r, { returns: { ...asObj(asObj(r.spec).returns), type: e.target.value } }))}
            />
          </Field>
          <Field label={t('ed.unit')}>
            <TextInput
              value={asStr(returns.unit)}
              onChange={(v) => update((r) => withSpec(r, { returns: { ...asObj(asObj(r.spec).returns), unit: v || undefined } }))}
            />
          </Field>
        </div>
      </Group>

      <Group
        title={t('ed.capabilities')}
        count={caps.length}
        hint={t('ed.capabilitiesHint')}
        action={<AddButton label={t('ed.addCapability')} onClick={() => setCaps([...caps, { 'read-objects': [] }])} />}
      >
        {caps.length === 0 ? <p className="text-[12px] muted">{t('ed.emptyList')}</p> : (
          <div className="flex flex-col gap-1.5">
            {caps.map((c, i) => {
              const kind = capKind(c)
              const value = c[kind]
              return (
                <Row key={i} removeLabel={t('ed.removeCapability')} onRemove={() => setCaps(caps.filter((_, j) => j !== i))}>
                  <select
                    className="ontogeny-input w-40 shrink-0 font-mono text-[12px]"
                    value={CAPABILITY_KINDS.includes(kind as typeof CAPABILITY_KINDS[number]) ? kind : CAPABILITY_KINDS[0]}
                    onChange={(e) => setCaps(caps.map((x, j) => (j === i
                      ? { [e.target.value]: e.target.value === 'read-objects' ? [] : true }
                      : x)))}
                  >
                    {CAPABILITY_KINDS.map((k) => <option key={k} value={k}>{k}</option>)}
                  </select>
                  {kind === 'read-objects' ? (
                    <input
                      className="ontogeny-input font-mono text-[12px]"
                      value={asStrList(value).join(', ')}
                      placeholder={t('ed.capObjectsPlaceholder')}
                      onChange={(e) => setCaps(caps.map((x, j) => (j === i
                        ? { 'read-objects': e.target.value.split(',').map((y) => y.trim()).filter(Boolean) }
                        : x)))}
                    />
                  ) : kind === 'http' ? (
                    // An http capability IS its host list: the runtime refuses
                    // every call when the list is empty, so an empty box is a
                    // function that cannot reach anything.
                    <input
                      className="ontogeny-input font-mono text-[12px]"
                      data-testid={`cap-http-allow-${i}`}
                      value={asStrList(asObj(value).allow).join(', ')}
                      placeholder={t('ed.capHttpAllowPlaceholder')}
                      onChange={(e) => setCaps(caps.map((x, j) => (j === i
                        ? { http: { allow: e.target.value.split(',').map((y) => y.trim()).filter(Boolean) } }
                        : x)))}
                    />
                  ) : (
                    <Check
                      label={t('ed.capabilityOn')}
                      checked={value !== false}
                      onChange={(on) => setCaps(caps.map((x, j) => (j === i ? { [kind]: on } : x)))}
                    />
                  )}
                </Row>
              )
            })}
          </div>
        )}
      </Group>


      {/* The body of a CODE function. Deliberately python-only: a declarative
          body is the steps group above, and showing an empty "runtime code"
          box for one was an answer to a question nobody asked. The governance
          sentence lives in the group hint (ed.sourceHint) — it says what this
          section IS: the file the sandbox executes, bounded by capabilities,
          published by saving. */}
      {runtime === 'python' ? (
        <Group
          title={t('ed.fnSource')}
          hint={t('ed.sourceHint')}
          action={source.data ? (
            <Badge tone={source.data.exists ? 'success' : 'warning'} mono>
              {source.data.exists ? t('ed.sourceReady') : t('ed.sourceMissing')}
            </Badge>
          ) : null}
        >
          {source.isLoading ? <Skeleton rows={2} /> : source.error ? (
            <ErrorBanner error={source.error} />
          ) : (
            <>
              {!source.data?.exists ? (
                <Alert tone="warning" title={t('ed.sourceMissing')}>
                  {t('ed.sourceMissingHint', { path: source.data?.path ?? '' })}
                </Alert>
              ) : null}

              <PythonEditor
                label={t('ed.fnSource')}
                testId="function-source"
                value={buffer}
                onChange={setCode}
              />
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <Button
                  variant="primary"
                  size="sm"
                  data-testid="function-source-save"
                  disabled={saving || restored === disk}
                  onClick={() => save.mutate()}
                >
                  {saving ? t('ed.saving') : t('ed.saveAndPublish')}
                </Button>
                <Button
                  size="sm"
                  data-testid="function-test-run"
                  title={t('ed.testRunHint')}
                  disabled={testing || !buffer.trim()}
                  onClick={() => test.mutate()}
                >
                  {testing ? t('ed.testing') : t('ed.testRun')}
                </Button>
                <span className="text-[11px] muted">{t('ed.codeRevisionHint')}</span>
              </div>

              {save.error ? <div className="mt-2"><ErrorBanner error={save.error} /></div> : null}
              {save.data ? (
                <div className="mt-2" data-testid="function-source-saved">
                  <Alert tone={save.data.changed === false ? 'info' : 'success'}>
                    {save.data.changed === false
                      ? t('ed.codeUnchanged')
                      : t('ed.codeSaved', {
                        version: save.data.version ?? '—',
                        bytes: save.data.bytes ?? 0,
                      })}
                  </Alert>
                </div>
              ) : null}

              {test.error ? (
                /* a syntax error arrives as a 4xx, so it lands here rather
                   than in the in-band result below */
                <div className="mt-2" data-testid="function-test-result">
                  <ErrorBanner error={test.error} />
                </div>
              ) : null}
              {test.data ? (
                <div className="mt-2" data-testid="function-test-result">
                  <Alert tone={test.data.ok ? 'success' : 'warning'}>
                    {test.data.ok
                      ? t('ed.testOk', { value: JSON.stringify(test.data.value)?.slice(0, 160) ?? '' })
                      : t('ed.testFailed', { message: test.data.message ?? '' })}
                    {/* Which inputs the run invented, and where each came from:
                        a test result is only readable if you know that. */}
                    {Object.keys(test.data.params ?? {}).length ? (
                      <ul className="mt-1 flex flex-col gap-0.5 text-[11px] muted" data-testid="test-params">
                        {Object.entries(test.data.params ?? {}).map(([k, v]) => (
                          <li key={k} className="font-mono">
                            {k} = {JSON.stringify(v)}
                            <span className="ml-1.5 not-italic">
                              （{test.data?.param_sources?.[k] ?? ''}）
                            </span>
                          </li>
                        ))}
                      </ul>
                    ) : null}
                  </Alert>
                </div>
              ) : null}

              {source.data?.revisions?.length ? (
                /* Collapsed by default: the history is reference material, and a
                   list that grows with every save should not push the editor's
                   own controls down the dialog. */
                <details className="mt-2" data-testid="function-source-revisions">
                  <summary
                    className="cursor-pointer select-none text-[11.5px] muted hover:underline"
                    data-testid="revisions-toggle"
                  >
                    {t('ed.revisionHistory')} · {source.data.revisions.length}
                  </summary>
                  <ul className="mt-1.5 flex flex-col gap-0.5 text-[11.5px]">
                    {(source.data.revisions ?? []).map((r) => (
                      <li key={r.id} className="flex flex-wrap items-center gap-2 muted">
                        <span className="font-mono">{r.version ?? '—'}</span>
                        <span>{r.principal}</span>
                        <span>{new Date(r.at).toLocaleString()}</span>
                        <span>{r.bytes} B</span>
                      </li>
                    ))}
                  </ul>
                </details>
              ) : null}
            </>
          )}
        </Group>
      ) : null}
    </div>
  )
}

/* -------------------------------------------------------------- PolicySet */

export function PolicySetEditor({ resource, update, rename }: EditorProps) {
  const { t } = useI18n()
  const source = asStr(spec(resource).source)
  const rules = (source.match(/permit\(/g) ?? []).length
  return (
    <div className="flex flex-col gap-3" data-testid="policy-editor">
      <Identity resource={resource} update={update} rename={rename} />
      <Group title={t('ed.cedar')} hint={t('ed.cedarHint')} action={<Badge tone="danger">{t('data.policyRules', { count: rules })}</Badge>}>
        <textarea
          className="ontogeny-input min-h-[240px] w-full font-mono text-[11.5px] leading-relaxed"
          spellCheck={false}
          value={source}
          data-testid="policy-source"
          onChange={(e) => update((r) => withSpec(r, { source: e.target.value }))}
        />
      </Group>
    </div>
  )
}
