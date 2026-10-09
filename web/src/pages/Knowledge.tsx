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
 * Knowledge — the semantic layer, editable.
 *
 * The object types (with their live sample rows), the links that connect them,
 * and the graph projection derived from them. Split out of the old single
 * "data preview" page because these three answer one question — *what is in the
 * ontology and what does it contain* — while actions, functions and policy sets
 * answer a different one (what may happen), and the two halves are edited by
 * different people for different reasons.
 *
 * Every resource here is editable in place: the tab strips are the model's own
 * three semantic resources, and the save bar publishes whatever is dirty.
 */
import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useI18n } from '../i18n'
import { Badge, Button, Page, Tabs } from '../components/ui'
import { ResourceWorkbench } from '../components/ResourceWorkbench'
import { ProjectionView } from './ProjectionView'
import { ObjectTypeEditor, LinkTypeEditor, ProjectionEditor } from './ontology/editors'
import { useOntologyDraft } from './ontology/draft'
import { SampleRows } from './ontology/SampleRows'
import { asObj, asStr } from '../api/resources'
import { useMeta } from '../api/queries'
import { ObjectsOverview } from './ObjectsOverview'
import { ObjectsDialog } from '../components/ObjectsDialog'
import { DataOverviewDialog } from '../components/DataOverviewDialog'
import { IconTable } from '../components/icons'
import type { OntologyResource } from '../api/types'

type Tab = 'objects' | 'links' | 'projections'

const TABS: Tab[] = ['objects', 'links', 'projections']

export function Knowledge() {
  const { t } = useI18n()
  const { stores } = useOntologyDraft()
  const draft = useOntologyDraft()
  const [params, setParams] = useSearchParams()
  const raw = params.get('tab')
  const tab: Tab = TABS.includes(raw as Tab) ? (raw as Tab) : 'objects'
  const setTab = (next: Tab) => setParams(next === 'objects' ? {} : { tab: next }, { replace: true })

  useEffect(() => draft.ensureLoaded(), [draft])

  const objects = draft.ofKind('ObjectType')
  const links = draft.ofKind('LinkType')
  const projections = draft.ofKind('Projection')
  // "all types and their rows at a glance" is a *view* of this page, not a page
  // of its own: it used to be /data, which duplicated the model that lives here
  const meta = useMeta()
  const [overviewOpen, setOverviewOpen] = useState(false)
  const [browseType, setBrowseType] = useState<string | null>(null)

  const tabs = (
    <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
    <Tabs<Tab>
      tabs={[
        { id: 'objects', label: t('data.tab.objects'), count: objects.length, hint: t('knowledge.objectsHint') },
        { id: 'links', label: t('data.tab.links'), count: links.length, hint: t('knowledge.linksHint') },
        { id: 'projections', label: t('data.tab.projections'), count: projections.length, hint: t('knowledge.projectionsHint') },
      ]}
      value={tab}
      onChange={setTab}
    />
    <Badge tone="brand">{t('knowledge.badge')}</Badge>
    <Button
      size="sm"
      className="ml-auto"
      data-testid="data-overview-open"
      onClick={() => setOverviewOpen(true)}
      icon={<IconTable width={13} height={13} />}
    >
      {t('knowledge.overview')}
    </Button>
    </div>
  )

  return (
    <Page fill testId="knowledge">
      <h1 className="sr-only">{t('knowledge.title')}</h1>

      {tab === 'objects' ? (
        <ResourceWorkbench
          kind="ObjectType"
          tabs={tabs}
          hint={t('knowledge.objectsHint')}
          makeNew={(name) => newObject(name)}
          renderEditor={(r) => (
            <ObjectTypeEditor
              resource={r}
              update={(next) => draft.update('ObjectType', r.metadata.name, next)}
              rename={(to) => draft.rename('ObjectType', r.metadata.name, to)}
              objectNames={draft.objectNames}
              policyNames={[]}
              stores={stores}
            />
          )}
          renderRowExtra={(r) => (
            <span className="text-[11px] muted tnum">
              {t('ed.propCount', { count: Object.keys(asObj(r.spec.properties)).length })}
            </span>
          )}
          renderBelow={(r) => <SampleRows type={r.metadata.name} />}
        />
      ) : null}

      {tab === 'links' ? (
        <ResourceWorkbench
          kind="LinkType"
          tabs={tabs}
          hint={t('knowledge.linksHint')}
          makeNew={(name, objectNames) => newLink(name, objectNames)}
          renderEditor={(r) => (
            <LinkTypeEditor
              resource={r}
              update={(next) => draft.update('LinkType', r.metadata.name, next)}
              rename={(to) => draft.rename('LinkType', r.metadata.name, to)}
              objectNames={draft.objectNames}
              policyNames={[]}
            />
          )}
          renderRowExtra={(r) => (
            <span className="truncate font-mono text-[10.5px] muted">
              {asStr(r.spec.source)} → {asStr(r.spec.target)}
            </span>
          )}
        />
      ) : null}

      {tab === 'projections' ? (
        <ResourceWorkbench
          kind="Projection"
          tabs={tabs}
          hint={t('knowledge.projectionsHint')}
          makeNew={(name) => newProjection(name)}
          renderEditor={(r) => (
            <ProjectionEditor
              resource={r}
              update={(next) => draft.update('Projection', r.metadata.name, next)}
              rename={(to) => draft.rename('Projection', r.metadata.name, to)}
              objectNames={draft.objectNames}
              policyNames={[]}
            />
          )}
          renderRowExtra={(r) => (
            <span className="truncate font-mono text-[10.5px] muted">
              {asStr(r.spec.graph)} · {Object.keys(asObj(asObj(r.spec.include).objects)).length}
            </span>
          )}
          renderBelow={() => <ProjectionView />}
        />
      ) : null}

      <DataOverviewDialog open={overviewOpen} onClose={() => setOverviewOpen(false)}>
        <ObjectsOverview meta={meta.data} onOpenBrowser={(ty) => setBrowseType(ty)} />
      </DataOverviewDialog>
      <ObjectsDialog type={browseType} onClose={() => setBrowseType(null)} />
    </Page>
  )
}

/* --------------------------------------------------------- fresh resources */

const newObject = (name: string): OntologyResource => ({
  apiVersion: 'ontogeny/v1',
  kind: 'ObjectType',
  metadata: { name, display: name },
  spec: { primaryKey: ['id'], properties: { id: { type: 'string', required: true } } },
})

const newLink = (name: string, objectNames: string[]): OntologyResource => ({
  apiVersion: 'ontogeny/v1',
  kind: 'LinkType',
  metadata: { name, display: name },
  spec: {
    source: objectNames[0] ?? '',
    target: objectNames[1] ?? objectNames[0] ?? '',
    cardinality: 'ONE_TO_MANY',
    join: { kind: 'foreign-key', keys: {} },
  },
})

const newProjection = (name: string): OntologyResource => ({
  apiVersion: 'ontogeny/v1',
  kind: 'Projection',
  metadata: { name, display: name },
  spec: {
    engine: 'hugegraph',
    endpoint: '${HUGEGRAPH_URL}',
    graph: name.replace(/-/g, '_'),
    graphspace: 'DEFAULT',
    api: 'auto',
    include: { objects: {}, links: [] },
    deletion: 'remove',
    indexes: [],
  },
})
