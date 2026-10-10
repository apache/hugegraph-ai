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
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { beforeAll, describe, expect, it } from 'vitest'

const PORT = Number(readFileSync(path.join(__dirname, '..', '.e2e-port'), 'utf-8').trim())
const BASE = `http://127.0.0.1:${PORT}`

// admin/evolve planes are admin-gated now; the dev-header simulation may
// claim it explicitly (dev_auth is enabled for this e2e server).
const PLANNER = { id: 'e2e-planner', Role: ['planner'], site: 'plant-north', is_admin: true }
const VISITOR = { id: 'e2e-visitor' }

async function api<T = any>(
  p: string,
  { method = 'GET', body, principal = PLANNER }: { method?: string; body?: unknown; principal?: object } = {},
): Promise<{ status: number; json: T }> {
  const resp = await fetch(`${BASE}${p}`, {
    method,
    headers: { 'content-type': 'application/json', 'X-Ontogeny-Principal': JSON.stringify(principal) },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const json = resp.status === 204 ? undefined : await resp.json().catch(() => undefined)
  return { status: resp.status, json: json as T }
}

let llmOk = false

beforeAll(async () => {
  const { json } = await api('/api/v1/admin/llm/status')
  llmOk = Boolean(json?.ok)
})

describe('e2e: real backend', () => {
  it('serves the compiled ontology meta', async () => {
    const { status, json } = await api('/api/v1/meta/ontology')
    expect(status).toBe(200)
    expect(json.package).toBe('product-manufacturing')
    expect(Object.keys(json.objects).sort()).toEqual(
      ['bom', 'material', 'operation', 'product', 'production-order', 'quality-inspection', 'work-center'],
    )
  })

  it('syncs all object types from the source database', async () => {
    for (const t of ['product', 'bom', 'material', 'work-center', 'production-order', 'operation', 'quality-inspection']) {
      const { status, json } = await api(`/api/v1/admin/sync/${t}`, { method: 'POST' })
      expect(status).toBe(200)
      expect((json.inserted ?? 0) + (json.updated ?? 0)).toBeGreaterThan(0)
    }
  })

  it('queries objects with row results and marking masks', async () => {
    const { status, json } = await api('/api/v1/objects/production-order/query', {
      method: 'POST',
      body: { filter: { status: 'PLANNED' }, sort: [['order_id', 'asc']] },
    })
    expect(status).toBe(200)
    expect(json.total).toBeGreaterThanOrEqual(1) // PO-1002 ships PLANNED

    const mat = await api('/api/v1/objects/material/M-104')
    expect(mat.json.unit_cost).toBe('__masked__')
    const marked = await api('/api/v1/objects/material/M-104', {
      principal: { ...PLANNER, markings: ['internal'] },
    })
    expect(marked.json.unit_cost).toBe(320) // decimals sync as numbers
  })

  it('executes the full action cycle: validate → execute → rule guard → policy deny → audit', async () => {
    // release the one PLANNED order: planner passes Cedar, rule sees PLANNED
    const v = await api('/api/v1/actions/release-production-order/validate', {
      method: 'POST',
      body: { parameters: {}, target_id: 'PO-1002' },
    })
    expect(v.status).toBe(200)
    expect(v.json.policy.allow).toBe(true)

    const x = await api('/api/v1/actions/release-production-order/execute', {
      method: 'POST',
      body: { parameters: {}, target_id: 'PO-1002', idempotency_key: 'e2e-release' },
    })
    expect(x.status).toBe(200)
    expect(x.json.outcome).toBe('executed')
    expect(x.json.after.status).toBe('RELEASED')

    const replay = await api('/api/v1/actions/release-production-order/execute', {
      method: 'POST',
      body: { parameters: {}, target_id: 'PO-1002', idempotency_key: 'e2e-release' },
    })
    expect(replay.json.revision_id).toBe(x.json.revision_id) // idempotent

    // releasing again trips the rule before policy even runs
    const dbl = await api('/api/v1/actions/release-production-order/execute', {
      method: 'POST',
      body: { parameters: {}, target_id: 'PO-1002' },
    })
    expect(dbl.status).toBe(422)
    expect(dbl.json.code).toBe('RULE_REJECTED')

    // a fresh PLANNED order: the rule passes for anyone, so a roleless
    // principal is denied by Cedar (default deny), not by the rule
    const created = await api('/api/v1/actions/create-production-order/execute', {
      method: 'POST',
      body: { parameters: { product_id: 'P-200', qty: 5 } },
    })
    expect(created.status).toBe(200)
    const newId = created.json.object_id ?? created.json.after?.order_id

    const deny = await api('/api/v1/actions/release-production-order/execute', {
      method: 'POST',
      body: { parameters: {}, target_id: newId },
      principal: VISITOR,
    })
    expect(deny.status).toBe(403)
    expect(deny.json.code).toBe('POLICY_DENIED')

    const audit = await api('/api/v1/audit/revisions?object_id=PO-1002')
    const outcomes = audit.json.revisions.map((r: any) => r.outcome)
    expect(outcomes).toContain('executed')
    expect(outcomes).toContain('rejected_rule')
    const denied = await api('/api/v1/audit/revisions?object_id=' + newId)
    expect(denied.json.revisions.map((r: any) => r.outcome)).toContain('denied_policy')
  })

  it('traverses links across two hops', async () => {
    const { status, json } = await api('/api/v1/graph/traverse', {
      method: 'POST',
      body: {
        start_type: 'work-center',
        start_ids: ['WC-01'],
        path: [
          { link: 'operation-work-center', direction: 'out' },
          { link: 'production-order-operations', direction: 'in' },
        ],
      },
    })
    expect(status).toBe(200)
    expect(json.steps.at(-1).type).toBe('production-order')
    // WC-01 runs OP-2001 + OP-2002 (PO-1001) and OP-2301 (PO-1004)
    expect([...json.final_ids].sort()).toEqual(['PO-1001', 'PO-1004'])
  })

  it('runs the RSI loop end-to-end: signal → proposal → eval → T0 promote → live schema', async () => {
    // generate the fitness signal: unmapped filter field, 6 failed queries
    for (let i = 0; i < 6; i++) {
      await api('/api/v1/objects/production-order/query', {
        method: 'POST',
        body: { filter: { field: 'expedite', op: 'eq', value: 'Y' } },
      })
    }
    const agg = await api('/api/v1/evolve/aggregate', { method: 'POST' })
    expect(agg.json.created.some((s: any) => s.kind === 'unmapped_filter_field')).toBe(true)

    const diag = await api('/api/v1/evolve/diagnose', { method: 'POST' })
    const proposal = diag.json.proposals.find((p: any) => p.gap_kind === 'add-optional-property')
    expect(proposal).toBeTruthy()
    expect(proposal.diff[0].prop).toBe('expedite')

    const ev = await api(`/api/v1/evolve/proposals/${proposal.id}/eval`, { method: 'POST' })
    expect(ev.status).toBe(200)
    expect(ev.json.passed).toBe(true)

    const pr = await api(`/api/v1/evolve/proposals/${proposal.id}/promote`, { method: 'POST' })
    expect(pr.status).toBe(200)
    expect(pr.json.status).toBe('promoted')
    expect(pr.json.tier).toBe('t0-auto-merge')

    // the mutation is LIVE in the registry (hot-swapped snapshot)
    const meta = await api('/api/v1/meta/ontology')
    expect(Object.keys(meta.json.objects['production-order'].properties)).toContain('expedite')
  })

  it('serves the ontology assistant through the live Ollama endpoint', { timeout: 180_000 }, async (ctx) => {
    if (!llmOk) ctx.skip()
    const { status, json } = await api('/api/v1/assistant/chat', {
      method: 'POST',
      body: {
        messages: [{ role: 'user', content: 'In one sentence, how does production-order relate to work-center?' }],
      },
    })
    expect(status).toBe(200)
    expect(typeof json.content).toBe('string')
    expect(json.content.length).toBeGreaterThan(0)
  })

  it('assistant propose mode returns parsable mutations (live LLM)', { timeout: 180_000 }, async (ctx) => {
    if (!llmOk) ctx.skip()
    const { status, json } = await api('/api/v1/assistant/chat', {
      method: 'POST',
      body: {
        messages: [
          { role: 'user', content: 'Planners keep filtering production orders by expedite flag, but the ontology has no such property. Propose one add-optional-property mutation.' },
        ],
        propose: true,
      },
    })
    expect(status).toBe(200)
    // the model's exact wording varies run to run; assert plumbing + shape,
    // and surface the payload when a structural expectation fails
    expect(json.content, `empty content; payload=${JSON.stringify(json).slice(0, 300)}`).toBeTruthy()
    if (json.proposals != null) {
      expect(Array.isArray(json.proposals), JSON.stringify(json.proposals).slice(0, 200)).toBe(true)
      const m = json.proposals[0]
      expect(typeof m.mutation, JSON.stringify(m)).toBe('string')
      expect(m.mutation.length, JSON.stringify(m)).toBeGreaterThan(0)
    }
  })
})
