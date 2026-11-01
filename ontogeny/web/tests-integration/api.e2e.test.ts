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
specific language governing permissions and
limitations under the License.
*/
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
const PRODUCT = { id: 'e2e-product', Role: ['product'], site: 'hq', is_admin: true }
const VISITOR = { id: 'e2e-visitor' }

async function api<T = any>(
  p: string,
  { method = 'GET', body, principal = PRODUCT }: { method?: string; body?: unknown; principal?: object } = {},
): Promise<{ status: number; json: T }> {
  const resp = await fetch(`${BASE}${p}`, {
    method,
    headers: { 'content-type': 'application/json', 'X-Ontogeny-Principal': JSON.stringify(principal) },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const json = resp.status === 204 ? undefined : await resp.json().catch(() => undefined)
  return { status: resp.status, json }
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
    expect(json.package).toBe('chip-lifecycle')
    expect(Object.keys(json.objects).sort()).toEqual([
      'customer', 'design-module', 'equipment', 'field-failure', 'fmea-note',
      'process-step', 'requirement', 'tapeout-version', 'wafer-lot', 'wafer-test',
    ])
  })

  it('syncs all source-backed object types from the source database', async () => {
    // fmea-note is document-extracted, not synced
    for (const t of [
      'requirement', 'design-module', 'tapeout-version', 'equipment', 'wafer-lot',
      'process-step', 'wafer-test', 'customer', 'field-failure',
    ]) {
      const { status, json } = await api(`/api/v1/admin/sync/${t}`, { method: 'POST' })
      expect(status).toBe(200)
      expect((json.inserted ?? 0) + (json.updated ?? 0)).toBeGreaterThan(0)
    }
  })

  it('queries objects with row results and marking masks', async () => {
    const { status, json } = await api('/api/v1/objects/wafer-lot/query', {
      method: 'POST',
      body: { filter: { status: 'RUNNING' }, sort: [['lot_id', 'asc']] },
    })
    expect(status).toBe(200)
    expect(json.total).toBeGreaterThanOrEqual(1) // LOT-2419 / LOT-2501 ship RUNNING

    const version = await api('/api/v1/objects/tapeout-version/TO-A0')
    expect(version.json.mask_cost).toBe('__masked__')
    const marked = await api('/api/v1/objects/tapeout-version/TO-A0', {
      principal: { ...PRODUCT, markings: ['internal'] },
    })
    expect(marked.json.mask_cost).toBe(1850000) // decimals sync as numbers
  })

  it('executes the full action cycle: validate → execute → rule guard → policy deny → audit', async () => {
    // tape out the one PLANNED version: product passes Cedar, rule sees PLANNED
    const v = await api('/api/v1/actions/tapeout/validate', {
      method: 'POST',
      body: { parameters: {}, target_id: 'TO-A1' },
    })
    expect(v.status).toBe(200)
    expect(v.json.policy.allow).toBe(true)

    const x = await api('/api/v1/actions/tapeout/execute', {
      method: 'POST',
      body: { parameters: {}, target_id: 'TO-A1', idempotency_key: 'e2e-tapeout' },
    })
    expect(x.status).toBe(200)
    expect(x.json.outcome).toBe('executed')
    expect(x.json.after.status).toBe('FAB')

    const replay = await api('/api/v1/actions/tapeout/execute', {
      method: 'POST',
      body: { parameters: {}, target_id: 'TO-A1', idempotency_key: 'e2e-tapeout' },
    })
    expect(replay.json.revision_id).toBe(x.json.revision_id) // idempotent

    // taping out again trips the rule before policy even runs
    const dbl = await api('/api/v1/actions/tapeout/execute', {
      method: 'POST',
      body: { parameters: {}, target_id: 'TO-A1' },
    })
    expect(dbl.status).toBe(422)
    expect(dbl.json.code).toBe('RULE_REJECTED')

    // a fresh PLANNED version: the rule passes for anyone, so a roleless
    // principal is denied by Cedar (default deny), not by the rule
    const created = await api('/api/v1/actions/create-tapeout-version/execute', {
      method: 'POST',
      body: { parameters: { project: 'X3', notes: 'e2e probe' } },
    })
    expect(created.status).toBe(200)
    const newId = created.json.object_id ?? created.json.after?.version_id

    const deny = await api('/api/v1/actions/tapeout/execute', {
      method: 'POST',
      body: { parameters: {}, target_id: newId },
      principal: VISITOR,
    })
    expect(deny.status).toBe(403)
    expect(deny.json.code).toBe('POLICY_DENIED')

    const audit = await api('/api/v1/audit/revisions?object_id=TO-A1')
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
        start_type: 'equipment',
        start_ids: ['EQ-07'],
        path: [
          { link: 'step-equipment', direction: 'out' },
          { link: 'lot-steps', direction: 'in' },
        ],
      },
    })
    expect(status).toBe(200)
    expect(json.steps.at(-1).type).toBe('wafer-lot')
    // EQ-07 etched PS-7112 (LOT-2417) and PS-7132 (LOT-2419)
    expect([...json.final_ids].sort()).toEqual(['LOT-2417', 'LOT-2419'])
  })

  it('runs the RSI loop end-to-end: signal → proposal → eval → T0 promote → live schema', async () => {
    // the intentional demo gap: field_failures carries lot_id in the source
    // but the model does not declare it. Six failed filters raise the signal.
    for (let i = 0; i < 6; i++) {
      await api('/api/v1/objects/field-failure/query', {
        method: 'POST',
        body: { filter: { field: 'lot_id', op: 'eq', value: 'LOT-2417' } },
      })
    }
    const agg = await api('/api/v1/evolve/aggregate', { method: 'POST' })
    expect(agg.json.created.some((s: any) => s.kind === 'unmapped_filter_field')).toBe(true)

    const diag = await api('/api/v1/evolve/diagnose', { method: 'POST' })
    const proposal = diag.json.proposals.find((p: any) => p.gap_kind === 'add-optional-property')
    expect(proposal).toBeTruthy()
    expect(proposal.diff[0].prop).toBe('lot_id')

    const ev = await api(`/api/v1/evolve/proposals/${proposal.id}/eval`, { method: 'POST' })
    expect(ev.status).toBe(200)
    expect(ev.json.passed).toBe(true)

    const pr = await api(`/api/v1/evolve/proposals/${proposal.id}/promote`, { method: 'POST' })
    expect(pr.status).toBe(200)
    expect(pr.json.status).toBe('promoted')
    expect(pr.json.tier).toBe('t0-auto-merge')

    // the mutation is LIVE in the registry (hot-swapped snapshot): the
    // customer-return → wafer-lot trace chain is now closed
    const meta = await api('/api/v1/meta/ontology')
    expect(Object.keys(meta.json.objects['field-failure'].properties)).toContain('lot_id')
  })

  it('serves the ontology assistant through the live Ollama endpoint', { timeout: 180_000 }, async (ctx) => {
    if (!llmOk) ctx.skip()
    const { status, json } = await api('/api/v1/assistant/chat', {
      method: 'POST',
      body: {
        messages: [{ role: 'user', content: 'In one sentence, how does wafer-lot relate to equipment?' }],
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
          { role: 'user', content: 'Quality engineers keep filtering field failures by lot_id, but the ontology has no such property. Propose one add-optional-property mutation.' },
        ],
        propose: true,
      },
    })
    expect(status).toBe(200)
    // the model's exact wording varies run to run; assert plumbing + shape,
    // and surface the payload when a structural expectation fails
    expect(json.content, `empty content; payload=${JSON.stringify(json).slice(0, 300)}`).toBeTruthy()
    // A live model may legitimately decline to propose (empty array) or
    // return no proposals block at all -- both are valid answers. What the
    // endpoint CONTRACTS is: proposals, when present, is an array, and every
    // element carries a non-empty `mutation` string. Asserting on a
    // first-element mutation made this test flaky on nondeterministic model
    // output; the deterministic proposer path is covered by unit tests.
    if (json.proposals != null) {
      expect(Array.isArray(json.proposals), JSON.stringify(json.proposals).slice(0, 200)).toBe(true)
      for (const m of json.proposals) {
        expect(typeof m?.mutation, JSON.stringify(m).slice(0, 200)).toBe('string')
        expect(m.mutation.length, JSON.stringify(m).slice(0, 200)).toBeGreaterThan(0)
      }
    }
  })
})
