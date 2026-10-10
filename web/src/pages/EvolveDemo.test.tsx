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
/** The one-click demo run: the whole loop through the real endpoints, and the
 *  honesty rules — a red eval or a human-gated promotion must STOP the run and
 *  say so, never fake a green ending. */
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { mockFetch, META } from '../test/setup'
import { renderWithProviders } from '../test/render'
import { EvolveConsole } from './EvolveConsole'

type ObjectMetaFixture = {
  display?: string
  primaryKey: string[]
  properties: Record<string, { type: string; required: boolean; marking: string | null; display?: string; description?: string | null; owner?: string | null; derived?: unknown }>
  links: string[]
  actions: string[]
}

/** META with extra properties on a type — a fresh clone each call, since the
 *  fixture object is shared by every test in the file. */
function metaWith(type: string, props: Record<string, ObjectMetaFixture['properties'][string]>) {
  const clone = structuredClone(META) as unknown as { objects: Record<string, ObjectMetaFixture> }
  Object.assign(clone.objects[type].properties, props)
  return clone
}
const PROPOSAL = {
  id: 7,
  gap_kind: 'add-optional-property',
  diff: [{ mutation: 'add-optional-property', object: 'sales-order', prop: 'zone', type: 'string' }],
  rationale: 'filter field zone used 6x',
}

function mockHappyPath() {
  // The world flips exactly when the promote call responds: from that moment
  // the field is modelled and the query passes. Stateful bodies make the
  // transition synchronous with the demo's own continuation (no test race).
  let promoted = false
  const withZone = metaWith('sales-order', { zone: { type: 'string', required: false, marking: null } })
  return mockFetch([
    { match: '/evolve/aggregate', body: { created: [{ kind: 'unmapped_filter_field', evidence: { object_type: 'sales-order', field: 'zone', count: 6 } }] } },
    { match: '/evolve/diagnose', body: { proposals: [PROPOSAL] } },
    { match: /proposals\/7\/eval/, body: { passed: true } },
    {
      match: /proposals\/7\/promote/,
      body: () => {
        promoted = true
        return { status: 'promoted', tier: 't0-auto-merge', budget_used: 1, budget_cap: 8, content_hash: 'b7c21b76aa' }
      },
    },
    // before promotion every query probe is rejected (unknown field) — that IS
    // the demo's signal; after it the same query goes through
    {
      match: /\/objects\/.*\/query/,
      body: () => (promoted
        ? { objects: [], total: 0, latency_ms: 1 }
        : { code: 'NOT_FOUND', message: "unknown filter field 'zone'" }),
      status: undefined as unknown as number,
    },
    { match: '/meta/ontology', body: () => (promoted ? withZone : META) },
  ])
}

const render = () => renderWithProviders(<EvolveConsole />, { path: '/evolve', route: '/evolve' })

async function startDemo() {
  // the button waits for the meta snapshot (it needs the schema to pick a gap)
  await waitFor(() => expect(screen.getByTestId('demo-run')).toBeEnabled())
  fireEvent.click(screen.getByTestId('demo-run'))
}

describe('EvolveDemo — the one-click loop', () => {
  it('walks gap → traffic → signals → proposal → eval → promote → verify, all green', async () => {
    mockHappyPath()
    render()
    await startDemo()

    // the panel appears with the seven steps...
    expect(await screen.findByText('① Pick a modelling gap')).toBeInTheDocument()
    // ...and every step lands on "done"
    await waitFor(() => {
      const badges = screen.getAllByText('done')
      expect(badges).toHaveLength(7)
    }, { timeout: 4000 })
    // the verify step says the loop actually closed, with the new property
    expect(screen.getByText(/sales-order has the new property “zone”/)).toBeInTheDocument()
    // and the summary names the promoted proposal
    expect(screen.getByText(/Proposal #7/)).toBeInTheDocument()
  })

  it('stops honestly when the eval suites are red', async () => {
    mockFetch([
      { match: '/evolve/aggregate', body: { created: [] } },
      { match: '/evolve/diagnose', body: { proposals: [PROPOSAL] } },
      { match: /proposals\/7\/eval/, body: { passed: false } },
      { match: /\/objects\/.*\/query/, status: 404, body: { code: 'NOT_FOUND', message: 'x' } },
      { match: '/meta/ontology', body: META },
    ])
    render()
    await startDemo()

    // eval step fails, and everything after it stays pending: no faked green
    await waitFor(() => expect(screen.getByText('⑤ Run the eval suites').parentElement!.parentElement!.textContent).toContain('failed'))
    expect(screen.getByText(/held back by the selection function/)).toBeInTheDocument()
    expect(screen.getByText('⑥ Promote by policy')).toBeInTheDocument()
    const badges = screen.getAllByText('pending')
    expect(badges.length).toBeGreaterThanOrEqual(2)
  })

  it('ends in the converged steady state when every candidate is modelled', async () => {
    // zone/line/batch_code/station are all present in the snapshot already
    const full = metaWith('sales-order', Object.fromEntries(
      ['zone', 'line', 'batch_code', 'station'].map((f) => [f, { type: 'string', required: false, marking: null }]),
    ))
    mockFetch([{ match: '/meta/ontology', body: full }])
    render()
    await startDemo()

    expect(await screen.findByText(/converged steady state/)).toBeInTheDocument()
    // nothing after the first step ran
    expect(screen.getAllByText('pending').length).toBe(6)
  })
})
