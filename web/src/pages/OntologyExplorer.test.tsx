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
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { QueryClient } from '@tanstack/react-query'
import { mockFetch, META } from '../test/setup'
import { renderWithProviders } from '../test/render'
import { OntologyExplorer } from './OntologyExplorer'
import { OntologyDraftProvider } from './ontology/draft'

/** The editors hold the compiled resources verbatim, so the page needs the raw
 *  endpoint — the lossy `/meta` snapshot cannot express an action's effect or a
 *  function's capability values. */
const RESOURCES = [
  {
    apiVersion: 'ontogeny/v1', kind: 'ObjectType',
    metadata: { name: 'sales-order', display: '销售订单' },
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
    apiVersion: 'ontogeny/v1', kind: 'Action',
    metadata: { name: 'confirm-sales-order', display: '确认订单' },
    spec: {
      target: 'sales-order',
      parameters: { note: { type: 'string', required: false } },
      rules: [], effects: [{ kind: 'modify-target', set: { status: '"CONFIRMED"' } }],
    },
  },
  {
    apiVersion: 'ontogeny/v1', kind: 'Function',
    metadata: { name: 'line-capacity-check', display: '产能校验' },
    spec: {
      runtime: 'python', entry: 'capacity.py:check',
      parameters: {}, capabilities: [{ 'read-objects': ['sales-order'] }],
    },
  },
  {
    apiVersion: 'ontogeny/v1', kind: 'LinkType',
    metadata: { name: 'sales-order-customer', display: '订单客户' },
    spec: { source: 'sales-order', target: 'customer', cardinality: 'ONE_TO_MANY', join: { kind: 'foreign-key', keys: {} } },
  },
]

const mock = (extra: Parameters<typeof mockFetch>[0] = []) => mockFetch([
  { match: '/meta/ontology', body: META },
  { match: '/admin/builder/resources', body: { resources: RESOURCES, content_hash: 'hash1' } },
  ...extra,
])

const render = () => renderWithProviders(
  <OntologyDraftProvider><OntologyExplorer /></OntologyDraftProvider>,
  { path: '/ontology', route: '/ontology' },
)

const g6 = () => (globalThis as any).__ooG6
/** Click a node on the fake canvas, waiting for it to exist first: the graph
 *  mounts only once the active domain's resources have loaded, so `__ooG6` is
 *  undefined for the first few ticks of every render. */
const clickNode = async (id: string) => {
  await waitFor(() => expect(g6()?.cfg?.data?.nodes?.length).toBeGreaterThan(0))
  await act(async () => { g6().emitNodeClick(id) })
}
const nodeCfg = (id: string) => g6().cfg.data.nodes.find((n: { id: string }) => n.id === id)

