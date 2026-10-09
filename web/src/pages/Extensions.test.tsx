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
import { fireEvent, screen, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { mockFetch } from '../test/setup'
import { renderWithProviders } from '../test/render'
import { ExtensionsPanel } from './Extensions'

const render = () => renderWithProviders(<ExtensionsPanel />, { path: '/admin', route: '/admin' })

const INVENTORY = {
  extensions: [
    {
      name: 'llm-ollama',
      kind: 'llm-provider',
      display: 'Ollama LLM 适配器',
      description: 'platform LLM gateway over /api/chat',
      provides: ['capability:llm'],
      requires: [],
      entry: 'ontogeny_ext_ollama:register',
      status: 'loaded',
      error: null,
      path: '/repo/extensions/llm-ollama',
    },
    {
      name: 'agent-builtin-llm',
      kind: 'agent-engine',
      display: '内置 LLM Agent 引擎',
      description: 'reference builtin-llm engine',
      provides: [],
      requires: [],
      entry: 'ontogeny_ext_agent_llm:register',
      status: 'loaded',
      error: null,
      path: '/repo/extensions/agent-builtin-llm',
    },
    {
      name: 'legacy-experiment',
      kind: 'generic',
      display: 'Legacy experiment',
      description: 'broken on purpose',
      provides: [],
      requires: [],
      entry: 'pkg_legacy:register',
      status: 'error',
      error: 'RuntimeError: nope',
      path: '/repo/extensions/legacy-experiment',
    },
  ],
  capabilities: { 'capability:llm': { extension: 'llm-ollama' } },
  dirs: ['/repo/extensions'],
}

const PLUGINS = {
  plugins: [
    {
      name: 'production-copilot',
      display: '生产协作者（只读）',
      description: '',
      transport: 'http',
      engine: { kind: 'builtin-llm', endpoint: null },
      principal: { id: 'agent:production-copilot' },
      approval: 'never',
      budget: { steps: 40, wall_ms: 120000, writes_per_session: 0 },
      tools: {},
    },
  ],
}

function mockScenario() {
  return mockFetch([
    { match: '/admin/extensions', body: INVENTORY },
    {
      match: '/admin/llm/status',
      body: { configured: true, base_url: 'http://ollama.test', model: 'm1', ok: true, models: ['m1'] },
    },
    {
      match: '/graph/projection',
      body: { configured: false, ok: false, reason: 'no projection declared' },
    },
    { match: '/agent/plugins', body: PLUGINS },
    { match: '/admin/projection/rebuild', body: { vertices: 35, edges: 25 } },
    { match: '/assistant/chat', body: { content: 'Loaded package is manufacturing-system.' } },
    {
      match: /\/agent\/sessions$/,
      body: {
        id: 7, plugin: 'production-copilot', principal: 'agent:production-copilot',
        task: 'demo', status: 'open', budget: { steps: 40, wall_ms: 1, writes: 0, writes_used: 0, steps_used: 0 },
        catalog_hash: 'x', created_at: null, tools: {},
      },
    },
    { match: /\/agent\/sessions\/7\/run/, body: { id: 7, status: 'running' } },
    {
      match: /\/agent\/sessions\/7$/,
      body: {
        id: 7, plugin: 'production-copilot', principal: 'agent:production-copilot',
        task: 'demo', status: 'finished',
        result: { final: '两张 OPEN 工单，建议先派 WO-1。' },
        budget: { steps: 40, wall_ms: 1, writes: 0, writes_used: 0, steps_used: 3 },
        catalog_hash: 'x', created_at: null,
        steps: [{ seq: 1 }, { seq: 2 }, { seq: 3 }],
      },
    },
  ])
}

describe('Extensions', () => {
  it('renders the inventory with statuses, capabilities and errors', async () => {
    mockScenario()
    render()
    await waitFor(() =>
      expect(screen.getByTestId('ext-card-llm-ollama')).toBeInTheDocument())
    expect(screen.getByText('Ollama LLM 适配器')).toBeInTheDocument()
    expect(screen.getByText('capability:llm')).toBeInTheDocument()
    expect(screen.getByText('RuntimeError: nope')).toBeInTheDocument()
  })

  it('drives the agent scenario: open session -> run -> show final', async () => {
    const { calls } = mockScenario()
    render()
    await waitFor(() => expect(screen.getByTestId('agent-probe-production-copilot')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('agent-probe-production-copilot'))
    await waitFor(() =>
      expect(screen.getByTestId('agent-probe-result')).toHaveTextContent(/WO-1/))
    expect(calls.some((c) => /\/agent\/sessions$/.test(c.url))).toBe(true)
    expect(calls.some((c) => /\/agent\/sessions\/7\/run/.test(c.url))).toBe(true)
  })
})
