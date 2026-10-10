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
 * OntologyExplorer — the ontology, editable on one page.
 *
 * The canvas is the model: object types as compact cards, their actions and
 * functions as small satellites hanging off them (many of each belong to one
 * type, so they cannot live inside its card). One colour for object types,
 * because fifteen hues were decoration rather than information; the satellites
 * keep a colour each, where it does distinguish kinds.
 *
 * Nothing here navigates away. Clicking any node opens it in the right-hand
 * panel — the model's own detail plus what hangs off it — and editing opens the
 * full form in a modal, because a property table needs more width than a detail
 * column has. Every edit lands in the shared draft and only reaches the server
 * when the toolbar's save button is pressed; the same is true of a hand-arranged
 * layout, which is why dragging marks the page dirty rather than silently
 * rewriting anything.
 */
import { useEffect, useMemo, useState } from 'react'
import { useI18n } from '../i18n'
import { Alert, Badge, Button, Card, CodeBlock, ConfirmDialog, EmptyState, LiveRegion, MenuButton, Page, Skeleton } from '../components/ui'
import { FlowGraph } from '../components/FlowGraph'
import type { GraphLegendItem } from '../components/GraphLegend'
import { ErrorBanner } from '../components/ErrorBanner'
import { ResourceDialog } from '../components/ResourceDialog'
import { DataMountDialog } from '../components/DataMountDialog'
import { useOntologyDraft } from './ontology/draft'
import { asObj, asStr, asStrList, rkey, uniqueName, type ResourceKind } from '../api/resources'
import { modelIssues } from '../api/modelIssues'
import { toYaml } from '../api/yaml'
import { ontologyToFlow, ontNodeId, parseOntNodeId, type OntologyNodeRef } from '../components/graphAdapters'
import { ATTACHED_COLOR, KIND_COLOR, KIND_ORDER, kindIconSrc } from '../components/nodeKinds'
import {
  IconAddNode, IconBolt, IconBraces, IconCheck, IconCode, IconCube, IconDatabase,
  IconEraser, IconLinkType, IconList, IconPencil, IconPlus, IconRefresh, IconShield,
  IconTrash, IconUndo, IconX,
} from '../components/icons'
import type { OntologyResource } from '../api/types'

/** `sel.kind` names the *ref*; the i18n key names the model element. They differ
 *  for object types (`object` vs `type`), and using the ref directly leaked the
 *  raw key into the panel header. */
const NODE_LABEL_KEY: Record<OntologyNodeRef['kind'], string> = {
  object: 'ontology.node.type',
  link: 'ontology.node.link',
  action: 'ontology.node.action',
  function: 'ontology.node.function',
  policy: 'ontology.node.policy',
  projection: 'ontology.node.projection',
}

/** The one colour every object type is drawn in. */
const OBJECT_COLOR = '#2e5bff'

