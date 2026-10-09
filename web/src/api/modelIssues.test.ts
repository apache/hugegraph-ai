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
/** Client-side model checks: the rules that must mirror the server's.
 *
 * The one that matters here is the function-entry rule. The server
 * (core/validator.py) requires an `entry` for `runtime: python` and *forbids*
 * one for `runtime: declarative` (a prompt/webhook/pipeline function has no
 * file). This module used to demand an entry from every function, so the demo
 * package's prompt and webhook functions were reported as errors on the canvas
 * — a false alarm on a perfectly valid model.
 */
import { describe, expect, it } from 'vitest'
import { modelIssues } from './modelIssues'
import type { OntologyResource } from './types'

const obj = (name: string): OntologyResource => ({
  apiVersion: 'ontogeny/v1', kind: 'ObjectType',
  metadata: { name, display: name },
  spec: { primaryKey: ['id'], properties: { id: { type: 'string', required: true } } },
})

const fn = (name: string, spec: Record<string, unknown>): OntologyResource => ({
  apiVersion: 'ontogeny/v1', kind: 'Function',
  metadata: { name, display: name },
  spec,
})

describe('function entry rule', () => {
  it('flags a python function with no entry', () => {
    const issues = modelIssues([fn('oee', { runtime: 'python' })])
    expect(issues.map((i) => i.message)).toContain('model.issue.entry')
  })

  it('accepts a python function with an entry', () => {
    const issues = modelIssues([fn('oee', { runtime: 'python', entry: 'oee.py:compute' })])
    expect(issues).toEqual([])
  })

  it('accepts a declarative function: no entry, steps declared', () => {
    // the demo's prompt + webhook functions are exactly this shape
    const issues = modelIssues([
      fn('equipment-diagnosis-prompt', { runtime: 'declarative', steps: [{ prompt: 'x' }] }),
      fn('notify-maintenance-webhook', { runtime: 'declarative', steps: [{ http: 'y' }] }),
    ])
    expect(issues).toEqual([])
  })

  it('flags a declarative function that declares an entry', () => {
    const issues = modelIssues([
      fn('prompt-fn', { runtime: 'declarative', entry: 'x.py:main', steps: [{ prompt: 'x' }] }),
    ])
    expect(issues.map((i) => i.message)).toContain('model.issue.entryDeclarative')
  })

  it('flags a declarative function with no steps', () => {
    const issues = modelIssues([fn('prompt-fn', { runtime: 'declarative' })])
    expect(issues.map((i) => i.message)).toContain('model.issue.steps')
  })

  it('still flags a capability naming an object type that does not exist', () => {
    const issues = modelIssues([
      obj('equipment'),
      fn('oee', { runtime: 'python', entry: 'oee.py:compute', capabilities: [{ 'read-objects': ['machine'] }] }),
    ])
    expect(issues.map((i) => i.message)).toContain('model.issue.capability')
  })
})
