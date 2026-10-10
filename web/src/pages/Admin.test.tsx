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
/** Admin — the "republish" action must go through the API client.
 *
 * Regression: `publish` used a bare `fetch(...).then(r => r.json())`, which
 * skipped the principal header, the `resp.ok` check and `ApiError`
 * classification — so a 403 was rendered as a successful result and the
 * `ErrorBanner` branch could never fire. */
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { setPrincipal } from '../api/client'
import { mockFetch } from '../test/setup'
import { renderWithProviders } from '../test/render'
import { Admin } from './Admin'

const META = {
  package: 'manufacturing-system',
  content_hash: 'deadbeefcafe1234',
  objects: {},
  actions: {},
  functions: {},
  projections: {},
}

const renderRegistry = () =>
  renderWithProviders(<Admin />, { path: '/admin?tab=registry', route: '/admin' })

const baseRoutes = [
  { match: '/meta/ontology', body: META },
  { match: '/admin/llm/status', body: { configured: false } },
  { match: '/admin/extensions', body: { extensions: [], capabilities: {}, dirs: [] } },
  { match: '/graph/projection', body: { configured: false, ok: false, labels: { vertices: [], edges: [] } } },
]

describe('Admin · republish', () => {
  it('sends the dev principal override when one is chosen, and nothing when not', async () => {
    const { calls } = mockFetch([
      ...baseRoutes,
      { match: '/admin/publish', body: { content_hash: 'abc123def456' } },
    ])
    renderRegistry()
    fireEvent.click(await screen.findByTestId('republish'))
    await waitFor(() => expect(calls.some((c) => c.url.includes('/admin/publish'))).toBe(true))

    // Without an explicit override the client sends NO principal header: the
    // session cookie is the identity now, and a default preset header would
    // shadow it for every signed-in caller.
    const call = calls.find((c) => c.url.includes('/admin/publish'))!
    const headers = call.init?.headers as Record<string, string>
    expect(headers['X-Ontogeny-Principal']).toBeUndefined()
    expect(call.init?.credentials).toBe('same-origin')

    // With one chosen it is sent, which is what the CLI/CI path relies on.
    setPrincipal({ id: 'u-ci', Role: ['operator'] })
    fireEvent.click(await screen.findByTestId('republish'))
    await waitFor(() => {
      const withOverride = calls.filter((c) => c.url.includes('/admin/publish')).at(-1)!
      const h = withOverride.init?.headers as Record<string, string>
      expect(JSON.parse(h['X-Ontogeny-Principal'])).toMatchObject({ id: 'u-ci' })
    })
    setPrincipal(null)

    // and the happy path still renders the new hash
    expect(await screen.findByText(/abc123def456/)).toBeInTheDocument()
  })

  it('surfaces a rejected publish as an error instead of rendering it as data', async () => {
    mockFetch([
      ...baseRoutes,
      { match: '/admin/publish', status: 403, body: { code: 'POLICY_DENIED', message: 'policy denied' } },
    ])
    renderRegistry()
    fireEvent.click(await screen.findByTestId('republish'))

    // before the fix this branch was unreachable: the 403 body was treated as
    // success data and drawn by JsonView. One page now renders several probe
    // banners, so assert on the one that carries THIS rejection.
    const banners = await screen.findAllByTestId('error-banner')
    expect(banners.length).toBeGreaterThanOrEqual(1)
    const publishError = banners.find((b) => /POLICY_DENIED|policy denied/.test(b.textContent ?? ''))
    expect(publishError).toBeDefined()
    expect(screen.queryByTestId('republish')).toBeInTheDocument()
  })
})

describe('Admin · runtime config LLM probe', () => {
  // The probe used to be a separate "capability:llm" card; it now lives inside
  // the LLM config section it verifies. Keep the gateway-path regression
  // coverage with it: the round-trip must go through apiClient.assistantChat.
  it('probes the configured gateway in place and renders the reply', async () => {
    const { calls } = mockFetch([
      {
        match: '/admin/llm/status',
        body: { configured: true, base_url: 'http://llm.test', model: 'm1', ok: true, models: ['m1'] },
      },
      {
        match: '/admin/runtime-config',
        body: {
          llm: { provider: 'external', base_url: 'http://llm.test', model: 'm1', api_key_set: false },
          storage: { provider: 'sqlite', url: null, user: null, password_set: false },
        },
      },
      { match: '/agent/plugins', body: { plugins: [] } },
      { match: '/assistant/chat', body: { content: 'Loaded package is manufacturing-system.' } },
      ...baseRoutes,
    ])
    renderRegistry()
    fireEvent.click(await screen.findByTestId('llm-probe'))
    await waitFor(() =>
      expect(screen.getByTestId('llm-probe-result')).toHaveTextContent(/manufacturing-system/))
    expect(calls.some((c) => c.url.includes('/assistant/chat'))).toBe(true)
  })
})