describe('OntologyExplorer — the editable ontology canvas', () => {
  it('draws every model element as a box sized to its own name', async () => {
    mock()
    render()
    await waitFor(() => expect(screen.getByTestId('ontology-toolbar')).toBeInTheDocument())
    // the canvas mounts once the active domain's resources have loaded
    await waitFor(() => expect(g6()?.cfg?.data?.nodes?.length).toBeGreaterThan(0))

    const ids = g6().cfg.data.nodes.map((n: { id: string }) => n.id)
    expect(ids).toContain('type:sales-order')
    expect(ids).toContain('type:customer')
    expect(ids).toContain('action:confirm-sales-order')
    expect(ids).toContain('function:line-capacity-check')

    // One colour for every object type; every kind is a box, not a dot.
    const fillOf = (id: string) => g6().cfg.node.style({ data: nodeCfg(id).data }).fill
    const sizeOf = (id: string) => g6().cfg.node.style({ data: nodeCfg(id).data }).size as [number, number]
    expect(fillOf('type:sales-order')).toBe(fillOf('type:customer'))
    for (const id of ['type:sales-order', 'action:confirm-sales-order', 'function:line-capacity-check']) {
      expect(Array.isArray(sizeOf(id))).toBe(true)
      expect(sizeOf(id)[1]).toBeGreaterThan(0)
    }

    // ...and the width follows the label: a longer name gets a wider box
    expect(sizeOf('type:sales-order')[0]).toBeGreaterThan(sizeOf('type:customer')[0])

    // an action is attached to the type it targets; a function to what it reads
    const edges = g6().cfg.data.edges.map((e: { source: string; target: string }) => `${e.source}->${e.target}`)
    // the attachment arrow points at the OBJECT the action acts on / the
    // function reads
    expect(edges).toContain('action:confirm-sales-order->type:sales-order')
    expect(edges).toContain('type:sales-order->function:line-capacity-check')
  })

  it('opens a node in the right panel — no page below, no navigation away', async () => {
    mock()
    render()
    await waitFor(() => expect(screen.getByTestId('ontology-flow')).toBeInTheDocument())
    expect(screen.queryByTestId('ontology-panel')).not.toBeInTheDocument()

    await clickNode('type:sales-order')
    const panel = await screen.findByTestId('ontology-panel')
    // the header names the model element, not the internal ref kind (a raw
    // `ontology.node.object` key leaked here once)
    expect(within(panel).getByRole('heading', { level: 2 })).toHaveTextContent('Object type · sales-order')
    expect(within(panel).getByTestId('node-detail-sales-order')).toBeInTheDocument()
    expect(within(panel).getByText('so_id')).toBeInTheDocument()
    // the type's own action and function are listed as attached children
    expect(within(panel).getByTestId('attached-confirm-sales-order')).toBeInTheDocument()
    expect(within(panel).getByTestId('attached-line-capacity-check')).toBeInTheDocument()
    // nothing links out of the page any more
    expect(within(panel).queryByRole('link')).toBeNull()
  })

  it('opens an action or a function node in the same panel', async () => {
    mock()
    render()
    await waitFor(() => expect(screen.getByTestId('ontology-flow')).toBeInTheDocument())

    await clickNode('action:confirm-sales-order')
    await waitFor(() => expect(screen.getByTestId('node-detail-confirm-sales-order')).toBeInTheDocument())

    await clickNode('function:line-capacity-check')
    await waitFor(() => expect(screen.getByTestId('node-detail-line-capacity-check')).toBeInTheDocument())
    expect(screen.getByText('capacity.py:check')).toBeInTheDocument()
  })

  it('draws one directed, selectable edge per link type', async () => {
    mock()
    render()
    await waitFor(() => expect(screen.getByTestId('ontology-flow')).toBeInTheDocument())

    const link = g6().cfg.data.edges.find((e: { id?: string }) => e.id === 'link:sales-order-customer')
    expect(link).toBeTruthy()
    // direction comes from the declared source/target, not a guess
    expect(link.source).toBe('type:sales-order')
    expect(link.target).toBe('type:customer')

    // clicking the connection selects the LINK, and the panel shows its ends
    await act(async () => { g6().emitEdgeClick('link:sales-order-customer') })
    const panel = await screen.findByTestId('ontology-panel')
    expect(within(panel).getByTestId('node-detail-sales-order-customer')).toBeInTheDocument()
    expect(within(panel).getAllByText('sales-order').length).toBeGreaterThan(0)
    expect(within(panel).getByTestId('node-edit')).toBeInTheDocument()
  })

  it('lists links in the index and creates one from a type', async () => {
    mock()
    render()
    await waitFor(() => expect(screen.getByTestId('ontology-index-toggle')).toBeInTheDocument())
    // the index lists the *loaded* draft, so wait for the domain's resources
    // before opening it — otherwise the click lands on an empty index
    await waitFor(() => expect(g6()?.cfg?.data?.nodes?.length).toBeGreaterThan(0))
    fireEvent.click(screen.getByTestId('ontology-index-toggle'))
    const panel = await screen.findByTestId('ontology-panel')
    // the index used to skip link types entirely
    expect(within(panel).getByTestId('index-sales-order-customer')).toBeInTheDocument()
    fireEvent.click(within(panel).getByTestId('index-sales-order-customer'))
    await waitFor(() => expect(screen.getByTestId('node-detail-sales-order-customer')).toBeInTheDocument())
  })

  it('creates any of the five kinds from one + menu', async () => {
    mock()
    render()
    await waitFor(() => expect(g6()?.cfg?.data?.nodes?.length).toBeGreaterThan(0))

    // one trigger, five actions — the words live in the menu, not the toolbar
    const trigger = screen.getByTestId('palette-new')
    expect(trigger).toHaveAttribute('aria-haspopup', 'menu')
    expect(trigger).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByTestId('palette-menu')).not.toBeInTheDocument()

    fireEvent.click(trigger)
    const menu = await screen.findByTestId('palette-menu')
    for (const id of ['palette-object', 'palette-action', 'palette-function', 'palette-link', 'palette-policy']) {
      expect(within(menu).getByTestId(id)).toBeInTheDocument()
    }

    // picking one opens that kind's editor on a fresh, uniquely named resource
    fireEvent.click(within(menu).getByTestId('palette-function'))
    await waitFor(() => expect(screen.getByTestId('resource-dialog')).toBeInTheDocument())
    expect(screen.queryByTestId('palette-menu')).not.toBeInTheDocument()
  })

  it('opens the type index from the toolbar', async () => {
    mock()
    render()
    await waitFor(() => expect(screen.getByTestId('ontology-index-toggle')).toBeInTheDocument())
    await waitFor(() => expect(g6()?.cfg?.data?.nodes?.length).toBeGreaterThan(0))
    fireEvent.click(screen.getByTestId('ontology-index-toggle'))
    const panel = await screen.findByTestId('ontology-panel')
    expect(within(panel).getByTestId('index-sales-order')).toBeInTheDocument()
    fireEvent.click(within(panel).getByTestId('index-customer'))
    await waitFor(() => expect(screen.getByTestId('node-detail-customer')).toBeInTheDocument())
  })

  it('edits a type in a modal, and only the save button reaches the server', async () => {
    const { calls } = mock([
      { match: '/admin/builder/save', body: { published: true, content_hash: 'h2', written: [], removed: [], issues: [] } },
    ])
    render()
    await waitFor(() => expect(screen.getByTestId('ontology-flow')).toBeInTheDocument())
    await clickNode('type:sales-order')

    fireEvent.click(await screen.findByTestId('node-edit'))
    const dialog = await screen.findByTestId('resource-dialog')
    expect(within(dialog).getByTestId('object-type-editor')).toBeInTheDocument()

    // the panel is not wide enough for a property table: the form is a modal
    const display = within(dialog).getByDisplayValue('销售订单')
    fireEvent.change(display, { target: { value: '销售订单（改）' } })

    // nothing has been sent yet — the edit is a draft
    expect(calls.some((c) => c.url.includes('/admin/builder/save'))).toBe(false)
    await waitFor(() => expect(screen.getByTestId('ontology-dirty').textContent).toMatch(/unsaved/i))

    fireEvent.click(screen.getByTestId('ontology-save'))
    await waitFor(() => expect(calls.some((c) => c.url.includes('/admin/builder/save'))).toBe(true))
    const body = JSON.parse(String(calls.find((c) => c.url.includes('/admin/builder/save'))!.init?.body))
    expect(body.resources.map((r: { kind: string }) => r.kind)).toEqual(['ObjectType'])
    expect(body.resources[0].metadata.display).toBe('销售订单（改）')
  })

  it('adds a new action from the panel and sends it on save', async () => {
    const { calls } = mock([
      { match: '/admin/builder/save', body: { published: true, content_hash: 'h3', written: [], removed: [], issues: [] } },
    ])
    render()
    await waitFor(() => expect(screen.getByTestId('ontology-flow')).toBeInTheDocument())
    await clickNode('type:sales-order')
    fireEvent.click(await screen.findByTestId('add-action-for'))

    const dialog = await screen.findByTestId('resource-dialog')
    expect(within(dialog).getByTestId('action-editor')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('ontology-save'))
    await waitFor(() => expect(calls.some((c) => c.url.includes('/admin/builder/save'))).toBe(true))
    const body = JSON.parse(String(calls.find((c) => c.url.includes('/admin/builder/save'))!.init?.body))
    expect(body.resources.map((r: { kind: string }) => r.kind)).toEqual(['Action'])
    expect(body.resources[0].spec.target).toBe('sales-order')
  })

  it('deletes a resource only after the confirmation', async () => {
    mock()
    render()
    await waitFor(() => expect(screen.getByTestId('ontology-flow')).toBeInTheDocument())
    await clickNode('type:customer')
    fireEvent.click(await screen.findByTestId('node-delete'))
    await waitFor(() => expect(screen.getByTestId('confirm-dialog')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('confirm-accept'))
    await waitFor(() => expect(screen.queryByTestId('node-detail-customer')).not.toBeInTheDocument())
    await waitFor(() => expect(screen.getByTestId('ontology-dirty').textContent).toMatch(/unsaved/i))
  })

  it('edits and deletes an ACTION from its own node, and a FUNCTION too', async () => {
    const { calls } = mock([
      { match: '/admin/builder/save', body: { published: true, content_hash: 'h5', written: [], removed: [], issues: [] } },
    ])
    render()
    await waitFor(() => expect(screen.getByTestId('ontology-flow')).toBeInTheDocument())

    // an action node opens its own editor, and its target is editable
    await clickNode('action:confirm-sales-order')
    fireEvent.click(await screen.findByTestId('node-edit'))
    const dialog = await screen.findByTestId('resource-dialog')
    expect(within(dialog).getByTestId('action-editor')).toBeInTheDocument()
    fireEvent.change(within(dialog).getByDisplayValue('确认订单'), { target: { value: '确认订单（改）' } })
    fireEvent.click(screen.getByTestId('resource-dialog-close'))

    // a function node likewise
    await clickNode('function:line-capacity-check')
    fireEvent.click(await screen.findByTestId('node-edit'))
    const fnDialog = await screen.findByTestId('resource-dialog')
    expect(within(fnDialog).getByTestId('function-editor')).toBeInTheDocument()
    expect(within(fnDialog).getByDisplayValue('capacity.py:check')).toBeInTheDocument()
    // an untouched field is not an edit: change one so the save carries it
    fireEvent.change(within(fnDialog).getByDisplayValue('产能校验'), { target: { value: '产能校验（改）' } })
    fireEvent.click(screen.getByTestId('resource-dialog-close'))

    // deleting the action takes it off the canvas and into the deletes list
    await clickNode('action:confirm-sales-order')
    fireEvent.click(await screen.findByTestId('node-delete'))
    fireEvent.click(await screen.findByTestId('confirm-accept'))
    await waitFor(() => expect(screen.queryByTestId('node-detail-confirm-sales-order')).not.toBeInTheDocument())

    fireEvent.click(screen.getByTestId('ontology-save'))
    await waitFor(() => expect(calls.some((c) => c.url.includes('/admin/builder/save'))).toBe(true))
    const body = JSON.parse(String(calls.find((c) => c.url.includes('/admin/builder/save'))!.init?.body))
    // the edited function is written; the action was edited *and then deleted*,
    // so it is a delete rather than an update
    expect(body.resources.map((r: { kind: string }) => r.kind)).toEqual(['Function'])
    expect(body.resources[0].metadata.display).toBe('产能校验（改）')
    expect(body.deletes).toEqual(['Action/confirm-sales-order'])
  })

  it('persists a dragged layout only when saved', async () => {
    const { calls } = mock([
      { match: '/admin/builder/save', body: { published: true, content_hash: 'h4', written: [], removed: [], issues: [] } },
    ])
    localStorage.clear()
    render()
    await waitFor(() => expect(screen.getByTestId('ontology-flow')).toBeInTheDocument())
    await waitFor(() => expect(g6()?.cfg?.data?.nodes?.length).toBeGreaterThan(0))

    // a drag marks the page dirty rather than silently rewriting anything
    await act(async () => { g6().emitNodeDragEnd('type:sales-order', 500, 320) })
    await waitFor(() => expect(screen.getByTestId('ontology-dirty').textContent).toMatch(/unsaved/i))
    // positions are server state now (the package's layout.yaml): nothing is
    // written to the browser, not even under the legacy per-domain key
    expect(localStorage.getItem('ontogeny.ontology.layout.manufacturing-system')).toBeNull()

    fireEvent.click(screen.getByTestId('ontology-save'))
    await waitFor(() => expect(calls.some((c) => c.url.includes('/admin/builder/save'))).toBe(true))
    await waitFor(() => {
      const body = JSON.parse(String(calls.find((c) => c.url.includes('/admin/builder/save'))!.init?.body))
      expect(body.layout['type:sales-order']).toEqual({ x: 500, y: 320 })
    })
  })
})

