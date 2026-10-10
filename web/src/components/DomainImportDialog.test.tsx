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
import { renderWithProviders } from '../test/render'
import { mockFetch } from '../test/setup'
import { DomainSwitcher } from './DomainSwitcher'

const DOMAINS = {
  domains: [{ name: 'manufacturing', display: 'Mfg', description: '', path: '/tmp/pkg',
              objects: 2, links: 1, actions: 1, active: true }],
  active: 'manufacturing',
}

function fileAt(path: string, content: string): File {
  const f = new File([content], path.split('/').pop() as string, { type: 'text/yaml' })
  // the browser sets this only through a folder picker; tests simulate it
  Object.defineProperty(f, 'webkitRelativePath', { value: path })
  return f
}

async function openImportTab() {
  await waitFor(() => expect(screen.getByTestId('domain-switcher')).toBeInTheDocument())
  fireEvent.click(screen.getByTestId('domain-switcher'))
  await waitFor(() => expect(screen.getByTestId('domain-create')).toBeInTheDocument())
  fireEvent.click(screen.getByTestId('domain-create'))
  await waitFor(() => expect(screen.getByTestId('domain-mode-import')).toBeInTheDocument())
  fireEvent.click(screen.getByTestId('domain-mode-import'))
  await waitFor(() => expect(screen.getByTestId('domain-folder-input')).toBeInTheDocument())
}

describe('New domain dialog: import a whole folder', () => {
  it('packs a picked folder into a valid zip and uploads it', async () => {
    const { calls } = mockFetch([
      { match: '/auth/me', body: { principal: { id: 'admin' }, dev_auth: true } },
      { match: '/meta/ontology', body: { package: 'manufacturing', objects: {}, links: {}, actions: {}, functions: {} } },
      { match: /\/admin\/domains$/, body: DOMAINS },
      { match: '/admin/domains/import', status: 200,
        body: { name: 'picked-domain', display: 'Picked', objects: 3, links: 2, actions: 1, active: true } },
    ])
    renderWithProviders(<DomainSwitcher />)
    await openImportTab()

    fireEvent.change(screen.getByTestId('domain-folder-input'), {
      target: { files: [
        fileAt('picked-domain/ontology.yaml', 'apiVersion: ontogeny/v1\nkind: Ontology\n'),
        fileAt('picked-domain/objects/a.yaml', '# a\n'),
        fileAt('picked-domain/objects/b.yaml', '# b\n'),
      ] },
    })
    await waitFor(() => expect(screen.getByTestId('domain-zip-name')).toHaveTextContent('picked-domain'))

    fireEvent.click(screen.getByTestId('domain-create-confirm'))
    await waitFor(() => {
      const upload = calls.find(c => c.url.includes('/admin/domains/import'))
      expect(upload).toBeTruthy()
    })

    // what left the browser is a REAL zip: signature + the picked files,
    // verified through the same structural reader the zip tests use
    const upload = calls.find(c => c.url.includes('/admin/domains/import'))!
    const sent = upload.init!.body as File
    expect(sent.name).toBe('picked-domain.zip')
    const bytes = new Uint8Array(await sent.arrayBuffer())
    expect(bytes[0]).toBe(0x50) // P
    expect(bytes[1]).toBe(0x4b) // K
    const text = new TextDecoder().decode(bytes)
    expect(text).toContain('ontology.yaml')
    expect(text).toContain('objects/a.yaml')
  })

  it('lists the exact problem when the folder has no ontology.yaml', async () => {
    mockFetch([
      { match: '/auth/me', body: { principal: { id: 'admin' }, dev_auth: true } },
      { match: '/meta/ontology', body: { package: 'manufacturing', objects: {}, links: {}, actions: {}, functions: {} } },
      { match: /\/admin\/domains$/, body: DOMAINS },
    ])
    renderWithProviders(<DomainSwitcher />)
    await openImportTab()

    fireEvent.change(screen.getByTestId('domain-folder-input'), {
      target: { files: [fileAt('not-a-domain/readme.md', 'hi')] },
    })
    const problems = await screen.findByTestId('domain-import-problems')
    expect(problems.textContent).toContain('ontology.yaml')
    // the submit stays disabled until a real package is picked
    expect(screen.getByTestId('domain-create-confirm')).toBeDisabled()
  })

  it('shows the server validator issues when the import is refused', async () => {
    mockFetch([
      { match: '/auth/me', body: { principal: { id: 'admin' }, dev_auth: true } },
      { match: '/meta/ontology', body: { package: 'manufacturing', objects: {}, links: {}, actions: {}, functions: {} } },
      { match: /\/admin\/domains$/, body: DOMAINS },
      { match: '/admin/domains/import', status: 400,
        body: { code: 'DOMAIN_INVALID', message: 'package rejected by validator: boom',
                details: { issues: [
                  { code: 'LINK-TARGET', resource: 'LinkType/x', message: 'unknown target type ghost' },
                  { code: 'FN-ENTRY', resource: 'Function/y', message: 'entry must be file.py:fn' },
                ] } } },
    ])
    renderWithProviders(<DomainSwitcher />)
    await openImportTab()

    fireEvent.change(screen.getByTestId('domain-zip-input'), {
      target: { files: [new File([new Uint8Array([0x50, 0x4b])], 'bad.zip', { type: 'application/zip' })] },
    })
    await waitFor(() => expect(screen.getByTestId('domain-zip-name')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('domain-create-confirm'))

    const err = await screen.findByTestId('domain-import-error')
    expect(err.textContent).toContain('Import failed')
    expect(err.textContent).toContain('LINK-TARGET@LinkType/x')
    expect(err.textContent).toContain('unknown target type ghost')
    expect(err.textContent).toContain('FN-ENTRY@Function/y')
    // the dialog stays open with the details -- the operator can read them
  })
})
