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
import { mockFetch, META } from '../test/setup'
import { renderWithProviders } from '../test/render'
import { ActionRunner } from './ActionRunner'

const render = () =>
  renderWithProviders(<ActionRunner />, { path: '/actions/confirm-sales-order', route: '/actions/:name' })

function fill() {
  fireEvent.change(screen.getByLabelText(/target object id/i), { target: { value: 'SO-2026-0001' } })
}

describe('ActionRunner', () => {
  it('dry-run shows rule verdicts and the policy decision', async () => {
    mockFetch([
      { match: '/meta/ontology', body: META },
      {
        match: '/actions/confirm-sales-order/validate',
        body: {
          parameters: {},
          rules: [{ expr: "target.status == 'DRAFT'", ok: true, message: null }],
          policy: { allow: true, reason: 'permit by sales-policies' },
        },
      },
    ])
    render()
    await waitFor(() => expect(screen.getByTestId('validate-action')).toBeInTheDocument())
    fill()
    fireEvent.click(screen.getByTestId('validate-action'))
    await waitFor(() => expect(screen.getByTestId('validate-result')).toBeInTheDocument())
    expect(screen.getByText("target.status == 'DRAFT'")).toBeInTheDocument()
    expect(screen.getByText('permitted')).toBeInTheDocument()
  })

  it('execute renders the revision and the resulting object', async () => {
    mockFetch([
      { match: '/meta/ontology', body: META },
      { match: '/actions/confirm-sales-order/execute', body: { revision_id: 42, outcome: 'executed', object_id: 'SO-2026-0001', after: { status: 'CONFIRMED' } } },
    ])
    render()
    await waitFor(() => expect(screen.getByTestId('execute-action')).toBeInTheDocument())
    fill()
    fireEvent.click(screen.getByTestId('execute-action'))
    await waitFor(() => expect(screen.getByTestId('execute-result')).toBeInTheDocument())
    expect(screen.getByText('#42')).toBeInTheDocument()
    expect(screen.getByText('executed')).toBeInTheDocument()
  })

  it('renders a rule rejection with its code and localized hint', async () => {
    mockFetch([
      { match: '/meta/ontology', body: META },
      { match: '/actions/confirm-sales-order/execute', status: 422, body: { code: 'RULE_REJECTED', message: '只有草稿状态的订单可以确认' } },
    ])
    render()
    await waitFor(() => expect(screen.getByTestId('execute-action')).toBeInTheDocument())
    fill()
    fireEvent.click(screen.getByTestId('execute-action'))
    await waitFor(() => expect(screen.getByTestId('error-banner')).toBeInTheDocument())
    expect(screen.getByTestId('error-banner')).toHaveTextContent('RULE_REJECTED')
    expect(screen.getByTestId('error-banner')).toHaveTextContent('只有草稿状态的订单可以确认')
  })

  it('renders a policy denial hint', async () => {
    mockFetch([
      { match: '/meta/ontology', body: META },
      { match: '/actions/confirm-sales-order/execute', status: 403, body: { code: 'POLICY_DENIED', message: 'default deny' } },
    ])
    render()
    await waitFor(() => expect(screen.getByTestId('execute-action')).toBeInTheDocument())
    fill()
    fireEvent.click(screen.getByTestId('execute-action'))
    await waitFor(() => expect(screen.getByTestId('error-banner')).toHaveTextContent('POLICY_DENIED'))
  })
})
