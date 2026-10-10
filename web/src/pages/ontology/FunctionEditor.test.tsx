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
import { renderWithProviders } from '../../test/render'
import { mockFetch } from '../../test/setup'
import { FunctionEditor } from './editors'
import type { OntologyResource } from '../../api/types'

const FN: OntologyResource = {
  apiVersion: 'ontogeny/v1',
  kind: 'Function',
  metadata: { name: 'capacity-check' },
  spec: {
    runtime: 'python',
    entry: 'capacity.py:capacity_check',
    parameters: { work_center_id: { type: 'string', required: true } },
    capabilities: [{ 'read-objects': ['work-center'] }],
  },
} as unknown as OntologyResource

const props = {
  resource: FN,
  update: () => {},
  rename: () => {},
  objectNames: ['work-center'],
  policyNames: [],
}

const sourceRoute = (body: Record<string, unknown>) => ({
  match: (url: string) => url.includes('/functions/capacity-check/source'),
  body,
})

describe('FunctionEditor runtime code section', () => {
  it('seeds a commented skeleton when the file does not exist yet', async () => {
    mockFetch([sourceRoute({
      name: 'capacity-check', runtime: 'python', entry: 'capacity.py:capacity_check',
      path: '/pkg/functions/capacity.py', exists: false, source: null, capabilities: [],
    })])
    renderWithProviders(<FunctionEditor {...props} />)

    const editor = await screen.findByTestId('function-source')
    // skeleton: named after the entry, runnable guidance present
    expect(editor).toHaveTextContent('capacity_check')
    expect(editor).toHaveTextContent('ontogeny.query')
    // missing-file state is said out loud (badge + alert), and saving
    // (creating the file) is offered
    expect(await screen.findAllByText(/Code file missing/).then((els) => els.length >= 1)).toBe(true)
    expect(screen.getByTestId('function-source-save')).toBeEnabled()
  })

  it('hides the license header from the editor and restores it verbatim on save', async () => {
    const licensed = '# Copyright 2026 Apache HugeGraph Authors\n#\n# Licensed under the Apache License, Version 2.0\n# limitations under the License.\n\ndef capacity_check():\n    return {"ok": True}\n'
    const { calls } = mockFetch([
      sourceRoute({
        name: 'capacity-check', runtime: 'python', entry: 'capacity.py:capacity_check',
        path: '/pkg/functions/capacity.py', exists: true, source: licensed, capabilities: [],
      }),
      { match: (url: string) => url.includes('/functions/capacity-check/source'),
        status: 200, body: { ok: true, changed: true, version: 'v2', bytes: 10 } },
    ])
    // route PUT through the generic mock: match by method inside body fn
    renderWithProviders(<FunctionEditor {...props} />)

    const editor = await screen.findByTestId('function-source')
    // legal text is NOT shown; the code is
    expect(editor.textContent).not.toContain('Copyright 2026')
    expect(editor.textContent).toContain('def capacity_check')

    // save sends license + edited body stitched back together
    fireEvent.change(screen.getByTestId('function-source').querySelector('textarea') as Element, {
      target: { value: 'def capacity_check():\n    return {"ok": False}\n' },
    })
    fireEvent.click(screen.getByTestId('function-source-save'))
    await waitFor(() => {
      const put = calls.find(c => c.url.includes('/source') && c.init?.method === 'PUT')
      expect(put).toBeTruthy()
      const sent = JSON.parse(String(put!.init!.body))
      expect(sent.source.startsWith('# Copyright 2026 Apache HugeGraph Authors')).toBe(true)
      expect(sent.source).toContain('limitations under the License')
      expect(sent.source).toContain('return {"ok": False}')
    })
  })

  it('shows an existing but EMPTY file as empty, never as a skeleton (Bug C regression)', async () => {
    mockFetch([sourceRoute({
      name: 'capacity-check', runtime: 'python', entry: 'capacity.py:capacity_check',
      path: '/pkg/functions/capacity.py', exists: true, source: '', capabilities: [],
    })])
    renderWithProviders(<FunctionEditor {...props} />)

    const editor = await screen.findByTestId('function-source')
    await waitFor(() => {
      const textarea = editor.querySelector('textarea') as HTMLTextAreaElement
      expect(textarea.value).toBe('')
    })
    // nothing was invented for the user to accidentally save
    expect(screen.getByTestId('function-source-save')).toBeDisabled()
  })

  it('runs a test against the buffer and reports the result without saving', async () => {
    const { calls } = mockFetch([
      sourceRoute({
        name: 'capacity-check', runtime: 'python', entry: 'capacity.py:capacity_check',
        path: '/pkg/functions/capacity.py', exists: true,
        source: 'def capacity_check():\n    return {"ok": True}\n', capabilities: [],
      }),
      {
        match: (url: string) => url.includes('/functions/capacity-check/test'),
        body: { ok: true, value: { ok: true }, params: { work_center_id: 'WC-01' },
                param_sources: { work_center_id: 'real id from work-center' } },
      },
    ])
    renderWithProviders(<FunctionEditor {...props} />)
    await screen.findByTestId('function-source')

    fireEvent.click(screen.getByTestId('function-test-run'))
    const result = await screen.findByTestId('function-test-result')
    expect(result).toHaveTextContent('Test run succeeded')
    expect(result).toHaveTextContent('WC-01')

    // the test went to POST .../test; nothing was written to the source file
    const tested = calls.find((c) => c.url.includes('/functions/capacity-check/test'))
    expect(tested?.init?.method).toBe('POST')
    expect(calls.filter((c) => c.url.includes('/source') && c.init?.method === 'PUT')).toHaveLength(0)
  })
})
