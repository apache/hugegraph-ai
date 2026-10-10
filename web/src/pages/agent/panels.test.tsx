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
/** The plugins panel must offer the create door on the EMPTY state — that is
 *  the one situation where the first plugin is needed most. Asserts the button,
 *  the dialog it opens, and that saving goes through the builder door. */
import { fireEvent, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { mockFetch, META } from '../../test/setup'
import { renderWithProviders } from '../../test/render'
import { PluginsPanel } from './panels'

describe('PluginsPanel (empty package)', () => {
  it('offers the create action on the empty state and saves the plugin', async () => {
    const m = mockFetch([
      { match: '/agent/plugins', body: { plugins: [] } },
      { match: '/meta/ontology', body: META },
      { match: '/admin/builder/save', body: { published: true, written: ['AgentPlugin/qc-copilot'], removed: [], issues: [], content_hash: 'abc' } },
    ])
    renderWithProviders(<PluginsPanel />, { path: '/agent/manage', route: '/agent/manage' })

    expect(await screen.findByText(/No AgentPlugin declared/)).toBeInTheDocument()
    fireEvent.click(await screen.findByTestId('new-plugin-open'))
    expect(await screen.findByTestId('new-plugin-dialog')).toBeInTheDocument()

    fireEvent.change(screen.getByTestId('new-plugin-name'), { target: { value: 'qc-copilot' } })
    fireEvent.click(screen.getByTestId('new-plugin-role-technician'))
    fireEvent.click(screen.getByTestId('new-plugin-tool-describe_ontology'))
    fireEvent.click(screen.getByTestId('new-plugin-submit'))

    const call = m.calls.find((c: { url: string }) => c.url.includes('/admin/builder/save'))
    expect(call).toBeDefined()
    const body = JSON.parse(String(call!.init!.body))
    expect(body.resources[0]).toMatchObject({ kind: 'AgentPlugin', metadata: { name: 'qc-copilot' } })
    expect(await screen.findByTestId('new-plugin-done')).toHaveTextContent('qc-copilot')
  })
})
