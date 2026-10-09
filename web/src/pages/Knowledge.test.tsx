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
import { fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { mockFetch, META } from '../test/setup'
import { renderWithProviders } from '../test/render'
import { Knowledge } from './Knowledge'
import { Action } from './Action'
import { OntologyDraftProvider } from './ontology/draft'

/** Two resources of each kind, so a list has something to select and the
 *  selects that point at an object type have options. */
const RESOURCES = [
  {
    apiVersion: 'ontogeny/v1', kind: 'ObjectType',
    metadata: { name: 'sales-order', display: '销售订单', description: '客户订单' },
    spec: {
      primaryKey: ['so_id'],
      properties: { so_id: { type: 'string', required: true }, qty: { type: 'integer' } },
    },
  },
  {
    apiVersion: 'ontogeny/v1', kind: 'ObjectType',
    metadata: { name: 'customer', display: '客户' },
    spec: { primaryKey: ['customer_id'], properties: { customer_id: { type: 'string', required: true } } },
  },
  {
    apiVersion: 'ontogeny/v1', kind: 'LinkType',
    metadata: { name: 'sales-order-customer', display: '订单客户' },
    spec: { source: 'sales-order', target: 'customer', cardinality: 'ONE_TO_MANY', join: { kind: 'foreign-key', keys: {} } },
  },
  {
    apiVersion: 'ontogeny/v1', kind: 'Projection',
    metadata: { name: 'supply-chain', display: '供应链图谱' },
    spec: {
      engine: 'hugegraph', endpoint: '${HUGEGRAPH_URL}', graph: 'supply_chain', graphspace: 'DEFAULT',
      include: { objects: { 'sales-order': { properties: ['qty'] } }, links: ['sales-order-customer'] },
      deletion: 'remove', indexes: [{ object: 'sales-order', property: 'qty' }],
    },
  },
  {
    apiVersion: 'ontogeny/v1', kind: 'Action',
    metadata: { name: 'confirm-sales-order', display: '确认订单' },
    spec: {
      target: 'sales-order',
      parameters: { note: { type: 'string', required: false } },
      rules: [{ expr: 'target.qty > 0', message: '数量必须为正' }],
      effects: [{ kind: 'modify-target', set: { status: '"CONFIRMED"' } }],
    },
  },
  {
    apiVersion: 'ontogeny/v1', kind: 'Function',
    metadata: { name: 'equipment-mtbf', display: '设备 MTBF' },
    spec: {
      runtime: 'python', entry: 'mtbf.py:mtbf',
      parameters: { equipment_id: { type: 'string', required: true } },
      returns: { type: 'decimal', unit: 'hours' },
      // the capability VALUE is the point: /meta/ontology only lists the name
      capabilities: [{ 'read-objects': ['work-order'] }],
      publish: { enabled: true },
    },
  },
  {
    apiVersion: 'ontogeny/v1', kind: 'PolicySet',
    metadata: { name: 'default', display: '默认策略' },
    spec: { language: 'cedar', source: 'permit(principal, action, resource);' },
  },
]

const PREVIEW = {
  objects: [
    { type: 'sales-order', display: '销售订单', primary_key: 'so_id', total: 2, rows: [{ so_id: 'SO-1', qty: 3 }] },
  ],
  total: 2,
}

const mock = (extra: Parameters<typeof mockFetch>[0] = []) => mockFetch([
  { match: '/meta/ontology', body: META },
  { match: '/admin/builder/resources', body: { resources: RESOURCES, content_hash: 'hash123456789' } },
  { match: '/data/preview', body: PREVIEW },
  { match: '/graph/projection', body: { configured: false, ok: false, labels: { vertices: [], edges: [] } } },
  ...extra,
])

// the provider lives above the router in the real app, so the pages share one
// draft; in a page test it has to be supplied explicitly
const renderKnowledge = (path = '/knowledge') =>
  renderWithProviders(
    <OntologyDraftProvider><Knowledge /></OntologyDraftProvider>,
    { path, route: '/knowledge' },
  )
const renderAction = (path = '/action') =>
  renderWithProviders(
    <OntologyDraftProvider><Action /></OntologyDraftProvider>,
    { path, route: '/action' },
  )

describe('Knowledge — the semantic layer', () => {
  it('splits the ontology into objects / links / projections and seeds from the raw resources', async () => {
    mock()
    renderKnowledge()

    // the object list, from the lossless resource endpoint (not the meta view)
    await waitFor(() => expect(screen.getByTestId('ObjectType-item-sales-order')).toBeInTheDocument())
    expect(screen.getByTestId('ObjectType-item-customer')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('tab-links'))
    await waitFor(() => expect(screen.getByTestId('LinkType-item-sales-order-customer')).toBeInTheDocument())

    fireEvent.click(screen.getByTestId('tab-projections'))
    await waitFor(() => expect(screen.getByTestId('Projection-item-supply-chain')).toBeInTheDocument())
  })

  it('edits an object type and shows the live sample rows beside the form', async () => {
    mock()
    renderKnowledge()
    await waitFor(() => expect(screen.getByTestId('ObjectType-item-sales-order')).toBeInTheDocument())

    // the sample rows come from the normal query path, under the editor
    fireEvent.click(screen.getByTestId('ObjectType-item-sales-order'))
    await waitFor(() => expect(screen.getByText('SO-1')).toBeInTheDocument())
    // the model side is editable in place
    const display = await screen.findByDisplayValue('销售订单')
    fireEvent.change(display, { target: { value: '销售订单（改）' } })

    await waitFor(() => expect(screen.getByTestId('ed-dirty-badge').textContent).toMatch(/unsaved/i))
    expect(screen.getByTestId('ed-save')).toBeEnabled()
  })

  it('renaming an object type cascades to the links that reference it', async () => {
    const { calls } = mock([{ match: '/admin/builder/save', body: { published: true, content_hash: 'newhash', written: [], removed: [], issues: [] } }])
    renderKnowledge()
    await waitFor(() => expect(screen.getByTestId('ObjectType-item-sales-order')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('ObjectType-item-sales-order'))

    const name = await screen.findByDisplayValue('sales-order')
    fireEvent.change(name, { target: { value: 'order' } })
    await waitFor(() => expect(screen.getByTestId('ed-dirty-badge').textContent).toMatch(/unsaved/i))

    fireEvent.click(screen.getByTestId('ed-save'))
    await waitFor(() => expect(calls.some((c) => c.url.includes('/admin/builder/save'))).toBe(true))

    const body = JSON.parse(String(calls.find((c) => c.url.includes('/admin/builder/save'))!.init?.body))
    const written = body.resources as Array<{ kind: string; metadata: { name: string }; spec: Record<string, unknown> }>
    // everything that pointed at the old name comes along: the link's endpoint,
    // the action's target and the projection's include + index
    expect(written.map((r) => `${r.kind}/${r.metadata.name}`).sort()).toEqual([
      'Action/confirm-sales-order', 'LinkType/sales-order-customer',
      'ObjectType/order', 'Projection/supply-chain',
    ])
    expect(written.find((r) => r.kind === 'LinkType')!.spec.source).toBe('order')
    expect(written.find((r) => r.kind === 'Action')!.spec.target).toBe('order')
    expect(Object.keys((written.find((r) => r.kind === 'Projection')!.spec.include as { objects: object }).objects))
      .toEqual(['order'])
    // the old file is deleted, so the rename does not leave a duplicate behind
    expect(body.deletes).toContain('ObjectType/sales-order')
  })
})

describe('Action — the kinetic layer', () => {
  it('splits the ontology into actions / functions / policies', async () => {
    mock()
    renderAction()

    await waitFor(() => expect(screen.getByTestId('Action-item-confirm-sales-order')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('tab-functions'))
    await waitFor(() => expect(screen.getByTestId('Function-item-equipment-mtbf')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('tab-policies'))
    await waitFor(() => expect(screen.getByTestId('PolicySet-item-default')).toBeInTheDocument())
  })

  it('edits a function capability VALUE, which the meta snapshot cannot even express', async () => {
    mock()
    renderAction('/action?tab=functions')
    await waitFor(() => expect(screen.getByTestId('Function-item-equipment-mtbf')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('Function-item-equipment-mtbf'))

    // the capability is seeded with its value (work-order), not just its name
    const capValue = await screen.findByDisplayValue('work-order')
    fireEvent.change(capValue, { target: { value: 'work-order, part' } })

    await waitFor(() => expect(screen.getByTestId('ed-dirty-badge').textContent).toMatch(/unsaved/i))
  })

  it('edits the Cedar source of a policy set', async () => {
    mock()
    renderAction('/action?tab=policies')
    await waitFor(() => expect(screen.getByTestId('PolicySet-item-default')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('PolicySet-item-default'))

    const source = await screen.findByTestId('policy-source')
    expect(source).toHaveValue('permit(principal, action, resource);')
    fireEvent.change(source, { target: { value: 'permit(principal, action, resource) when { principal.Role.contains("planner") };' } })
    await waitFor(() => expect(screen.getByTestId('ed-dirty-badge').textContent).toMatch(/unsaved/i))
  })

  it('sends only the touched resource on save', async () => {
    const { calls } = mock([{ match: '/admin/builder/save', body: { published: true, content_hash: 'h2', written: ['Action/confirm-sales-order'], removed: [], issues: [] } }])
    renderAction()
    await waitFor(() => expect(screen.getByTestId('Action-item-confirm-sales-order')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('Action-item-confirm-sales-order'))

    const display = await screen.findByDisplayValue('确认订单')
    fireEvent.change(display, { target: { value: '确认订单（改）' } })
    fireEvent.click(screen.getByTestId('ed-save'))

    await waitFor(() => expect(calls.some((c) => c.url.includes('/admin/builder/save'))).toBe(true))
    const body = JSON.parse(String(calls.find((c) => c.url.includes('/admin/builder/save'))!.init?.body))
    // partial save: untouched YAML on disk is never rewritten
    expect(body.resources.map((r: { kind: string }) => r.kind)).toEqual(['Action'])
    expect(body.deletes).toEqual([])
  })

  it('creates a new resource from the list toolbar', async () => {
    mock()
    renderAction('/action?tab=policies')
    await waitFor(() => expect(screen.getByTestId('PolicySet-item-default')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('PolicySet-create'))
    await waitFor(() => expect(screen.getByTestId('PolicySet-item-new-policy')).toBeInTheDocument())
    // a brand-new policy permits nothing: Cedar denies by default
    const source = await screen.findByTestId('policy-source')
    expect(String((source as HTMLTextAreaElement).value)).not.toContain('permit(')
  })

  it('deletes a resource only after the confirmation', async () => {
    mock()
    renderAction('/action?tab=functions')
    await waitFor(() => expect(screen.getByTestId('Function-item-equipment-mtbf')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('Function-item-equipment-mtbf'))
    await waitFor(() => expect(screen.getByTestId('Function-delete')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('Function-delete'))
    await waitFor(() => expect(screen.getByTestId('confirm-dialog')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('confirm-accept'))
    await waitFor(() => expect(screen.queryByTestId('Function-item-equipment-mtbf')).not.toBeInTheDocument())
    expect(within(screen.getByTestId('ed-dirty-badge')).getByText(/unsaved/i)).toBeInTheDocument()
  })
})
