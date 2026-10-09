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
 * ResourceWorkbench — the two-pane editor every Knowledge/Action tab uses.
 *
 * Left: the resources of one kind, searchable, with create/delete. Right: the
 * selected resource's form (plus whatever the tab wants underneath it — the
 * object tab adds the type's live sample rows). The pane is a *list*: these
 * pages answer "what does the model say?", and a table of names with the editor
 * beside it beats hunting for a card.
 *
 * The save bar lives here too, because "unsaved changes" is a property of the
 * session, not of one tab: whatever is dirty anywhere is saved in one publish.
 */
import { useMemo, useState } from 'react'
import { useI18n } from '../i18n'
import {
  Alert, Badge, Button, Card, ConfirmDialog, EmptyState, LiveRegion, Panel, Skeleton,
} from './ui'
import { ErrorBanner } from './ErrorBanner'
import { IconCheck, IconPlus, IconSearch, IconTrash, IconX } from './icons'
import { toYaml } from '../api/yaml'
import { rkey, uniqueName, type ResourceKind } from '../api/resources'
import { useOntologyDraft } from '../pages/ontology/draft'
import type { OntologyResource } from '../api/types'

export interface WorkbenchProps {
  kind: ResourceKind
  /** The chapter tabs, rendered into this card's toolbar so the page is one
   *  surface: chapter switch + save controls + list + editor. */
  tabs: React.ReactNode
  /** One line under the tab strip explaining what these resources are. */
  hint: string
  /** Build a brand-new resource of this kind (already uniquely named). */
  makeNew: (name: string, objectNames: string[]) => OntologyResource
  /** Renders the form for the selected resource. */
  renderEditor: (res: OntologyResource) => React.ReactNode
  /** Extra panel under the editor (the object tab's sample rows). */
  renderBelow?: (res: OntologyResource) => React.ReactNode
  /** Extra column in the list row (e.g. a row count). */
  renderRowExtra?: (res: OntologyResource) => React.ReactNode
}