/** One active ontology per deployment: switching republishes server-side, and
 *  the canvas holds a *copy* of the package it loaded. Seeds itself once and
 *  never again, and "switching a domain leaves the ontology browser empty"
 *  follows: the copy belongs to the package that is no longer active. */
describe('OntologyExplorer — a domain switch moves the canvas with it', () => {
  const logisticsResources = [{
    apiVersion: 'ontogeny/v1', kind: 'ObjectType',
    metadata: { name: 'waybill', display: '运单' },
    spec: { primaryKey: ['waybill_id'], properties: { waybill_id: { type: 'string', required: true } } },
  }]

  const domainA = {
    domains: [
      { name: 'manufacturing-system', display: '离散制造运营系统', path: '/tmp/a', objects: 2, links: 1, actions: 1, active: true },
      { name: 'logistics-system', display: '物流运营系统', path: '/tmp/b', objects: 1, links: 0, actions: 0, active: false },
    ],
    active: 'manufacturing-system',
  }
  const domainB = {
    domains: [
      domainA.domains[0], { ...domainA.domains[1], active: true },
    ],
    active: 'logistics-system',
  }

  it('re-reads the newly activated package instead of drawing the old one', async () => {
    // one live answer per route, so the same mock can serve both domains
    let domainBody: unknown = domainA
    let resourcesBody: unknown = { resources: RESOURCES, content_hash: 'hash1' }
    mockFetch([
      { match: '/meta/ontology', body: META },
      { match: '/admin/builder/resources', body: () => resourcesBody },
      { match: '/admin/domains', body: () => domainBody },
    ])
    let qc: QueryClient | undefined
    renderWithProviders(
      <OntologyDraftProvider><OntologyExplorer /></OntologyDraftProvider>,
      { path: '/ontology', route: '/ontology', onClient: (c) => { qc = c } },
    )
    await waitFor(() => expect(g6()?.cfg?.data?.nodes?.some((n: { id: string }) => n.id === 'type:sales-order')).toBe(true))

    // the user picks "物流运营系统" in the switcher: the server republishes and
    // the switcher invalidates the whole cache (see DomainSwitcher.afterSwitch)
    domainBody = domainB
    resourcesBody = { resources: logisticsResources, content_hash: 'hash2' }
    await act(async () => { await qc!.invalidateQueries() })

    await waitFor(() => {
      const ids = g6()?.cfg?.data?.nodes?.map((n: { id: string }) => n.id) ?? []
      expect(ids).toContain('type:waybill')
      expect(ids).not.toContain('type:sales-order')
    })
  })

  it('never restores another domain’s draft onto the new canvas', async () => {
    // an autosaved draft from the manufacturing package, left in storage
    localStorage.setItem('ontogeny.ontology.draft', JSON.stringify({
      savedAt: Date.now(),
      domain: 'manufacturing-system',
      resources: RESOURCES,
      touched: ['ObjectType/sales-order'],
      removed: [],
      layout: {},
    }))
    mockFetch([
      { match: '/meta/ontology', body: META },
      { match: '/admin/builder/resources', body: { resources: logisticsResources, content_hash: 'hash2' } },
      { match: '/admin/domains', body: domainB },
    ])
    renderWithProviders(
      <OntologyDraftProvider><OntologyExplorer /></OntologyDraftProvider>,
      { path: '/ontology', route: '/ontology' },
    )

    await waitFor(() => {
      const ids = g6()?.cfg?.data?.nodes?.map((n: { id: string }) => n.id) ?? []
      expect(ids).toEqual(['type:waybill'])
    })
    // ...and the draft it refused is gone, so it cannot come back on a reload
    expect(localStorage.getItem('ontogeny.ontology.draft')).toBeNull()
  })
})

