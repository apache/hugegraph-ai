/*
Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements.  See the NOTICE file
distributed with this work for additional information
regarding copyright ownership.  The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License.  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and limitations
under the License.
*/
/** One document workspace: inventory, task review, and the confirm gate. */
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { mockFetch } from '../test/setup'
import { renderWithProviders } from '../test/render'
import { AuthProvider } from '../api/auth'
import { Documents } from './Documents'

const STORES = {
  extractor: 'loaded',
  stores: [{
    name: 'supplier-docs', display: 'Supplier documents', description: null,
    connection: 'data/docs', documents: 2, removed: 0,
    object_types: ['supplier-note'], pending: 0, last_run: null,
  }],
}

const DOCS = {
  store: 'supplier-docs',
  documents: [
    {
      id: 'd1', path: '/pkg/data/docs/acme.md', name: 'acme.md', media_type: 'text/markdown',
      size: 120, status: 'active', chunk_count: 1, error: null,
      first_seen_at: null, last_seen_at: null, extracted_at: null,
    },
    {
      id: 'd2', path: '/pkg/data/docs/api.md', name: 'api.md', media_type: 'text/markdown',
      size: 80, status: 'active', chunk_count: 0, error: null,
      first_seen_at: null, last_seen_at: null, extracted_at: null,
    },
  ],
}

const TASK = {
  id: 1, store: 'supplier-docs', doc_id: 'd1', name: 'acme.md', path: '/pkg/data/docs/acme.md',
  status: 'review', revision: 1, supersedes_task_id: null,
  scope: { objects: { 'supplier-note': ['supplier_name', 'risk_level'] }, links: ['supplier-risk-note'] },
  schema_hash: 's', skill: { name: 'graph-extract', version: 1 }, skill_hash: 'k',
  current_attempt_id: 3, confirmed_attempt_id: null, created_by: 'tester', created_at: null,
  confirmed_by: null, confirmed_at: null, graph_sync_status: 'not_applied', confirm_summary: null, error: null,
}

const TASK_DETAIL = {
  ...TASK,
  chunks: [{ index: 0, text: 'Supplier: Acme Components\nRisk level: HIGH', graph: { vertices: [], edges: [] }, issues: [], status: 'final' }],
  attempt: {
    id: 3, task_id: 1, attempt_no: 1, status: 'review', agent_run_id: 9, provider: 'task', model: null,
    schema_hash: 's', prompt_hash: 'p',
    chunks: [{ index: 0, text: 'Supplier: Acme Components\nRisk level: HIGH', graph: { vertices: [], edges: [] }, issues: [], status: 'final' }],
    issues: [],
    validation: { blockers: [], warnings: [], objects: 1, links: 1, references: [], gaps: [] },
    error: null, started_at: null, finished_at: null,
    graph: {
      vertices: [{ id: 'n1', label: 'supplier-note', properties: { supplier_name: 'Acme Components', risk_level: 'HIGH' } }],
      edges: [],
    },
    raw_graph: {
      vertices: [{ id: 'n1', label: 'supplier-note', properties: { supplier_name: 'Acme Components', risk_level: 'HIGH' } }],
      edges: [],
    },
  },
  attempts: [],
}

const SCHEMA = {
  store: 'supplier-docs',
  objects: [{
    name: 'supplier-note', display: 'Supplier risk note', description: null,
    identity: ['supplier_name'],
    properties: [
      { name: 'supplier_name', display: 'Supplier', type: 'string', required: true, identity: true, owner: 'document' },
      { name: 'risk_level', display: 'Risk level', type: 'enum', required: false, identity: false, owner: 'document' },
    ],
  }],
  links: [{ name: 'supplier-risk-note', display: 'Has risk note', source: 'supplier', target: 'supplier-note', source_is_reference: true }],
}

const SKILLS = { skills: [{ id: 'graph-extract', name: 'graph-extract', display: 'Graph extract', version: 1, body: '', examples: [] }] }

const render = () =>
  renderWithProviders(
    <AuthProvider>
      <Documents />
    </AuthProvider>,
    { path: '/documents', route: '/documents' },
  )

