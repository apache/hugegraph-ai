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
import { describe, expect, it, vi } from 'vitest'
import { mockFetch, META } from '../test/setup'
import { renderWithProviders } from '../test/render'
import { AgentConsoleBody } from './AgentConsole'
import { AgentConsole } from './AgentConsole'
import { AgentManagement } from './AgentManagement'

const PLUGIN = {
  name: 'maintenance-copilot',
  display: '维修协作者',
  transport: 'http',
  engine: { kind: 'builtin-llm' },
  principal: { id: 'agent:maintenance-copilot', Role: ['maintenance_supervisor'], site: 'north' },
  approval: 'confirm',
  budget: { steps: 25, wall_ms: 60000, writes_per_session: 3 },
  tools: {
    describe_ontology: { name: 'describe_ontology', kind: 'meta', description: 'meta', writes: false, input_schema: {} },
    search_work_order: { name: 'search_work_order', kind: 'search', target: 'work-order', description: 'search', writes: false, input_schema: {} },
    act_close_work_order: { name: 'act_close_work_order', kind: 'act', target: 'close-work-order', description: 'write', writes: true, input_schema: {} },
  },
}

const SESSION = {
  id: 1, plugin: 'maintenance-copilot', principal: 'agent:maintenance-copilot',
  task: 'close WO-1001', status: 'open', catalog_hash: 'abc123',
  budget: { steps: 25, wall_ms: 60000, writes: 3, writes_used: 1, steps_used: 3 },
  created_at: '2026-09-18T08:00:00+00:00',
}

const DETAIL = {
  ...SESSION,
  steps: [
    { seq: 1, tool: 'search_work_order', args: '{}', outcome: 'ok', latency_ms: 3.2,
      thought: '先确认这张工单现在的状态。', revision_id: null, approval_id: null },
    { seq: 2, tool: 'act_close_work_order', args: '{"target_id":"WO-1001"}', outcome: 'pending_approval',
      latency_ms: 5.1, thought: '工单还是 OPEN，需要人工批准才能关闭。', revision_id: null, approval_id: 7 },
  ],
}

const APPROVAL = {
  id: 7, session_id: 1, plugin: 'maintenance-copilot', tool: 'act_close_work_order',
  action: 'close-work-order', parameters: { resolution: 'copilot 建议' }, target_id: 'WO-1001',
  rationale: '工单状态 OPEN', status: 'pending', requested_at: '2026-09-18T08:01:00+00:00',
}

const renderConsole = () =>
  renderWithProviders(<AgentConsole />, { path: '/agent', route: '/agent' })

/* --------------------------------------------------------------- console */