export function OntologyExplorer() {
  const { t } = useI18n()
  const draft = useOntologyDraft()
  const [sel, setSel] = useState<OntologyNodeRef | null>(null)
  const [indexOpen, setIndexOpen] = useState(false)
  const [editing, setEditing] = useState<{ kind: ResourceKind; name: string; isNew?: boolean } | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<{ kind: ResourceKind; name: string } | null>(null)
  const [confirmClear, setConfirmClear] = useState(false)
  const [showYaml, setShowYaml] = useState(false)
  const [mountOpen, setMountOpen] = useState(false)
  /** Which type the mount dialog should open on, when it was launched from a
   *  type's own panel rather than the toolbar. */
  const [mountFor, setMountFor] = useState<string | null>(null)
  useEffect(() => draft.ensureLoaded(), [draft])

  const objects = draft.ofKind('ObjectType')
  const actions = draft.ofKind('Action')
  const functions = draft.ofKind('Function')
  const links = draft.ofKind('LinkType')

  const data = useMemo(
    () => ontologyToFlow(draft.resources, draft.layout, OBJECT_COLOR),
    [draft.resources, draft.layout],
  )

  /** The canvas's colour key: the three model kinds, exactly as drawn. Short
   *  labels — the legend is a key, not a taxonomy. */
  const legendItems = useMemo<GraphLegendItem[]>(() => (
    KIND_ORDER.map((kind) => ({
      id: kind,
      label: t(`ontology.legend.${kind}`),
      color: KIND_COLOR[kind],
      iconSrc: kindIconSrc(kind, KIND_COLOR[kind]),
    }))
  ), [t])

  /** Local checks, so a name typo or a dangling link is caught on the canvas
   *  instead of bouncing back from the publish. */
  const issues = useMemo(() => modelIssues(draft.resources), [draft.resources])
  const errorCount = issues.filter((i) => i.severity === 'error').length

  /** Exactly what the next save would write: the touched resources and the
   *  explicit deletes. Untouched YAML on disk is never rewritten. */
  const pending = useMemo(
    () => draft.resources.filter((r) => draft.touched.has(rkey(r.kind, r.metadata.name))),
    [draft.resources, draft.touched],
  )
  const pendingYaml = useMemo(
    () => toYaml(pending as unknown as Array<Record<string, unknown>>),
    [pending],
  )

  /** The object types the mount dialog may attach a source to. */
  const mountable = useMemo(
    () => objects.map((o) => ({
      name: o.metadata.name,
      display: o.metadata.display,
      properties: Object.entries(asObj(o.spec.properties)).map(([name, def]) => ({
        name,
        required: Boolean(asObj(def).required),
      })),
    })),
    [objects],
  )

  // a link is drawn as a connection, everything else as a node
  const selectedId = sel && sel.kind !== 'link'
    ? sel.kind === 'object' ? ontNodeId.object(sel.name)
      : sel.kind === 'action' ? ontNodeId.action(sel.name)
      : ontNodeId.function(sel.name)
    : null
  const selectedEdgeId = sel?.kind === 'link' ? ontNodeId.link(sel.name) : null

  if (draft.loading && draft.resources.length === 0) {
    return <Page fill><Skeleton rows={8} /></Page>
  }

  const openNew = (kind: ResourceKind, forType?: string) => {
    const base = kind === 'ObjectType' ? 'new-object'
      : kind === 'Action' ? 'new-action'
      : kind === 'Function' ? 'new-function'
      : kind === 'LinkType' ? 'new-link' : 'new-policy'
    const name = uniqueName(base, draft.ofKind(kind).map((r) => r.metadata.name))
    const res = makeResource(kind, name, draft.objectNames)
    // created from a type's panel, the new action/function starts out wired to
    // that type: an action targets it, a function declares it readable
    if (forType) {
      if (kind === 'Action') res.spec = { ...res.spec, target: forType }
      if (kind === 'Function') res.spec = { ...res.spec, capabilities: [{ 'read-objects': [forType] }] }
      if (kind === 'LinkType') res.spec = { ...res.spec, source: forType }
    }
    draft.create(res)
    setEditing({ kind, name, isNew: true })
  }

  const openEdit = (kind: ResourceKind, name: string) => setEditing({ kind, name })

  /** Create a policy and attach it to the action in one step.
   *
   * A policy only ever exists to be referenced by an action, so creating one
   * from the action's own panel wires the two together immediately — leaving
   * that second step to the user is how models end up with orphan policies. */
  const openNewPolicyFor = (action: OntologyResource) => {
    const name = uniqueName('new-policy', draft.ofKind('PolicySet').map((r) => r.metadata.name))
    draft.create(makeResource('PolicySet', name, draft.objectNames))
    draft.update('Action', action.metadata.name, (r) => ({
      ...r, spec: { ...r.spec, policy: name },
    }))
    setEditing({ kind: 'PolicySet', name, isNew: true })
  }

  const current = editing ? draft.get(editing.kind, editing.name) : undefined

  return (
    <Page fill testId="ontology-explorer">
      <h1 className="sr-only">{t('ontology.title')}</h1>

      {draft.loadError ? <ErrorBanner error={new Error(draft.loadError)} /> : null}

      <Card
        padded={false}
        className="flex min-h-0 flex-1 flex-col"
        bodyClassName="flex min-h-0 flex-1 flex-col"
        toolbar={
          <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-3 gap-y-2" data-testid="ontology-toolbar">
            <StatChip label={t('ontology.types')} value={objects.length} />
            <StatChip label={t('ontology.links')} value={links.length} />
            <StatChip label={t('ontology.actions')} value={actions.length} />
            <StatChip label={t('ontology.functions')} value={functions.length} />

            {/* One `+`, five kinds. Five labelled buttons was a paragraph of
                chrome at the head of the toolbar; the glyph is the action and
                the menu is where the words live. */}
            <MenuButton
              variant="primary"
              label={t('ontology.create')}
              icon={<IconAddNode width={15} height={15} />}
              testId="palette-new"
              menuTestId="palette-menu"
              items={[
                { id: 'palette-object', label: t('ontology.newType'), hint: t('ontology.newTypeHint'), icon: <IconCube width={13} height={13} />, onSelect: () => openNew('ObjectType') },
                { id: 'palette-action', label: t('ontology.newAction'), hint: t('ontology.newActionHint'), icon: <IconBolt width={13} height={13} />, onSelect: () => openNew('Action') },
                { id: 'palette-function', label: t('ontology.newFunction'), hint: t('ontology.newFunctionHint'), icon: <IconBraces width={13} height={13} />, onSelect: () => openNew('Function') },
                { id: 'palette-link', label: t('ontology.newLink'), hint: t('ontology.newLinkHint'), icon: <IconLinkType width={13} height={13} />, onSelect: () => openNew('LinkType') },
                { id: 'palette-policy', label: t('ontology.newPolicy'), hint: t('ontology.newPolicyHint'), icon: <IconShield width={13} height={13} />, onSelect: () => openNew('PolicySet') },
              ]}
            />

            {/* wraps instead of forcing the toolbar wider than the card:
                `shrink-0` here overflowed the page at 480px */}
            <span className="ml-auto flex min-w-0 flex-wrap items-center gap-1.5">
              {issues.length ? (
                <span data-testid="ontology-issues">
                  <Badge tone={errorCount ? 'danger' : 'warning'}>
                    {t('ontology.issues', { count: issues.length })}
                  </Badge>
                </span>
              ) : null}
              <span data-testid="ontology-dirty">
                <Badge tone={draft.dirty ? 'warning' : 'success'}>
                  {draft.dirty
                    ? t('ed.unsavedCount', { count: draft.touched.size + draft.removed.size })
                    : t('ed.inSync')}
                </Badge>
              </span>
              {/* Icon-only from here on: the label lives in the tooltip. A
                  modelling toolbar is a row of verbs you learn once, and words
                  for all of them crowded out the thing being modelled. */}
              <Button
                size="sm"
                square
                data-testid="ontology-reset-layout"
                title={t('ontology.resetLayoutHint')}
                aria-label={t('ontology.resetLayout')}
                onClick={draft.resetLayout}
                icon={<IconRefresh width={14} height={14} />}
              />
              <Button
                size="sm"
                square
                data-testid="ontology-discard"
                title={t('ed.discardHint')}
                aria-label={t('ed.discard')}
                disabled={!draft.dirty || draft.saving}
                onClick={draft.discard}
                icon={<IconUndo width={14} height={14} />}
              />
              <Button
                size="sm"
                square
                variant="primary"
                data-testid="ontology-save"
                disabled={!draft.dirty || draft.saving || errorCount > 0}
                title={errorCount > 0 ? t('ontology.saveBlocked') : t('ontology.saveHint')}
                aria-label={draft.saving ? t('ed.saving') : t('ed.save')}
                onClick={() => void draft.save()}
                icon={<IconCheck width={15} height={15} />}
              />
              <Button
                size="sm"
                square
                data-testid="ontology-yaml-toggle"
                aria-pressed={showYaml}
                title={showYaml ? t('ontology.hideYaml') : t('ontology.showYaml')}
                aria-label={showYaml ? t('ontology.hideYaml') : t('ontology.showYaml')}
                onClick={() => setShowYaml((v) => !v)}
                icon={<IconCode width={14} height={14} />}
              />
              <Button
                size="sm"
                square
                data-testid="ontology-clear"
                disabled={draft.saving}
                title={t('ontology.clearHint')}
                aria-label={t('ontology.clear')}
                onClick={() => setConfirmClear(true)}
                icon={<IconEraser width={14} height={14} />}
              />
              <Button
                size="sm"
                square
                data-testid="ontology-index-toggle"
                aria-pressed={indexOpen}
                title={t('ontology.indexHint')}
                aria-label={t('ontology.index')}
                onClick={() => { setIndexOpen(true); setSel(null) }}
                icon={<IconList width={14} height={14} />}
              />
            </span>
          </div>
        }
      >
        {draft.saveError ? (
          <div className="shrink-0 px-5 py-3" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
            <ErrorBanner error={new Error(draft.saveError)} />
          </div>
        ) : null}

        {draft.saveResult ? (
          <div className="shrink-0 px-5 py-3" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
            <LiveRegion>
              <Alert
                tone={draft.saveResult.issues.some((i) => i.severity === 'error') ? 'warning' : 'success'}
                title={t('ontology.saveOk', { hash: draft.saveResult.content_hash.slice(0, 12) })}
                action={
                  <Button size="sm" data-testid="ontology-save-result-close" onClick={draft.dismissSaveResult}>
                    {t('common.close')}
                  </Button>
                }
              >
                <div className="space-y-1 text-[12px]">
                  {draft.saveResult.written.length > 0 ? (
                    <div>{t('ontology.written', { n: draft.saveResult.written.length })}: <code>{draft.saveResult.written.join(', ')}</code></div>
                  ) : null}
                  {draft.saveResult.removed.length > 0 ? (
                    <div>{t('ontology.removed', { n: draft.saveResult.removed.length })}: <code>{draft.saveResult.removed.join(', ')}</code></div>
                  ) : null}
                  {draft.saveResult.issues.filter((i) => i.severity !== 'ok').map((i, ix) => (
                    <div key={ix}><Badge tone={i.severity === 'error' ? 'danger' : 'warning'}>{i.code}</Badge> {i.message}</div>
                  ))}
                </div>
              </Alert>
            </LiveRegion>
          </div>
        ) : null}

        {/* Local model checks: the node is one click away, so these are stated
            on the canvas rather than only after a failed publish. */}
        {issues.length > 0 ? (
          <div className="shrink-0 px-5 py-3" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
            <Alert tone={errorCount ? 'danger' : 'warning'} title={t('ontology.issuesTitle')}>
              <ul className="ml-4 max-h-24 list-disc space-y-0.5 overflow-y-auto" data-testid="ontology-issue-list">
                {issues.map((i, ix) => (
                  <li key={`${i.key}-${ix}`}>
                    <button
                      type="button"
                      className="text-left hover:underline"
                      onClick={() => {
                        const ref = i.kind === 'ObjectType' ? 'object'
                          : i.kind === 'Action' ? 'action'
                          : i.kind === 'Function' ? 'function' : 'link'
                        setIndexOpen(false)
                        setSel({ kind: ref as OntologyNodeRef['kind'], name: i.name })
                      }}
                    >
                      <span className="font-mono">{i.key}</span> · {t(i.message, i.params ?? {})}
                    </button>
                  </li>
                ))}
              </ul>
            </Alert>
          </div>
        ) : null}

        <div className="relative flex min-h-0 flex-1">
          <div className="ontogeny-canvas-grid relative min-h-0 min-w-0 flex-1">
            {objects.length === 0 ? (
              <div className="grid h-full place-items-center p-6">
                <EmptyState
                  icon={<IconCube width={22} height={22} />}
                  title={t('ontology.graph.empty')}
                  description={t('ontology.graph.emptyHint')}
                  action={<Button variant="primary" onClick={() => openNew('ObjectType')} icon={<IconPlus width={13} height={13} />}>{t('ontology.newType')}</Button>}
                />
              </div>
            ) : (
              <>
                <FlowGraph
                  data={data}
                  fill
                  cardSize={[210, 60]}
                  selectedId={selectedId}
                  selectedEdgeId={selectedEdgeId}
                  testId="ontology-flow"
                  // one cluster of canvas controls, bottom-left stacked above
                  // the legend: zoom in/out/fit used to sit in the opposite
                  // corner, which read as two unrelated toolbars on one canvas
                  controlsInset="16px"
                  legendItems={legendItems}
                  onNodeClick={(n) => { setIndexOpen(false); setSel(parseOntNodeId(n.id)) }}
                  onEdgeClick={(e) => { setIndexOpen(false); setSel(parseOntNodeId(e.id ?? '')) }}
                  onNodeDragEnd={(n) => { if (n.x !== undefined && n.y !== undefined) draft.moveNode(n.id, n.x, n.y) }}
                  onCanvasClick={() => { setSel(null); setIndexOpen(false) }}
                />
              </>
            )}
          </div>

          {indexOpen || sel ? (
            <aside
              className="relative z-10 flex h-full w-[360px] shrink-0 flex-col max-lg:absolute max-lg:inset-y-0 max-lg:right-0 max-lg:z-30 max-lg:w-[330px]"
              style={{ background: 'var(--surface-card)', borderLeft: '1px solid var(--border-subtle)' }}
              data-testid="ontology-panel"
            >
              <header className="flex shrink-0 items-center justify-between gap-2 px-4 py-3" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                <h2 className="min-w-0 truncate text-[13px] font-semibold tracking-wide">
                  {sel ? `${t(NODE_LABEL_KEY[sel.kind])} · ${sel.name}` : t('ontology.index')}
                </h2>
                <button
                  type="button"
                  data-testid="ontology-panel-close"
                  aria-label={t('common.close')}
                  onClick={() => { setSel(null); setIndexOpen(false) }}
                  className="grid size-7 shrink-0 place-items-center rounded-lg muted transition-colors hover:bg-[var(--surface-hover)]"
                >
                  <IconX width={14} height={14} />
                </button>
              </header>

              <div className="min-h-0 flex-1 overflow-y-auto p-4">
                {sel ? (
                  <NodeDetail
                    sel={sel}
                    draft={draft}
                    onEdit={openEdit}
                    onNew={openNew}
                    onDelete={(kind, name) => setConfirmDelete({ kind, name })}
                    onPick={(ref) => { setIndexOpen(false); setSel(ref) }}
                    onMount={(name) => { setMountFor(name); setMountOpen(true) }}
                    onNewPolicyFor={(action) => openNewPolicyFor(action)}
                  />
                ) : (
                  <TypeIndex
                    draft={draft}
                    onPick={(ref) => { setIndexOpen(false); setSel(ref) }}
                    onNew={openNew}
                  />
                )}
              </div>
            </aside>
          ) : null}
        </div>

        {/* The YAML preview: what the next save writes, verbatim. A form can
            only show the fields it models, so this is how a resource that
            carries more than the form knows stays inspectable. */}
        {showYaml ? (
          <div
            className="absolute inset-x-0 bottom-0 z-40 max-h-[52vh] overflow-y-auto px-5 pb-4"
            data-testid="ontology-yaml"
          >
            <Card>
              <div className="mb-1.5 flex items-center justify-between px-1">
                <h3 className="text-[12.5px] font-semibold">{t('ontology.yamlTitle')}</h3>
                <span className="flex items-center gap-2 text-[10.5px] muted">
                  {t('ontology.yamlHint', { count: pending.length })}
                  <button type="button" onClick={() => setShowYaml(false)} className="ontogeny-btn-subtle px-1.5" aria-label={t('common.close')}>
                    <IconX width={13} height={13} />
                  </button>
                </span>
              </div>
              <CodeBlock
                code={pendingYaml || t('ontology.yamlEmpty')}
                language="yaml"
                maxHeight={280}
              />
            </Card>
          </div>
        ) : null}
      </Card>

      {/* Editing opens a modal: a property table, a parameter list and a set of
          effect rows need more width than a 360px detail column has. */}
      {editing && current ? (
        <ResourceDialog
          open
          kind={editing.kind}
          resource={current}
          objectNames={draft.objectNames}
          policyNames={draft.ofKind('PolicySet').map((p) => p.metadata.name)}
          onClose={() => setEditing(null)}
          onRename={(to) => {
            draft.rename(editing.kind, editing.name, to)
            setEditing({ ...editing, name: to })
            if (sel?.name === editing.name) setSel({ ...sel, name: to })
          }}
          update={(next) => draft.update(editing.kind, editing.name, next)}
        />
      ) : null}

      <ConfirmDialog
        open={confirmDelete !== null}
        title={t('ontology.confirmDelete')}
        message={t('ontology.confirmDeleteHint', { name: confirmDelete?.name ?? '' })}
        confirmLabel={t('ed.delete')}
        cancelLabel={t('common.cancel')}
        onCancel={() => setConfirmDelete(null)}
        onConfirm={() => {
          if (confirmDelete) draft.remove(confirmDelete.kind, confirmDelete.name)
          if (confirmDelete && sel?.name === confirmDelete.name) setSel(null)
          setConfirmDelete(null)
        }}
      />

      <ConfirmDialog
        open={confirmClear}
        tone="warning"
        title={t('ontology.confirmClear')}
        message={t('ontology.confirmClearHint')}
        confirmLabel={t('ontology.clear')}
        cancelLabel={t('common.cancel')}
        onCancel={() => setConfirmClear(false)}
        onConfirm={() => {
          setConfirmClear(false)
          setSel(null)
          setIndexOpen(false)
          draft.reloadFromServer()
        }}
      />

      {/* Data mounting lives with the model it binds: the store resource and
          the object's backing are written and published by the same endpoint
          the canvas saves through. Remounted per target, so opening it from a
          type's panel starts on that type. */}
      <DataMountDialog
        key={mountFor ?? 'mount'}
        open={mountOpen}
        onClose={() => setMountOpen(false)}
        objects={mountable}
        defaultObject={mountFor ?? undefined}
        onMounted={() => { setMountOpen(false); void draft.reload() }}
      />
    </Page>
  )
}