/** The canvas's visual contract: one icon and one colour per model kind, and
 *  solid lines for entity relationships vs dashed lines for every other
 *  attachment. Both are decided in the adapter, so they are testable without a
 *  browser. */
describe('OntologyExplorer — the drawing language', () => {
  it('tags every node with its model kind and gives each kind an icon', async () => {
    mock()
    render()
    await waitFor(() => expect(g6()?.cfg?.data?.nodes?.length).toBeGreaterThan(0))

    const kindOf = (id: string) => nodeCfg(id).data.kind
    expect(kindOf('type:sales-order')).toBe('object')
    expect(kindOf('action:confirm-sales-order')).toBe('action')
    expect(kindOf('function:line-capacity-check')).toBe('function')

    // Every box carries an inline SVG icon of its kind (no network, no icon
    // font). Object types are HTML entity cards (the icon travels on
    // `cardIconSrc`, inlined into their markup); the canvas-drawn satellites keep
    // `kindIconSrc`. Either way the node is handed its kind's icon.
    const styleOf = (id: string) => g6().cfg.node.style({ data: nodeCfg(id).data })
    const iconOf = (id: string) => styleOf(id).cardIconSrc ?? styleOf(id).kindIconSrc
    for (const id of ['type:sales-order', 'action:confirm-sales-order', 'function:line-capacity-check']) {
      expect(String(iconOf(id))).toMatch(/^data:image\/svg\+xml/)
    }
  })

  it('emits exactly one node per model element, even when a function reads two types', async () => {
    // Regression: a function's `read-objects` capability can name several types,
    // and the adapter hung one box under EACH of them. G6 rejects the duplicate
    // id ("Node already exists"), which threw during render and blanked the
    // whole page — jsdom's fake engine accepted it silently, so only the real
    // canvas caught it.
    // mockFetch matches the FIRST route, so the override has to come before the
    // shared `mock()` helper's own builder/resources route
    mockFetch([
      {
        match: '/admin/builder/resources',
        body: {
          resources: [
            ...RESOURCES,
            {
              apiVersion: 'ontogeny/v1', kind: 'Function',
              metadata: { name: 'reads-two', display: '跨类型函数' },
              spec: {
                runtime: 'python', entry: 'two.py:main', parameters: {},
                capabilities: [{ 'read-objects': ['sales-order', 'customer'] }],
              },
            },
          ],
          content_hash: 'hash2',
        },
      },
      { match: '/meta/ontology', body: META },
    ])
    render()
    await waitFor(() => expect(g6()?.cfg?.data?.nodes?.length).toBeGreaterThan(0))

    const ids = g6().cfg.data.nodes.map((n: { id: string }) => n.id)
    expect(new Set(ids).size).toBe(ids.length)
    // ...and it is attached to both types it reads
    const edges = g6().cfg.data.edges.map((e: { source: string; target: string }) => `${e.source}->${e.target}`)
    expect(edges).toContain('type:sales-order->function:reads-two')
    expect(edges).toContain('type:customer->function:reads-two')
  })

  it('draws entity relationships solid and every other attachment dashed', async () => {
    mock()
    render()
    await waitFor(() => expect(g6()?.cfg?.data?.edges?.length).toBeGreaterThan(0))

    const edges = g6().cfg.data.edges as Array<{ source: string; target: string; data: { dashed?: boolean } }>
    const link = edges.find((e) => e.source === 'type:sales-order' && e.target === 'type:customer')
    // attachment arrows: an action points at the object it acts on; a
    // function is pointed at BY the object it reads
    const action = edges.find((e) => e.source === 'action:confirm-sales-order')
    const fn = edges.find((e) => e.target === 'function:line-capacity-check')

    expect(link?.data.dashed).toBe(false)
    expect(action?.data.dashed).toBe(true)
    expect(fn?.data.dashed).toBe(true)

    // ...and the canvas paints that as a dash pattern, not just a flag
    const dashOf = (dashed?: boolean) => g6().cfg.edge.style({ data: { dashed } })
    expect(dashOf(false).lineDash).toBeUndefined()
    expect(dashOf(true).lineDash).toEqual([5, 4])
  })
})