export function ResourceWorkbench(props: WorkbenchProps) {
  const { t } = useI18n()
  const draft = useOntologyDraft()
  const [query, setQuery] = useState('')
  const [selected, setSelected] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [showYaml, setShowYaml] = useState(false)

  const all = draft.ofKind(props.kind)
  const items = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return all
    return all.filter((r) =>
      r.metadata.name.toLowerCase().includes(q) || (r.metadata.display ?? '').toLowerCase().includes(q))
  }, [all, query])

  const current = selected ? draft.get(props.kind, selected) : undefined

  const create = () => {
    const name = uniqueName(
      props.kind === 'ObjectType' ? 'new-object'
        : props.kind === 'LinkType' ? 'new-link'
        : props.kind === 'Projection' ? 'new-projection'
        : props.kind === 'Action' ? 'new-action'
        : props.kind === 'Function' ? 'new-function'
        : 'new-policy',
      all.map((r) => r.metadata.name),
    )
    draft.create(props.makeNew(name, draft.objectNames))
    setSelected(name)
    setQuery('')
  }

  if (draft.loading && all.length === 0) return <Skeleton rows={8} />

  return (
    <>
    <Card
      padded={false}
      className="flex min-h-0 flex-1 flex-col"
      bodyClassName="flex min-h-0 flex-1 flex-col"
      toolbar={
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-2">
          {props.tabs}
          <span className="ml-auto flex flex-wrap items-center gap-2">
            <span data-testid="ed-dirty-badge">
              <Badge tone={draft.dirty ? 'warning' : 'success'}>
                {draft.dirty ? t('ed.unsavedCount', { count: draft.touched.size + draft.removed.size }) : t('ed.inSync')}
              </Badge>
            </span>
            <Button size="sm" onClick={() => setShowYaml((v) => !v)} data-testid="ed-yaml-toggle">
              {showYaml ? t('ed.hideYaml') : t('ed.showYaml')}
            </Button>
            <Button size="sm" onClick={draft.discard} disabled={!draft.dirty || draft.saving} data-testid="ed-discard">
              {t('ed.discard')}
            </Button>
            <Button
              size="sm"
              variant="primary"
              onClick={() => void draft.save()}
              disabled={!draft.dirty || draft.saving}
              data-testid="ed-save"
              icon={<IconCheck width={13} height={13} />}
            >
              {draft.saving ? t('ed.saving') : t('ed.save')}
            </Button>
          </span>
        </div>
      }
    >
      {/* session-level notices: a restored draft, the last publish, a failure */}
      {draft.loadError || draft.restoredAt || draft.saveError || draft.saveResult || showYaml ? (
        <div className="flex shrink-0 flex-col gap-2 px-5 py-3" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
          {draft.loadError ? <ErrorBanner error={new Error(draft.loadError)} /> : null}
          {draft.restoredAt ? (
            <Alert
              tone="info"
              title={t('ed.draftRestored')}
              action={<Button size="sm" onClick={draft.discard}>{t('ed.draftDiscard')}</Button>}
            >
              {t('ed.draftRestoredHint')}
            </Alert>
          ) : null}

          <LiveRegion>
            {draft.saveError
              ? `${t('ed.saveFailed')}: ${draft.saveError}`
              : draft.saveResult
                ? t('ed.saveOk', { hash: draft.saveResult.content_hash.slice(0, 12) })
                : ''}
          </LiveRegion>

          {draft.saveError ? (
            <Alert tone="danger" title={t('ed.saveFailed')}>
              <pre className="mt-1 whitespace-pre-wrap font-mono text-[11.5px]">{draft.saveError}</pre>
            </Alert>
          ) : null}

          {draft.saveResult ? (
            <Alert
              tone={draft.saveResult.issues.some((i) => i.severity === 'error') ? 'warning' : 'success'}
              title={t('ed.saveOk', { hash: draft.saveResult.content_hash.slice(0, 12) })}
              action={<Button size="sm" onClick={draft.dismissSaveResult} icon={<IconX width={12} height={12} />} />}
            >
              <span className="flex flex-wrap items-center gap-2">
                <span>{t('ed.written', { count: draft.saveResult.written.length })}</span>
                {draft.saveResult.removed.length ? <span>{t('ed.removed', { count: draft.saveResult.removed.length })}</span> : null}
                {draft.saveResult.issues.filter((i) => i.severity !== 'ok').map((i) => (
                  <Badge key={i.code} tone={i.severity === 'error' ? 'danger' : 'warning'} mono>{i.code}</Badge>
                ))}
              </span>
            </Alert>
          ) : null}

          {showYaml ? <YamlPreview /> : null}
        </div>
      ) : null}

      <div className="grid min-h-0 flex-1 lg:grid-cols-[290px_1fr]">
        {/* ------------------------------------------------------- the list */}
        <aside
          className="flex min-h-0 flex-col border-b lg:border-b-0 lg:border-r"
          style={{ borderColor: 'var(--border-subtle)' }}
        >
          <div className="flex shrink-0 items-center gap-2 px-3 py-2.5" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
            <span className="relative min-w-0 flex-1">
              <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 muted">
                <IconSearch width={13} height={13} />
              </span>
              <input
                className="ontogeny-input pl-7 text-[12.5px]"
                placeholder={t('ed.filter')}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </span>
            <Button size="sm" onClick={create} data-testid={`${props.kind}-create`} icon={<IconPlus width={13} height={13} />} title={t('ed.create')} />
          </div>

          <div className="min-h-0 flex-1 overflow-y-auto p-2">
            {items.length === 0 ? (
              <p className="px-2 py-6 text-center text-[12px] muted">
                {all.length === 0 ? t('ed.none') : t('ed.noMatch')}
              </p>
            ) : (
              <ul className="flex flex-col gap-0.5" data-testid={`${props.kind}-list`}>
                {items.map((r) => {
                  const name = r.metadata.name
                  const active = name === selected
                  const isDirty = draft.touched.has(rkey(props.kind, name))
                  return (
                    <li key={name}>
                      <button
                        type="button"
                        onClick={() => setSelected(name)}
                        data-testid={`${props.kind}-item-${name}`}
                        className="flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left transition-colors"
                        style={{ background: active ? 'var(--brand-tint)' : 'transparent' }}
                      >
                        <span className="min-w-0 flex-1">
                          <span className="flex items-center gap-1.5">
                            <span className="truncate font-mono text-[12.5px]" style={{ fontWeight: active ? 600 : 500 }}>
                              {name}
                            </span>
                            {isDirty ? <span className="size-1.5 shrink-0 rounded-full" style={{ background: 'var(--tone-warning-fg)' }} title={t('ed.unsaved')} /> : null}
                          </span>
                          {r.metadata.display ? (
                            <span className="mt-0.5 block truncate text-[11.5px] muted">{r.metadata.display}</span>
                          ) : null}
                          {props.renderRowExtra ? <span className="mt-1 block">{props.renderRowExtra(r)}</span> : null}
                        </span>
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}
          </div>

          <div className="shrink-0 px-3 py-2 text-[11px] muted" style={{ borderTop: '1px solid var(--border-subtle)' }}>
            {props.hint}
          </div>
        </aside>

        {/* ----------------------------------------------------- the editor */}
        <section className="min-h-0 flex-1 overflow-y-auto p-4">
          {!current ? (
            <EmptyState
              title={t('ed.selectTitle')}
              description={t('ed.selectHint')}
              icon={<IconPlus width={18} height={18} />}
              action={<Button size="sm" variant="primary" onClick={create}>{t('ed.create')}</Button>}
            />
          ) : (
            <div className="mx-auto flex max-w-3xl flex-col gap-4">
              <header className="flex flex-wrap items-center justify-between gap-3">
                <h2 className="flex min-w-0 items-center gap-2 text-[14px] font-semibold">
                  <span className="truncate font-mono">{current.metadata.name}</span>
                  {draft.touched.has(rkey(props.kind, current.metadata.name))
                    ? <Badge tone="warning">{t('ed.unsaved')}</Badge>
                    : <Badge tone="success">{t('ed.saved')}</Badge>}
                </h2>
                <Button
                  size="sm"
                  variant="danger"
                  onClick={() => setConfirmDelete(current.metadata.name)}
                  data-testid={`${props.kind}-delete`}
                  icon={<IconTrash width={13} height={13} />}
                >
                  {t('ed.delete')}
                </Button>
              </header>

              {props.renderEditor(current)}
              {props.renderBelow ? props.renderBelow(current) : null}
            </div>
          )}
        </section>
      </div>
    </Card>

      <ConfirmDialog
        open={confirmDelete !== null}
        title={t('ed.confirmDelete')}
        message={t('ed.confirmDeleteHint', { name: confirmDelete ?? '' })}
        confirmLabel={t('ed.delete')}
        cancelLabel={t('common.cancel')}
        onCancel={() => setConfirmDelete(null)}
        onConfirm={() => {
          if (confirmDelete) draft.remove(props.kind, confirmDelete)
          if (confirmDelete === selected) setSelected(null)
          setConfirmDelete(null)
        }}
      />
    </>
  )
}

/** The exact resources the next save would write (the same YAML writer the
 *  Scenario Builder's preview uses). */
function YamlPreview() {
  const { t } = useI18n()
  const draft = useOntologyDraft()
  const changed = draft.resources.filter((r) => draft.touched.has(rkey(r.kind, r.metadata.name)))
  // the same writer the Scenario Builder's preview uses, over exactly what the
  // next save would send
  const text = useMemo(
    () => toYaml(changed as unknown as Array<Record<string, unknown>>),
    [changed],
  )

  return (
    <Panel className="max-h-[40vh] overflow-auto p-0">
      <div className="flex items-center gap-2 px-3 py-2 text-[11.5px] muted" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
        {t('ed.yamlHint', { count: changed.length })}
      </div>
      <pre className="overflow-auto p-3 font-mono text-[11.5px] leading-relaxed" style={{ maxHeight: '34vh' }}>
        {changed.length ? text : t('ed.yamlEmpty')}
      </pre>
    </Panel>
  )
}