/* --------------------------------------------------------------- panel body */

type Draft = ReturnType<typeof useOntologyDraft>

/** What a selected node *is*, plus everything hanging off it. */
function NodeDetail({ sel, draft, onEdit, onNew, onDelete, onPick, onMount, onNewPolicyFor }: {
  sel: OntologyNodeRef
  draft: Draft
  onEdit: (kind: ResourceKind, name: string) => void
  onNew: (kind: ResourceKind, forType?: string) => void
  onDelete: (kind: ResourceKind, name: string) => void
  onPick: (ref: OntologyNodeRef) => void
  onMount: (name: string) => void
  onNewPolicyFor: (action: OntologyResource) => void
}) {
  const { t } = useI18n()
  const kindOf: Record<OntologyNodeRef['kind'], ResourceKind> = {
    object: 'ObjectType', action: 'Action', function: 'Function', link: 'LinkType',
    policy: 'PolicySet', projection: 'Projection',
  }
  const res = draft.get(kindOf[sel.kind], sel.name)
  if (!res) {
    return <EmptyState bare compact title={t('ontology.gone')} />
  }

  const kind: ResourceKind = res.kind
  const isDirty = draft.touched.has(rkey(kind, res.metadata.name))
  const children = sel.kind === 'object'
    ? [
      ...draft.ofKind('Action').filter((a) => asStr(a.spec.target) === sel.name),
      ...draft.ofKind('Function').filter((f) => functionReads(f).includes(sel.name)),
    ]
    : []

  return (
    <div className="flex flex-col gap-4" data-testid={`node-detail-${sel.name}`}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={isDirty ? 'warning' : 'success'}>{isDirty ? t('ed.unsaved') : t('ed.saved')}</Badge>
        <Badge tone="neutral" mono>{res.kind}</Badge>
        <span className="ml-auto flex items-center gap-1.5">
          <Button
            size="sm"
            square
            data-testid="node-edit"
            title={t('access.edit')}
            aria-label={t('access.edit')}
            onClick={() => onEdit(kind, res.metadata.name)}
            icon={<IconPencil width={14} height={14} />}
          />
          <Button
            size="sm"
            square
            variant="subtle"
            data-testid="node-delete"
            title={t('ed.delete')}
            aria-label={t('ed.delete')}
            onClick={() => onDelete(kind, res.metadata.name)}
            icon={<IconTrash width={14} height={14} />}
            // destructive: the icon itself carries the warning colour, so a
            // mis-aimed click is visible before it is taken
            style={{ color: 'var(--tone-danger-fg)' }}
          />
        </span>
      </div>

      <dl className="flex flex-col gap-2 text-[12.5px]">
        <Row label={t('ed.display')} value={asStr(res.metadata.display) || '—'} />
        <Row label={t('ed.description')} value={asStr(res.metadata.description) || '—'} />
        {sel.kind === 'object' ? (
          <>
            <Row label={t('ed.primaryKey')} value={asStrList(res.spec.primaryKey).join(', ') || '—'} mono />
            <Row label={t('ed.properties')} value={String(Object.keys(asObj(res.spec.properties)).length)} />
          </>
        ) : null}
        {sel.kind === 'action' ? (
          <>
            <Row label={t('ed.target')} value={asStr(res.spec.target)} mono />
            <Row label={t('ed.parameters')} value={String(Object.keys(asObj(res.spec.parameters)).length)} />
            {/* The policy is shown HERE rather than as a box on the canvas: a
                policy is a property of an action ("who may run it"), so this is
                where a reader looks for it. */}
            <Row label={t('ed.policy')} value={asStr(res.spec.policy) || t('ed.defaultPolicy')} mono />
          </>
        ) : null}
        {sel.kind === 'function' ? (
          <>
            <Row label={t('ed.entry')} value={asStr(res.spec.entry)} mono />
            <Row label={t('ed.capabilities')} value={functionReads(res).join(', ') || '—'} mono />
          </>
        ) : null}
        {sel.kind === 'link' ? (
          <>
            <Row label={t('ed.source')} value={asStr(res.spec.source)} mono />
            <Row label={t('ed.target')} value={asStr(res.spec.target)} mono />
            <Row label={t('ed.cardinality')} value={t(`data.card.${asStr(res.spec.cardinality, 'ONE_TO_MANY')}`)} />
          </>
        ) : null}
        {sel.kind === 'policy' ? (
          <Row label={t('ed.cedar')} value={t('ontology.cedarLines', { n: asStr(res.spec.source).split('\n').length })} />
        ) : null}
        {sel.kind === 'projection' ? (
          <>
            <Row label={t('ed.graph')} value={asStr(res.spec.graph) || '—'} mono />
            <Row label={t('ed.includeObjects')} value={String(Object.keys(asObj(asObj(res.spec.include).objects)).length)} />
          </>
        ) : null}
      </dl>

      {/* An action owns its policy: shown, editable and creatable from here. */}
      {sel.kind === 'action' ? (
        <section data-testid="action-policy">
          <h3 className="ontogeny-label">{t('ontology.actionPolicy')}</h3>
          <ul className="flex flex-col gap-1">
            {(draft.ofKind('PolicySet').filter((p) => p.metadata.name === asStr(res.spec.policy))).map((p) => (
              <li key={p.metadata.name}>
                <button
                  type="button"
                  data-testid={`action-policy-${p.metadata.name}`}
                  onClick={() => onPick({ kind: 'policy', name: p.metadata.name })}
                  className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left transition-colors hover:bg-[var(--surface-hover)]"
                >
                  <span className="size-2 shrink-0 rounded-full" style={{ background: ATTACHED_COLOR.policy }} />
                  <span className="min-w-0 flex-1 truncate font-mono text-[12px]">{p.metadata.name}</span>
                  <Badge tone="warning">{t('ontology.node.policy')}</Badge>
                </button>
              </li>
            ))}
            {asStr(res.spec.policy) ? null : (
              <li className="px-2.5 py-1.5 text-[12px] muted">{t('ontology.noActionPolicy')}</li>
            )}
          </ul>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Button
              size="sm"
              data-testid="add-policy-for"
              icon={<IconPlus width={12} height={12} />}
              onClick={() => onNewPolicyFor(res)}
            >
              {t('ontology.newPolicy')}
            </Button>
            {draft.ofKind('PolicySet').length > 0 ? (
              <select
                className="ontogeny-input h-7 w-auto py-0 text-[12px]"
                data-testid="action-policy-pick"
                aria-label={t('ontology.attachPolicy')}
                value={asStr(res.spec.policy)}
                onChange={(e) => draft.update('Action', res.metadata.name, (r) => ({
                  ...r, spec: { ...r.spec, policy: e.target.value || undefined },
                }))}
              >
                <option value="">{t('ed.defaultPolicy')}</option>
                {draft.ofKind('PolicySet').map((p) => (
                  <option key={p.metadata.name} value={p.metadata.name}>{p.metadata.name}</option>
                ))}
              </select>
            ) : null}
          </div>
        </section>
      ) : null}

      {/* A projection is a property of a set of object types: shown on the type
          it includes, not as another box floating on the canvas. */}
      {sel.kind === 'object' ? (
        <section data-testid="object-projections">
          <h3 className="ontogeny-label">{t('ontology.typeProjections', { count: projectionsOf(draft, res.metadata.name).length })}</h3>
          {projectionsOf(draft, res.metadata.name).length === 0 ? (
            <p className="text-[12px] muted">{t('ontology.noTypeProjections')}</p>
          ) : (
            <ul className="flex flex-col gap-1">
              {projectionsOf(draft, res.metadata.name).map((p) => (
                <li key={p.metadata.name}>
                  <button
                    type="button"
                    data-testid={`type-projection-${p.metadata.name}`}
                    onClick={() => onPick({ kind: 'projection', name: p.metadata.name })}
                    className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left transition-colors hover:bg-[var(--surface-hover)]"
                  >
                    <span className="size-2 shrink-0 rounded-full" style={{ background: ATTACHED_COLOR.projection }} />
                    <span className="min-w-0 flex-1 truncate font-mono text-[12px]">{p.metadata.name}</span>
                    <Badge tone="info">{t('ontology.node.projection')}</Badge>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </section>
      ) : null}

      {sel.kind === 'object' ? (
        <section>
          <h3 className="ontogeny-label">{t('ontology.attached', { count: children.length })}</h3>
          {children.length === 0 ? (
            <p className="text-[12px] muted">{t('ontology.noAttached')}</p>
          ) : (
            <ul className="flex flex-col gap-1">
              {children.map((c) => (
                <li key={`${c.kind}/${c.metadata.name}`}>
                  <button
                    type="button"
                    data-testid={`attached-${c.metadata.name}`}
                    onClick={() => onPick({ kind: c.kind === 'Action' ? 'action' : 'function', name: c.metadata.name })}
                    className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left transition-colors hover:bg-[var(--surface-hover)]"
                  >
                    <span
                      className="size-2 shrink-0 rounded-full"
                      style={{ background: c.kind === 'Action' ? '#7c3aed' : '#0369a1' }}
                    />
                    <span className="min-w-0 flex-1 truncate font-mono text-[12px]">{c.metadata.name}</span>
                    <Badge tone={c.kind === 'Action' ? 'violet' : 'info'}>{c.kind === 'Action' ? t('ontology.node.action') : t('ontology.node.function')}</Badge>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-2 flex flex-wrap gap-1.5">
            <Button size="sm" onClick={() => onNew('Action', sel.name)} data-testid="add-action-for" icon={<IconPlus width={12} height={12} />}>
              {t('ontology.newAction')}
            </Button>
            <Button size="sm" onClick={() => onNew('Function', sel.name)} data-testid="add-function-for" icon={<IconPlus width={12} height={12} />}>
              {t('ontology.newFunction')}
            </Button>
            <Button size="sm" onClick={() => onNew('LinkType', sel.name)} data-testid="add-link-for" icon={<IconPlus width={12} height={12} />}>
              {t('ontology.newLink')}
            </Button>
            {/* attach real rows to this type: creates the store, binds backing,
                publishes and syncs in one step (see DataMountDialog) */}
            <Button
              size="sm"
              onClick={() => onMount(sel.name)}
              data-testid="mount-for"
              icon={<IconDatabase width={12} height={12} />}
            >
              {t('mount.title')}
            </Button>
          </div>
        </section>
      ) : null}
    </div>
  )
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-start gap-3">
      <dt className="w-24 shrink-0 muted">{label}</dt>
      <dd className={`min-w-0 flex-1 break-words ${mono ? 'font-mono text-[12px]' : ''}`}>{value}</dd>
    </div>
  )
}

/** The browsable index of everything, for finding a node without hunting. */
function TypeIndex({ draft, onPick, onNew }: {
  draft: Draft
  onPick: (ref: OntologyNodeRef) => void
  onNew: (kind: ResourceKind) => void
}) {
  const { t } = useI18n()
  const groups: Array<{ kind: ResourceKind; ref: (name: string) => OntologyNodeRef; label: string }> = [
    { kind: 'ObjectType', ref: (name) => ({ kind: 'object', name }), label: t('ontology.node.type') },
    { kind: 'LinkType', ref: (name) => ({ kind: 'link', name }), label: t('ontology.node.link') },
    { kind: 'Action', ref: (name) => ({ kind: 'action', name }), label: t('ontology.node.action') },
    { kind: 'Function', ref: (name) => ({ kind: 'function', name }), label: t('ontology.node.function') },
    { kind: 'PolicySet', ref: (name) => ({ kind: 'policy', name }), label: t('ontology.node.policy') },
    { kind: 'Projection', ref: (name) => ({ kind: 'projection', name }), label: t('ontology.node.projection') },
  ]
  return (
    <div className="flex flex-col gap-4" data-testid="ontology-index">
      {groups.map(({ kind, ref, label }) => {
        const items = draft.ofKind(kind)
        return (
          <section key={kind}>
            <div className="mb-1.5 flex items-center gap-2">
              <h3 className="ontogeny-label" style={{ marginBottom: 0 }}>{label}</h3>
              <Badge tone="neutral" mono>{items.length}</Badge>
              <Button
                size="sm"
                className="ml-auto"
                data-testid={`index-new-${kind}`}
                onClick={() => onNew(kind)}
                icon={<IconPlus width={12} height={12} />}
              >
                {t('ed.create')}
              </Button>
            </div>
            <ul className="flex flex-col gap-0.5">
              {items.map((r) => (
                <li key={r.metadata.name}>
                  <button
                    type="button"
                    data-testid={`index-${r.metadata.name}`}
                    onClick={() => onPick(ref(r.metadata.name))}
                    className="flex w-full items-center gap-2 rounded-lg px-2.5 py-1.5 text-left transition-colors hover:bg-[var(--surface-hover)]"
                  >
                    <span className="min-w-0 flex-1 truncate font-mono text-[12px]">{r.metadata.name}</span>
                    {r.metadata.display ? <span className="truncate text-[11px] muted">{r.metadata.display}</span> : null}
                    {draft.touched.has(rkey(kind, r.metadata.name)) ? (
                      <span className="size-1.5 shrink-0 rounded-full" style={{ background: 'var(--tone-warning-fg)' }} />
                    ) : null}
                  </button>
                </li>
              ))}
            </ul>
          </section>
        )
      })}
    </div>
  )
}

/* ------------------------------------------------------------------ helpers */

/** The projections that carry this object type.
 *
 * A projection is a property of a set of object types, so it is listed on each
 * type it includes rather than drawn as its own node on the canvas. */
function projectionsOf(draft: Draft, type: string): OntologyResource[] {
  return draft.ofKind('Projection').filter((p) => {
    const include = asObj(asObj(p.spec.include).objects)
    return Object.prototype.hasOwnProperty.call(include, type)
  })
}

/** The object types a function declares it may read. */
function functionReads(f: OntologyResource): string[] {
  const out: string[] = []
  for (const cap of Array.isArray(f.spec.capabilities) ? f.spec.capabilities : []) {
    out.push(...asStrList(asObj(cap)['read-objects']))
  }
  return out
}

/** A brand-new resource of one kind, ready to edit. */
function makeResource(kind: ResourceKind, name: string, objectNames: string[]): OntologyResource {
  switch (kind) {
    case 'ObjectType':
      return {
        apiVersion: 'ontogeny/v1', kind, metadata: { name, display: name },
        spec: { primaryKey: ['id'], properties: { id: { type: 'string', required: true } } },
      }
    case 'Action':
      return {
        apiVersion: 'ontogeny/v1', kind, metadata: { name, display: name },
        spec: { target: objectNames[0] ?? '', parameters: {}, rules: [], effects: [{ kind: 'modify-target', set: {} }] },
      }
    case 'Function':
      return {
        apiVersion: 'ontogeny/v1', kind, metadata: { name, display: name },
        spec: { runtime: 'python', entry: `${name.replace(/-/g, '_')}.py:main`, parameters: {}, capabilities: [] },
      }
    case 'LinkType':
      return {
        apiVersion: 'ontogeny/v1', kind, metadata: { name, display: name },
        spec: {
          source: objectNames[0] ?? '', target: objectNames[1] ?? objectNames[0] ?? '',
          cardinality: 'ONE_TO_MANY', join: { kind: 'foreign-key', keys: {} },
        },
      }
    default:
      return {
        apiVersion: 'ontogeny/v1', kind, metadata: { name, display: name },
        spec: { language: 'cedar', source: '// 未完成的策略：Cedar 默认拒绝\n' },
      }
  }
}

function StatChip({ label, value }: { label: string; value: number }) {
  return (
    <span
      className="inline-flex items-baseline gap-1.5 rounded-full px-2.5 py-[3px] text-[11.5px]"
      style={{ background: 'var(--surface-sunken)', color: 'var(--text-secondary)' }}
      title={`${label}: ${value}`}
    >
      <span className="muted">{label}</span>
      <span className="font-mono font-semibold tnum">{value}</span>
    </span>
  )
}

export { OBJECT_COLOR, makeResource }
