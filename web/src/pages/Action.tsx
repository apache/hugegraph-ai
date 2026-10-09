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
 * Action — the kinetic layer, editable.
 *
 * The verbs of the ontology: the actions that may change state, the functions
 * that compute across objects, and the Cedar policy sets that decide who may do
 * either. Split from Knowledge because the two halves are different work — one
 * describes what exists, the other what is allowed to happen — and because a
 * policy reviewer should not have to scroll past fifteen data tables.
 */
import { useEffect } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useI18n } from '../i18n'
import { Badge, Page, Tabs } from '../components/ui'
import { ResourceWorkbench } from '../components/ResourceWorkbench'
import { ActionEditor, FunctionEditor, PolicySetEditor } from './ontology/editors'
import { useOntologyDraft } from './ontology/draft'
import { asStr } from '../api/resources'
import type { OntologyResource } from '../api/types'

type Tab = 'actions' | 'functions' | 'policies'

const TABS: Tab[] = ['actions', 'functions', 'policies']

export function Action() {
  const { t } = useI18n()
  const draft = useOntologyDraft()
  const [params, setParams] = useSearchParams()
  const raw = params.get('tab')
  const tab: Tab = TABS.includes(raw as Tab) ? (raw as Tab) : 'actions'
  const setTab = (next: Tab) => setParams(next === 'actions' ? {} : { tab: next }, { replace: true })

  useEffect(() => draft.ensureLoaded(), [draft])

  const actions = draft.ofKind('Action')
  const functions = draft.ofKind('Function')
  const policies = draft.ofKind('PolicySet')
  const policyNames = policies.map((p) => p.metadata.name)

  const tabs = (
    <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-2">
    <Tabs<Tab>
      tabs={[
        { id: 'actions', label: t('data.tab.actions'), count: actions.length, hint: t('action.actionsHint') },
        { id: 'functions', label: t('data.tab.functions'), count: functions.length, hint: t('action.functionsHint') },
        { id: 'policies', label: t('data.tab.policies'), count: policies.length, hint: t('action.policiesHint') },
      ]}
      value={tab}
      onChange={setTab}
    />
    <Badge tone="violet">{t('action.badge')}</Badge>
    </div>
  )

  return (
    <Page fill testId="action">
      <h1 className="sr-only">{t('action.title')}</h1>

      {tab === 'actions' ? (
        <ResourceWorkbench
          kind="Action"
          tabs={tabs}
          hint={t('action.actionsHint')}
          makeNew={(name, objectNames) => newAction(name, objectNames[0] ?? '')}
          renderEditor={(r) => (
            <ActionEditor
              resource={r}
              update={(next) => draft.update('Action', r.metadata.name, next)}
              rename={(to) => draft.rename('Action', r.metadata.name, to)}
              objectNames={draft.objectNames}
              policyNames={policyNames}
              linkNames={draft.ofKind('LinkType').map((l) => l.metadata.name)}
            />
          )}
          renderRowExtra={(r) => (
            <span className="truncate font-mono text-[10.5px] muted">{asStr(r.spec.target)}</span>
          )}
        />
      ) : null}

      {tab === 'functions' ? (
        <ResourceWorkbench
          kind="Function"
          tabs={tabs}
          hint={t('action.functionsHint')}
          makeNew={(name) => newFunction(name)}
          renderEditor={(r) => (
            <FunctionEditor
              resource={r}
              update={(next) => draft.update('Function', r.metadata.name, next)}
              rename={(to) => draft.rename('Function', r.metadata.name, to)}
              objectNames={draft.objectNames}
              policyNames={policyNames}
            />
          )}
          renderRowExtra={(r) => (
            <span className="truncate font-mono text-[10.5px] muted">{asStr(r.spec.entry)}</span>
          )}
        />
      ) : null}

      {tab === 'policies' ? (
        <ResourceWorkbench
          kind="PolicySet"
          tabs={tabs}
          hint={t('action.policiesHint')}
          makeNew={(name) => newPolicy(name)}
          renderEditor={(r) => (
            <PolicySetEditor
              resource={r}
              update={(next) => draft.update('PolicySet', r.metadata.name, next)}
              rename={(to) => draft.rename('PolicySet', r.metadata.name, to)}
              objectNames={draft.objectNames}
              policyNames={policyNames}
            />
          )}
        />
      ) : null}
    </Page>
  )
}

/* --------------------------------------------------------- fresh resources */

const newAction = (name: string, target: string): OntologyResource => ({
  apiVersion: 'ontogeny/v1',
  kind: 'Action',
  metadata: { name, display: name },
  spec: { target, parameters: {}, rules: [], effects: [{ kind: 'modify-target', set: {} }] },
})

const newFunction = (name: string): OntologyResource => ({
  apiVersion: 'ontogeny/v1',
  kind: 'Function',
  metadata: { name, display: name },
  spec: { runtime: 'python', entry: `${name.replace(/-/g, '_')}.py:main`, parameters: {}, capabilities: [] },
})

const newPolicy = (name: string): OntologyResource => ({
  apiVersion: 'ontogeny/v1',
  kind: 'PolicySet',
  metadata: { name, display: name },
  // a policy that permits nothing is the safe starting point: Cedar denies by
  // default, so an unfinished draft can never widen anyone's access
  spec: { language: 'cedar', source: '// 未完成的策略：Cedar 默认拒绝，此处不会放行任何请求\n' },
})
