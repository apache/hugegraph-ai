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
import { ProposalDetail } from './ProposalDetail'

const PROPOSAL = {
  id: 7,
  status: 'evaluated',
  tier: 't0-auto-merge',
  gap_kind: 'add-optional-property',
  diff: [{ mutation: 'add-optional-property', object: 'production-order', prop: 'workgroup', type: 'string' }],
  rationale: "filter field 'workgroup' used 6x on 'production-order' but is not modeled",
  // report shape as the eval endpoint stores it: per-suite dicts carrying the
  // verdict AND the suite's declared identity (display/description)
  eval_report: {
    passed: true,
    suites: {
      'production-flow-suite': {
        passed: true,
        display: 'Production flow regression suite',
        description: 'Regression assertions over orders, routing operations and stock.',
        cases: [{ kind: 'query', name: 'planned-orders-exist', ok: true }],
      },
      'quality-suite': true, // legacy boolean form must still render
    },
  },
}

const FAILED_PROPOSAL = {
  ...PROPOSAL,
  eval_report: {
    passed: false,
    suites: {
      'production-flow-suite': {
        passed: false,
        display: 'Production flow regression suite',
        description: 'Regression assertions over orders, routing operations and stock.',
        cases: [
          { kind: 'query', name: 'planned-orders-exist', ok: true },
          { kind: 'replay', action: 'release-production-order', ok: false, replays: 3, outcome_matches: 2 },
        ],
      },
    },
  },
}

const render = () => renderWithProviders(<ProposalDetail />, { path: '/evolve/7', route: '/evolve/:id' })

describe('ProposalDetail', () => {
  it('renders the diff, rationale and eval verdicts', async () => {
    mockFetch([{ match: '/meta/ontology', body: META }, { match: '/evolve/proposals/7', body: PROPOSAL }])
    render()
    await waitFor(() => expect(screen.getByText('production-order.workgroup')).toBeInTheDocument())
    expect(screen.getByText(/used 6x/)).toBeInTheDocument()
    expect(screen.getByText('all green')).toBeInTheDocument()
    // the suite's kebab-case name stays visible, and its declared identity
    // renders beside it: WHAT this suite is, not just an opaque id
    expect(screen.getByText('production-flow-suite')).toBeInTheDocument()
    expect(screen.getByText('Production flow regression suite')).toBeInTheDocument()
  })

  it('names the failed assertions when the report is red', async () => {
    mockFetch([{ match: '/meta/ontology', body: META }, { match: '/evolve/proposals/7', body: FAILED_PROPOSAL }])
    render()
    await waitFor(() => expect(screen.getByText('has failures')).toBeInTheDocument())
    // the suite badge must reflect the REAL verdict (an object report is
    // always truthy — the old bug that showed every suite as passing)
    const suite = screen.getByTestId('eval-suite-production-flow-suite')
    expect(suite).toHaveTextContent('fail')
    // and the failing case names its evidence
    expect(screen.getByText(/2\/3 replays matched/)).toBeInTheDocument()
  })

  it('shows the promotion result with tier and budget', async () => {
    mockFetch([
      { match: '/evolve/proposals/7/promote', body: { status: 'promoted', tier: 't0-auto-merge', budget_used: 1, budget_cap: 8 } },
      { match: '/evolve/proposals/7', body: PROPOSAL },
      { match: '/meta/ontology', body: META },
    ])
    render()
    await waitFor(() => expect(screen.getByTestId('promote-proposal')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('promote-proposal'))
    await waitFor(() => expect(screen.getByTestId('promote-result')).toBeInTheDocument())
    expect(screen.getByTestId('promote-result')).toHaveTextContent('promoted')
    expect(screen.getByTestId('promote-result')).toHaveTextContent('t0-auto-merge')
  })

  it('explains a constitution violation', async () => {
    mockFetch([
      { match: '/evolve/proposals/7/promote', status: 403, body: { code: 'CONSTITUTION_VIOLATION', message: 'touches the constitution surface' } },
      { match: '/evolve/proposals/7', body: { ...PROPOSAL, diff: [{ mutation: 'policy-loosen' }] } },
      { match: '/meta/ontology', body: META },
    ])
    render()
    await waitFor(() => expect(screen.getByTestId('promote-proposal')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('promote-proposal'))
    await waitFor(() => expect(screen.getByTestId('error-banner')).toHaveTextContent('CONSTITUTION_VIOLATION'))
    expect(screen.getAllByText(/constitutional surface/i).length).toBeGreaterThan(0)
  })
})