function routes() {
  return [
    { match: '/auth/me', body: { principal: { id: 'doc-admin', is_admin: true }, dev_auth: true } },
    { match: '/admin/documents/stores', body: STORES },
    { match: '/admin/documents/tasks/1/confirm', body: { summary: { inserted: 1 }, task: { ...TASK_DETAIL, status: 'confirmed' }, already: false } },
    { match: '/admin/documents/tasks/1/config', body: { ...TASK_DETAIL, status: 'draft', current_attempt_id: null, attempt: null } },
    { match: '/admin/documents/tasks/1', body: TASK_DETAIL },
    { match: '/admin/documents/tasks?store=', body: { tasks: [TASK] } },
    { match: '/admin/documents/tasks', body: { tasks: [TASK] } },
    { match: '/admin/documents/schema', body: SCHEMA },
    { match: '/admin/documents/skills', body: SKILLS },
    { match: '/admin/documents?store=', body: DOCS },
    { match: '/admin/documents', body: DOCS },
    { match: '/api/v1/admin/documents/tasks', body: { tasks: [TASK], written: [], schema_hash: 's' } },
  ]
}

describe('Document intelligence workspace', () => {
  it('offers a one-click default source when the package has none', async () => {
    const m = mockFetch([
      { match: '/auth/me', body: { principal: { id: 'doc-admin', is_admin: true }, dev_auth: true } },
      { match: '/admin/documents/stores', body: { extractor: 'loaded', stores: [] } },
      { match: '/admin/documents/default', body: { created: true, store: 'documents', object_type: 'document-note' } },
    ])
    render()
    fireEvent.click(await screen.findByTestId('documents-create-default'))
    await waitFor(() => {
      expect(m.calls.some((c) => c.url.includes('/admin/documents/default'))).toBe(true)
    })
  })

  it('shows every source and its task state in one workspace', async () => {
    mockFetch(routes())
    render()
    expect(await screen.findByText('acme.md')).toBeInTheDocument()
    expect(screen.getByText('api.md')).toBeInTheDocument()
    expect(screen.getByText('review')).toBeInTheDocument()
    expect(screen.getByText('No task')).toBeInTheDocument()
    // no tabs: the page is one workspace
    expect(screen.queryByTestId('tab-corpus')).toBeNull()
    expect(screen.queryByTestId('tab-runs')).toBeNull()
  })

  it('creates a task directly from a source without re-uploading it', async () => {
    const m = mockFetch(routes())
    render()
    fireEvent.click(await screen.findByTestId('documents-doc-d2'))
    fireEvent.click(await screen.findByTestId('documents-doc-create-task'))
    expect(await screen.findByTestId('documents-task-dialog')).toBeInTheDocument()
    await waitFor(() => {
      expect((screen.getByTestId('documents-task-existing-d2') as HTMLInputElement).checked).toBe(true)
      expect((screen.getByTestId('documents-task-prop-supplier-note-risk_level') as HTMLInputElement).checked).toBe(true)
    })
    fireEvent.click(screen.getByTestId('documents-task-create'))
    await waitFor(() => {
      const call = m.calls.find((c) => c.url.includes('/admin/documents/tasks') && c.init?.method === 'POST')
      expect(call).toBeTruthy()
      expect(JSON.parse(String(call!.init!.body))).toMatchObject({ doc_ids: ['d2'], files: [] })
    })
  })

  it('opens a defined task config and saves a changed scope', async () => {
    const m = mockFetch(routes())
    render()
    fireEvent.click(await screen.findByTestId('documents-task-1'))
    fireEvent.click(await screen.findByTestId('documents-task-config'))
    expect(await screen.findByTestId('documents-task-config-dialog')).toBeInTheDocument()
    await waitFor(() => {
      expect((screen.getByTestId('documents-task-config-prop-supplier-note-risk_level') as HTMLInputElement).checked).toBe(true)
    })
    fireEvent.click(screen.getByTestId('documents-task-config-save'))
    await waitFor(() => {
      expect(m.calls.some((c) => c.url.includes('/tasks/1/config') && c.init?.method === 'PATCH')).toBe(true)
    })
  })

  it('reviews a task, switches graph/json, and confirms explicitly', async () => {
    const m = mockFetch(routes())
    render()
    fireEvent.click(await screen.findByTestId('documents-task-1'))
    expect(await screen.findByTestId('documents-task-extraction')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('documents-task-extraction-json'))
    expect(await screen.findByTestId('documents-task-extraction-json-editor')).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('documents-task-extraction-graph'))
    fireEvent.click(screen.getByTestId('documents-task-confirm'))
    await waitFor(() => {
      expect(m.calls.some((c) => c.url.includes('/tasks/1/confirm'))).toBe(true)
    })
  })
})
