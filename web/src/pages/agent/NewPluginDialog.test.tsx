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
/** The new-plugin dialog: the form is a thin editor over the AgentPlugin DSL
 *  resource, and its constraints are the platform's own — roles come from the
 *  Cedar vocabulary the meta exports, tools from the compiled catalog, and the
 *  submit body must be exactly what the validator expects to see. */
import { fireEvent, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { mockFetch, META } from '../../test/setup'
import { renderWithProviders } from '../../test/render'
import { NewPluginDialog, toSnake } from './NewPluginDialog'

const render = (props: Partial<Parameters<typeof NewPluginDialog>[0]> = {}) =>
  renderWithProviders(
    <NewPluginDialog open onClose={vi.fn()} existingNames={['production-copilot']} onCreated={vi.fn()} {...props} />,
    { path: '/agent', route: '/agent' },
  )

async function fillValidForm() {
  fireEvent.change(await screen.findByTestId('new-plugin-name'), { target: { value: 'qc-copilot' } })
  fireEvent.click(screen.getByTestId('new-plugin-role-technician'))
  fireEvent.click(screen.getByTestId('new-plugin-tool-describe_ontology'))
  fireEvent.click(screen.getByTestId('new-plugin-tool-search_sales_order'))
}

describe('NewPluginDialog', () => {
  it('derives the tool catalog from the meta and submits the full resource', async () => {
    const m = mockFetch([{ match: '/meta/ontology', body: META }, { match: '/admin/builder/save', body: { published: true, written: ['AgentPlugin/qc-copilot'], removed: [], issues: [], content_hash: 'abc' } }])
    render()
    await fillValidForm()
    fireEvent.click(screen.getByTestId('new-plugin-submit'))

    const call = m.calls.find((c: { url: string }) => c.url.includes('/admin/builder/save'))
    const body = JSON.parse(String(call!.init!.body))
    expect(body.resources).toHaveLength(1)
    const res = body.resources[0]
    expect(res.kind).toBe('AgentPlugin')
    expect(res.spec.principal).toMatchObject({ id: 'agent:qc-copilot', Role: ['technician'] })
    expect(res.spec.tools.allow).toEqual(['describe_ontology', 'search_sales_order'])
    expect(res.spec.approval).toEqual({ writes: 'confirm' })
    expect(await screen.findByTestId('new-plugin-done')).toHaveTextContent('qc-copilot')
  })

  it('rejects a bad name and shows the reason', async () => {
    mockFetch([{ match: '/meta/ontology', body: META }])
    render()
    fireEvent.change(await screen.findByTestId('new-plugin-name'), { target: { value: 'Bad Name' } })
    expect(screen.getByText(/Must start with a lowercase letter/)).toBeInTheDocument()
    expect(screen.getByTestId('new-plugin-submit')).toBeDisabled()
  })

  it('rejects a duplicate name', async () => {
    mockFetch([{ match: '/meta/ontology', body: META }])
    render()
    fireEvent.change(await screen.findByTestId('new-plugin-name'), { target: { value: 'production-copilot' } })
    expect(screen.getByText(/already in use/)).toBeInTheDocument()
    expect(screen.getByTestId('new-plugin-submit')).toBeDisabled()
  })

  it('requires at least one role from the Cedar vocabulary', async () => {
    mockFetch([{ match: '/meta/ontology', body: META }])
    render()
    fireEvent.change(await screen.findByTestId('new-plugin-name'), { target: { value: 'qc-copilot' } })
    // no role picked
    expect(screen.getByTestId('new-plugin-submit')).toBeDisabled()
  })

  it('warns when a never-write plugin selects action tools', async () => {
    mockFetch([{ match: '/meta/ontology', body: META }])
    render()
    fireEvent.change(await screen.findByTestId('new-plugin-name'), { target: { value: 'qc-copilot' } })
    fireEvent.click(await screen.findByTestId('new-plugin-role-technician'))
    fireEvent.click(screen.getByTestId('new-plugin-tool-describe_ontology'))
    fireEvent.click(screen.getByTestId(/new-plugin-tool-act_/))
    fireEvent.click(screen.getByText('Never write'))

    expect(await screen.findByText(/the validator will warn/)).toBeInTheDocument()
  })

  it('keeps toSnake identical to the backend tool-naming rule', () => {
    expect(toSnake('work-order')).toBe('work_order')
    expect(toSnake('Weird--Name.x')).toBe('weird_name_x')
  })

  it('inspects a clicked search tool in the right-hand pane', async () => {
    mockFetch([{ match: '/meta/ontology', body: META }])
    render()
    fireEvent.click(await screen.findByTestId('new-plugin-tool-search_sales_order'))
    const pane = screen.getByTestId('new-plugin-detail')
    expect(pane).toHaveTextContent('search_sales_order')
    expect(pane).toHaveTextContent('销售订单')
    expect(pane).toHaveTextContent('so_id')
    expect(pane).toHaveTextContent('in allow-list')
  })

  it('inspects a clicked action tool with parameters and the write note', async () => {
    mockFetch([{ match: '/meta/ontology', body: META }])
    render()
    fireEvent.click(await screen.findByTestId('new-plugin-tool-act_confirm_sales_order'))
    const pane = screen.getByTestId('new-plugin-detail')
    expect(pane).toHaveTextContent('act_confirm_sales_order')
    expect(pane).toHaveTextContent('确认销售订单')
    expect(pane).toHaveTextContent('confirmed_note')
    expect(pane).toHaveTextContent(/write tool/i)
  })
})