describe('AgentConsole — one conversation, three modes', () => {
  it('opens on Agent run with the session picker left of the input', async () => {
    mockFetch([
      { match: '/agent/plugins', body: { plugins: [PLUGIN] } },
      { match: '/agent/sessions', body: { sessions: [] } },
      { match: '/meta/ontology', body: META },
    ])
    renderConsole()
    await waitFor(() => expect(screen.getByTestId('mode-agent')).toHaveAttribute('aria-selected', 'true'))
    expect(screen.getByText(/hand a task to an agent/i)).toBeInTheDocument()
    // the composer carries all three modes, and the picker sits by the input
    expect(screen.getByTestId('mode-propose')).toBeInTheDocument()
    expect(screen.getByTestId('mode-qa')).toBeInTheDocument()
    expect(screen.getByTestId('agent-session-picker')).toBeInTheDocument()
    expect(screen.getByTestId('chat-input')).toBeInTheDocument()
  })

  it('sends a grounded question and renders the answer', async () => {
    const { calls } = mockFetch([
      { match: '/agent/plugins', body: { plugins: [PLUGIN] } },
      { match: '/agent/sessions', body: { sessions: [] } },
      { match: '/meta/ontology', body: META },
      { match: '/assistant/chat', body: { content: 'Sales orders reach production via production orders.' } },
    ])
    renderConsole()
    await waitFor(() => expect(screen.getByTestId('mode-qa')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('mode-qa'))
    fireEvent.change(screen.getByTestId('chat-input'), { target: { value: 'how does an order reach production?' } })
    fireEvent.click(screen.getByTestId('chat-send'))
    await waitFor(() => expect(screen.getByText(/reach production via production orders/)).toBeInTheDocument())
    const body = JSON.parse(String(calls.find((c) => c.url.includes('/assistant/chat'))!.init?.body))
    expect(body.messages.at(-1)).toEqual({ role: 'user', content: 'how does an order reach production?' })
    expect(body.propose).toBe(false)
  })

  it('propose mode drafts a mutation diff and shows the reasoning', async () => {
    const { calls } = mockFetch([
      { match: '/agent/plugins', body: { plugins: [PLUGIN] } },
      { match: '/agent/sessions', body: { sessions: [] } },
      { match: '/meta/ontology', body: META },
      {
        match: '/assistant/chat',
        body: {
          content: 'Consider modelling the missing attribute.',
          thinking: 'the operator keeps filtering on it',
          proposals: [{ mutation: 'add-optional-property', object: 'production-order', prop: 'workgroup', type: 'string' }],
        },
      },
    ])
    renderConsole()
    await waitFor(() => expect(screen.getByTestId('mode-propose')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('mode-propose'))
    fireEvent.change(screen.getByTestId('chat-input'), { target: { value: 'what is missing?' } })
    fireEvent.click(screen.getByTestId('chat-send'))
    await waitFor(() => expect(screen.getByText('production-order.workgroup')).toBeInTheDocument())
    expect(screen.getByText('the operator keeps filtering on it')).toBeInTheDocument()
    expect(screen.getByText(/Drafts never take effect/i)).toBeInTheDocument()
    const body = JSON.parse(String(calls.find((c) => c.url.includes('/assistant/chat'))!.init!.body))
    expect(body.propose).toBe(true)
  })

  it('explains an unconfigured assistant (503)', async () => {
    mockFetch([
      { match: '/agent/plugins', body: { plugins: [PLUGIN] } },
      { match: '/agent/sessions', body: { sessions: [] } },
      { match: '/meta/ontology', body: META },
      { match: '/assistant/chat', status: 503, body: { code: 'HTTP_503', message: 'assistant requires ONTOGENY_LLM_BASE_URL' } },
    ])
    renderConsole()
    await waitFor(() => expect(screen.getByTestId('mode-qa')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('mode-qa'))
    fireEvent.change(screen.getByTestId('chat-input'), { target: { value: 'hi' } })
    fireEvent.click(screen.getByTestId('chat-send'))
    await waitFor(() => expect(screen.getByTestId('error-banner')).toBeInTheDocument())
    expect(screen.getByTestId('error-banner')).toHaveTextContent('ONTOGENY_LLM_BASE_URL')
  })

  it('agent mode: the session picker opens a new session and streams the step trace', async () => {
    const RUN = {
      ...SESSION, id: 2, task: 'inventory OPEN work orders', status: 'finished',
      steps: [
        {
          seq: 1, tool: 'search_work_order', args: '{}', outcome: 'ok', latency_ms: 4,
          thought: '先看 OPEN 工单再决定优先级。', revision_id: null, approval_id: null,
        },
      ],
      result: { final: 'WO-1001 first: its line is DOWN.', thought: '只剩一张高优先级工单，可以收尾了。' },
    }
    const { calls } = mockFetch([
      { match: '/agent/plugins', body: { plugins: [PLUGIN] } },
      {
        match: /\/agent\/sessions$/,
        body: (_url: string, init?: RequestInit) =>
          init?.method === 'POST' ? { ...RUN, status: 'open', steps: [], result: null } : { sessions: [] },
      },
      { match: /\/agent\/sessions\/2\/run$/, body: { id: 2, status: 'running' } },
      { match: /\/agent\/sessions\/2$/, body: RUN },
    ])
    renderConsole()
    // Agent run is the default mode; the picker sits left of the input and
    // offers the plugin as a new session
    const picker = await waitFor(() => {
      const el = screen.getByTestId('agent-session-picker')
      expect(el).toHaveValue('new:maintenance-copilot')
      return el
    })
    fireEvent.change(screen.getByTestId('chat-input'), { target: { value: 'inventory OPEN work orders' } })
    fireEvent.click(screen.getByTestId('chat-send'))
    expect(picker).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('agent-run-2')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByText(/WO-1001 first/)).toBeInTheDocument())
    expect(screen.getByTestId('agent-run-2').textContent).toContain('search_work_order')
    // the dialog shows the decision process, not just the tool calls
    expect(screen.getByTestId('step-thought-1')).toHaveTextContent('先看 OPEN 工单再决定优先级。')
    expect(screen.getByTestId('run-final-thought')).toHaveTextContent('只剩一张高优先级工单，可以收尾了。')
    expect(calls.some((c) => String(c.url).endsWith('/agent/sessions/2/run'))).toBe(true)
  })

  it('agent mode: picking an existing session shows its trace and flags a blocked write', async () => {
    mockFetch([
      { match: '/agent/plugins', body: { plugins: [PLUGIN] } },
      { match: /\/agent\/sessions$/, body: { sessions: [{ ...SESSION, status: 'blocked_on_approval' }] } },
      { match: /\/agent\/sessions\/1$/, body: { ...DETAIL, status: 'blocked_on_approval' } },
    ])
    renderConsole()
    const picker = await waitFor(() => {
      const el = screen.getByTestId('agent-session-picker')
      // the existing session must be in the list before we select it
      expect(within(el).getByText(/#1 · close WO-1001/)).toBeInTheDocument()
      return el
    })
    fireEvent.change(picker, { target: { value: 's:1' } })
    await waitFor(() => expect(screen.getByTestId('agent-run-1')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByText('appr:7')).toBeInTheDocument())
    expect(screen.getByText('pending approval')).toBeInTheDocument()
    expect(screen.getByText(/awaiting human approval/i)).toBeInTheDocument()
  })
})

/* --------------------------------------------------------------- sessions */

describe('Agent sessions management — sessions tab', () => {
  const render = (path = '/agent/manage') =>
    renderWithProviders(<AgentManagement />, { path, route: '/agent/manage' })

  it('is one surface with a tab bar over sessions, pending writes and plugins', async () => {
    mockFetch([
      { match: '/agent/plugins', body: { plugins: [PLUGIN] } },
      { match: /\/agent\/sessions(\?.*)?$/, body: { sessions: [SESSION] } },
      { match: '/agent/approvals', body: { approvals: [] } },
    ])
    render()
    await waitFor(() => expect(screen.getByTestId('tab-sessions')).toHaveAttribute('aria-selected', 'true'))
    expect(screen.getByTestId('tab-approvals')).toBeInTheDocument()
    expect(screen.getByTestId('tab-plugins')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('tab-approvals'))
    await waitFor(() => expect(screen.getByText('No pending write requests')).toBeInTheDocument())

    fireEvent.click(screen.getByTestId('tab-plugins'))
    await waitFor(() => expect(screen.getByText('maintenance-copilot')).toBeInTheDocument())
  })

  it('renders the step timeline with the agent reasoning, outcome badges and approval refs', async () => {
    mockFetch([
      { match: '/agent/plugins', body: { plugins: [PLUGIN] } },
      { match: /\/agent\/sessions(\?.*)?$/, body: { sessions: [SESSION] } },
      { match: /\/agent\/sessions\/\d+$/, body: DETAIL },
    ])
    render()
    // open the session row: the plugin name appears in the <option> and in the
    // list row; click the list-row cell (row onClick opens the detail pane)
    const row = await screen.findByTestId('session-row-1')
    fireEvent.click(row)
    await waitFor(() => expect(screen.getByTestId('plugin-example')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByText('appr:7')).toBeInTheDocument())
    await waitFor(() => expect(screen.getByText('pending approval')).toBeInTheDocument())
    expect(screen.getByText(/act_close_work_order/)).toBeInTheDocument()
    // the reasoning behind the write is visible to the approver
    expect(screen.getByTestId('step-thought-2')).toHaveTextContent('工单还是 OPEN，需要人工批准才能关闭。')
  })

  it('creates a session from the dialog and summons the dock via Agent 运行', async () => {
    const { calls } = mockFetch([
      { match: '/agent/plugins', body: { plugins: [PLUGIN] } },
      { match: /\/agent\/sessions(\?.*)?$/,
        body: (_url: string, init?: RequestInit) =>
          init?.method === 'POST'
            ? { id: 1, plugin: 'maintenance-copilot', principal: 'agent:maintenance-copilot',
                task: '巡检产线', status: 'open', catalog_hash: 'abc123',
                budget: { steps: 0, wall_ms: 0, writes: 0, writes_used: 0, steps_used: 0 },
                created_at: '2026-09-18T08:05:00+00:00', steps: [], result: null,
                run_count: 0, expires_at: null }
            : { sessions: [SESSION] } },
      { match: /\/agent\/sessions\/\d+$/, body: DETAIL },
    ])
    const dispatchSpy = vi.spyOn(window, 'dispatchEvent')
    render()
    // direction 1: creation lives in the dialog -- plugin + description,
    // budgets default unlimited, expiry default none. It does NOT run.
    fireEvent.click(screen.getByTestId('create-session'))
    // React's valueTracker swallows programmatic select changes inside a
    // portal: set the value via the native setter, then bubble a real change
    const pluginSelect = (await screen.findByTestId('create-plugin')) as HTMLSelectElement
    await waitFor(() => expect(pluginSelect.options.length).toBeGreaterThan(1))
    const nativeSetter = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!
    nativeSetter.call(pluginSelect, 'maintenance-copilot')
    pluginSelect.dispatchEvent(new Event('change', { bubbles: true }))
    fireEvent.change(screen.getByTestId('create-task'), { target: { value: '巡检产线，盯住 DOWN 的设备' } })
    fireEvent.click(screen.getByTestId('create-session-submit'))
    await waitFor(() => expect(screen.queryByTestId('create-session-dialog')).toBeNull(), { timeout: 3000 })
    await waitFor(() => expect(screen.getByTestId('plugin-example')).toBeInTheDocument(), { timeout: 3000 })
    expect(calls.some((c: { url: string }) => c.url.endsWith('/run'))).toBe(false)
    // "Agent 运行" summons the bottom-right dock, auto-selecting THIS session
    fireEvent.click(screen.getByTestId('plugin-example'))
    const evt = dispatchSpy.mock.calls.map(([e]) => e as CustomEvent)
      .find((e) => e.type === 'ontogeny:agent-dock-open')
    expect(evt?.detail).toMatchObject({ sessionId: 1 })
  })

  it('drives the session from the dock composer, carrying THIS run instruction', async () => {
    const { calls } = mockFetch([
      { match: '/agent/plugins', body: { plugins: [PLUGIN] } },
      { match: /\/agent\/sessions(\?.*)?$/, body: { sessions: [SESSION] } },
      { match: /\/agent\/sessions\/\d+$/, body: DETAIL },
      { match: /\/agent\/sessions\/\d+\/run$/, body: { id: 1, status: 'running' } },
    ])
    renderWithProviders(<AgentConsoleBody presetSessionId={1} />, { path: '/agent/manage', route: '/agent/manage' })
    // the preset auto-selected the session: an empty composer has nothing to
    // execute, so the send button is disabled
    await screen.findByTestId('chat-input')
    expect(screen.getByTestId('chat-send')).toBeDisabled()
    // the composer is the command input: its text is THIS drive's instruction
    fireEvent.change(screen.getByTestId('chat-input'), { target: { value: '盘点 DOWN 设备并列出受影响的工单' } })
    expect(screen.getByTestId('chat-send')).toBeEnabled()
    fireEvent.click(screen.getByTestId('chat-send'))
    await waitFor(() => {
      const run = calls.find((c: { url: string }) => c.url.endsWith('/agent/sessions/1/run'))
      expect(run).toBeTruthy()
      expect(JSON.parse(String(run!.init?.body))).toEqual({ task: '盘点 DOWN 设备并列出受影响的工单' })
    })
  })

  it('surfaces a missing LLM when the composer run fails', async () => {
    mockFetch([
      { match: '/agent/plugins', body: { plugins: [PLUGIN] } },
      { match: /\/agent\/sessions(\?.*)?$/, body: { sessions: [SESSION] } },
      { match: /\/agent\/sessions\/\d+$/, body: DETAIL },
      { match: /\/agent\/sessions\/\d+\/run$/, status: 500,
        body: { code: 'LLM_NOT_CONFIGURED', message: 'requires ONTOGENY_LLM_BASE_URL', details: { code: 'LLM_NOT_CONFIGURED' } } },
    ])
    renderWithProviders(<AgentConsoleBody presetSessionId={1} />, { path: '/agent/manage', route: '/agent/manage' })
    fireEvent.change(await screen.findByTestId('chat-input'), { target: { value: '盘点 DOWN 设备' } })
    fireEvent.click(screen.getByTestId('chat-send'))
    await waitFor(() => expect(screen.getAllByText(/ONTOGENY_LLM_BASE_URL/).length).toBeGreaterThan(0))
  })

  it('streams the finished drive back into the dock transcript', async () => {
    const FINISHED = { ...DETAIL, status: 'finished', result: { final: 'WO-1001 first: its line is DOWN and due tomorrow.' } }
    mockFetch([
      { match: '/agent/plugins', body: { plugins: [PLUGIN] } },
      { match: /\/agent\/sessions(\?.*)?$/, body: { sessions: [SESSION] } },
      { match: /\/agent\/sessions\/\d+$/, body: FINISHED },
      { match: /\/agent\/sessions\/\d+\/run$/, body: { id: 1, status: 'running' } },
    ])
    renderWithProviders(<AgentConsoleBody presetSessionId={1} />, { path: '/agent/manage', route: '/agent/manage' })
    fireEvent.change(await screen.findByTestId('chat-input'), { target: { value: '盘点 DOWN 设备' } })
    fireEvent.click(screen.getByTestId('chat-send'))
    await waitFor(() => expect(screen.getByText(/WO-1001 first/)).toBeInTheDocument())
  })

  it('prompts to approve and resume when the session is blocked', async () => {
    mockFetch([
      { match: '/agent/plugins', body: { plugins: [PLUGIN] } },
      { match: /\/agent\/sessions(\?.*)?$/, body: { sessions: [{ ...SESSION, status: 'blocked_on_approval' }] } },
      { match: /\/agent\/sessions\/\d+$/, body: { ...DETAIL, status: 'blocked_on_approval' } },
    ])
    render()
    fireEvent.click(await screen.findByTestId('session-row-1'))
    await waitFor(() => expect(screen.getByTestId('go-approvals')).toBeInTheDocument())
    expect(screen.getByText(/awaiting human approval/)).toBeInTheDocument()
  })
})

/* -------------------------------------------------------------- approvals */

describe('Agent sessions management — approvals tab', () => {
  const render = () => renderWithProviders(<AgentManagement />, { path: '/agent/manage?tab=approvals', route: '/agent/manage' })

  it('queues pending writes, posts the decision and shows the decided trail', async () => {
    const { calls } = mockFetch([
      { match: (url: string) => url.includes('/agent/approvals') && url.includes('status=decided'),
        body: { approvals: [{ ...APPROVAL, status: 'executed', decided_by: 'u-sup', decided_at: '2026-09-28T10:00:00+00:00' }] } },
      { match: '/agent/approvals', body: { approvals: [APPROVAL] } },
      { match: '/decision', body: { id: 7, status: 'executed', revision_id: 42 } },
    ])
    render()
    await waitFor(() => expect(screen.getAllByText('close-work-order').length).toBeGreaterThanOrEqual(1))
    expect(screen.getByText(/copilot 建议/)).toBeInTheDocument()
    // direction 1: the decided audit trail renders next to the queue
    expect(await screen.findByText('executed')).toBeInTheDocument()
    expect(screen.getByText(/u-sup/)).toBeInTheDocument()
    fireEvent.click(screen.getByTestId('approve-7'))
    await waitFor(() => {
      const decision = calls.find((c: { url: string }) => c.url.includes('/decision'))
      expect(decision).toBeTruthy()
      expect(JSON.parse(String(decision!.init?.body))).toEqual({ decision: 'approved' })
    })
  })

  it('shows the empty approvals queue', async () => {
    mockFetch([{ match: '/agent/approvals', body: { approvals: [] } }])
    render()
    await waitFor(() => expect(screen.getByText('No pending write requests')).toBeInTheDocument())
  })
})

/* ---------------------------------------------------------------- plugins */

describe('Agent sessions management — plugins tab', () => {
  const render = () => renderWithProviders(<AgentManagement />, { path: '/agent/manage?tab=plugins', route: '/agent/manage' })

  it('lists plugins with principal, budget and the write/read tool split', async () => {
    mockFetch([{ match: '/agent/plugins', body: { plugins: [PLUGIN] } }])
    render()
    await waitFor(() => expect(screen.getByText('maintenance-copilot')).toBeInTheDocument())
    expect(screen.getByText(/approval required/)).toBeInTheDocument()
    expect(screen.getByText(/agent:maintenance-copilot/)).toBeInTheDocument()
    expect(screen.getAllByText('act_close_work_order').length).toBeGreaterThanOrEqual(1)
  })

  it('shows an empty-state hint when the package declares no plugin', async () => {
    mockFetch([{ match: '/agent/plugins', body: { plugins: [] } }])
    render()
    await waitFor(() => expect(screen.getByText(/No AgentPlugin declared/)).toBeInTheDocument())
  })
})
