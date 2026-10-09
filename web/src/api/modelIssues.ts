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
 * Client-side model checks, run before a save leaves the browser.
 *
 * These are NOT a re-implementation of the server's validator — that one is
 * authoritative and its verdict is what lands in the save report. They are the
 * subset that can be decided from the resources alone and that the server would
 * otherwise report as a failed publish after a round trip: a name that is not
 * kebab-case, a duplicate, a link pointing at an object type that does not
 * exist, an action whose target is missing. Saying it on the canvas, while the
 * offending node is one click away, is the difference between a modelling tool
 * and a form that bounces.
 *
 * Every issue carries the resource it belongs to, so the page can show the
 * count in the toolbar and mark the node — not just print a wall of text.
 */
import { asList, asObj, asStr, rkey, type ResourceKind } from './resources'
import type { OntologyResource } from './types'

export interface ModelIssue {
  /** `Kind/name` — matches the draft's touched keys. */
  key: string
  kind: ResourceKind
  name: string
  /** i18n key; the page renders `t(issue.message, issue.params)`. */
  message: string
  params?: Record<string, string | number>
  severity: 'error' | 'warning'
}

const NAME_RE = /^[a-z][a-z0-9-]*$/

/** Object-type names a function declares it may read. */
function functionReads(res: OntologyResource): string[] {
  const out: string[] = []
  for (const cap of asList(res.spec.capabilities)) {
    for (const ty of asList(asObj(cap)['read-objects'])) {
      if (typeof ty === 'string') out.push(ty)
    }
  }
  return out
}

/** Every problem the model can be caught with locally, in canvas order. */
export function modelIssues(resources: OntologyResource[]): ModelIssue[] {
  const issues: ModelIssue[] = []
  const objectNames = new Set(resources.filter((r) => r.kind === 'ObjectType').map((r) => r.metadata.name))
  const seen = new Set<string>()

  for (const r of resources) {
    const { kind, name } = { kind: r.kind, name: r.metadata.name }
    const key = rkey(kind, name)
    const add = (message: string, severity: ModelIssue['severity'] = 'error', params?: ModelIssue['params']) =>
      issues.push({ key, kind, name, message, severity, params })

    if (!NAME_RE.test(name)) add('model.issue.name', 'error', { name })
    if (seen.has(key)) add('model.issue.dup', 'error', { name })
    seen.add(key)

    if (kind === 'ObjectType') {
      const props = Object.keys(asObj(r.spec.properties))
      const pk = asList(r.spec.primaryKey).filter((x): x is string => typeof x === 'string')
      if (props.length === 0) add('model.issue.props', 'error', { name })
      if (pk.length === 0) add('model.issue.pkEmpty', 'error', { name })
      else for (const k of pk) {
        if (!props.includes(k)) add('model.issue.pk', 'error', { name, key: k })
      }
    }

    if (kind === 'LinkType') {
      for (const end of ['source', 'target'] as const) {
        const ty = asStr(r.spec[end])
        if (!objectNames.has(ty)) add('model.issue.linkEnd', 'error', { name, end, type: ty || '—' })
      }
      if (asStr(r.spec.source) && asStr(r.spec.source) === asStr(r.spec.target)) {
        add('model.issue.selfLink', 'warning', { name })
      }
    }

    if (kind === 'Action') {
      const target = asStr(r.spec.target)
      if (!objectNames.has(target)) add('model.issue.target', 'error', { name, target: target || '—' })
      // An action may declare its effect plan statically (`effects`) OR compute
      // it at run time (`execution: {kind: function, entry}`). Only an action
      // with NEITHER is a no-op; flagging the function-executed form was a
      // false positive on the demo package's `raise-maintenance-order`.
      const effects = asList(r.spec.effects)
      const executed = asStr(asObj(r.spec.execution).kind) === 'function'
      if (effects.length === 0 && !executed) add('model.issue.effects', 'warning', { name })
      // a modify-target that sets nothing is a no-op action: almost always a
      // half-finished edit rather than an intent
      for (const eff of effects) {
        const e = asObj(eff)
        if (asStr(e.kind) === 'modify-target' && Object.keys(asObj(e.set)).length === 0) {
          add('model.issue.emptyEffect', 'warning', { name })
        }
      }
    }

    if (kind === 'Function') {
      // Mirrors the server rule (core/validator.py): a code function needs its
      // `file.py:function` entry, while a DECLARATIVE function (prompt / webhook
      // / pipeline) has no file at all — requiring an entry there flagged the
      // demo package's prompt and webhook functions as broken.
      const runtime = asStr(r.spec.runtime, 'python')
      if (runtime === 'python') {
        if (!asStr(r.spec.entry)) add('model.issue.entry', 'error', { name })
      } else if (runtime === 'declarative') {
        if (asStr(r.spec.entry)) add('model.issue.entryDeclarative', 'error', { name })
        if (asList(r.spec.steps).length === 0) add('model.issue.steps', 'error', { name })
      }
      for (const ty of functionReads(r)) {
        if (!objectNames.has(ty)) add('model.issue.capability', 'error', { name, type: ty })
      }
    }

    if (kind === 'PolicySet' && !asStr(r.spec.source).trim()) {
      add('model.issue.cedarEmpty', 'warning', { name })
    }
  }

  return issues
}
