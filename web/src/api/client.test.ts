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
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, PRESET_PRINCIPALS, getPrincipal, setPrincipal } from './client'

describe('principal handling', () => {
  beforeEach(() => localStorage.clear())

  it('defaults to the planner preset', () => {
    expect(getPrincipal().id).toBe(PRESET_PRINCIPALS.planner.id)
  })

  it('persists a chosen principal', () => {
    setPrincipal(PRESET_PRINCIPALS.visitor)
    expect(getPrincipal()).toEqual(PRESET_PRINCIPALS.visitor)
  })

  it('falls back to default on corrupted storage', () => {
    localStorage.setItem('ontogeny.principal', '{not json')
    expect(getPrincipal().id).toBe('u-planner')
  })
})

describe('api error unwrap', () => {
  beforeEach(() => localStorage.clear())

  it('turns backend error bodies into ApiError with code', async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ code: 'RULE_REJECTED', message: '已关闭的工单不能重复关闭' }), {
        status: 422,
        headers: { 'content-type': 'application/json' },
      }),
    )
    globalThis.fetch = fetchMock as unknown as typeof fetch
    const { apiClient } = await import('./client')
    await expect(apiClient.revisions({})).rejects.toMatchObject({
      code: 'RULE_REJECTED',
      status: 422,
      message: '已关闭的工单不能重复关闭',
    })
  })

  it('network failures become NETWORK errors', async () => {
    const fetchMock = vi.fn(async () => {
      throw new TypeError('fetch failed')
    })
    globalThis.fetch = fetchMock as unknown as typeof fetch
    const { apiClient } = await import('./client')
    const err = await apiClient.revisions({}).catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.code).toBe('NETWORK')
  })

  it('sends the principal header on every call', async () => {
    const calls: Array<{ url: string; headers: Record<string, string> }> = []
    globalThis.fetch = (async (input: any, init?: RequestInit) => {
      calls.push({ url: String(input), headers: init?.headers as Record<string, string> })
      return new Response(JSON.stringify({ signals: [] }), { headers: { 'content-type': 'application/json' } })
    }) as unknown as typeof fetch
    setPrincipal({ id: 'u-custom', Role: ['auditor'] })
    const { apiClient } = await import('./client')
    await apiClient.signals()
    expect(calls[0].headers['X-Ontogeny-Principal']).toContain('u-custom')
    expect(calls[0].url).toContain('/api/v1/evolve/signals')
  })
})
