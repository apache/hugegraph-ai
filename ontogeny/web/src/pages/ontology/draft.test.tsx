/*
Licensed to the Apache Software Foundation (ASF) under one
or more contributor license agreements.  See the NOTICE file
distributed with this work for additional information
regarding copyright ownership.  The ASF licenses this file
to you under the Apache License, Version 2.0 (the
"License"); you may not use this file except in compliance
with the License.  You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing,
software distributed under the License is distributed on an
"AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.  See the License for the
specific language governing permissions and
limitations under the License.
*/
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
import { useEffect } from 'react'
import { act, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { apiClient, ApiError } from '../../api/client'
import type { OntologyResource } from '../../api/types'
import { renderWithProviders } from '../../test/render'
import { OntologyDraftProvider, useOntologyDraft, type OntologyDraft } from './draft'

const KEY = 'ontogeny.ontology.draft'
const resource: OntologyResource = {
  apiVersion: 'ontogeny/v1', kind: 'ObjectType', metadata: { name: 'order', display: 'Published' },
  spec: { primaryKey: ['id'], properties: { id: { type: 'string', required: true } } },
}
const resources = () => ({ resources: [resource], content_hash: 'old', stores: [], layout: {} })
const result = { published: true, content_hash: 'new', written: ['objects/order.yaml'], removed: [], issues: [] }

function pending<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}
let draft: OntologyDraft
function Probe() {
  const current = useOntologyDraft()
  const ensureLoaded = current.ensureLoaded
  useEffect(() => { draft = current }, [current])
  useEffect(() => ensureLoaded(), [ensureLoaded])
  return null
}
function renderDraft(scope?: string) {
  return renderWithProviders(<OntologyDraftProvider storageScope={scope}><Probe /></OntologyDraftProvider>)
}
async function loaded() {
  await waitFor(() => expect(draft.resources).toHaveLength(1))
}
const edit = (name: string) => draft.update('ObjectType', 'order', (r) => ({ ...r, metadata: { ...r.metadata, display: name } }))

beforeEach(() => {
  vi.spyOn(apiClient, 'domains').mockResolvedValue({ active: 'domain-a', domains: [] })
  vi.spyOn(apiClient, 'builderResources').mockResolvedValue(resources())
})

describe('persisted ontology draft', () => {
  it('restores the active domain draft instead of deleting it during initial loading', async () => {
    localStorage.setItem(KEY, JSON.stringify({
      savedAt: Date.now(), domain: 'domain-a', resources: [{ ...resource, metadata: { ...resource.metadata, display: 'Unsaved' } }],
      touched: ['ObjectType/order'], removed: [], layout: {},
    }))
    renderDraft()
    await loaded()
    expect(draft.resources[0].metadata.display).toBe('Unsaved')
    expect(draft.dirty).toBe(true)
    expect(apiClient.builderResources).not.toHaveBeenCalled()
  })

  it('keeps persisted drafts isolated between signed-in accounts', async () => {
    const first = renderDraft('alice')
    await loaded()
    act(() => edit('Alice private draft'))
    await waitFor(() => expect(localStorage.getItem(`${KEY}:alice`)).toContain('Alice private draft'))
    first.unmount()
    const second = renderDraft('bob')
    await loaded()
    expect(draft.resources[0].metadata.display).toBe('Published')
    second.unmount()
    renderDraft('alice')
    await loaded()
    expect(draft.resources[0].metadata.display).toBe('Alice private draft')
  })
})

describe('asynchronous draft saves', () => {
  it('keeps edits made while the save request is pending', async () => {
    const save = pending<typeof result>()
    vi.spyOn(apiClient, 'builderSave').mockReturnValueOnce(save.promise).mockResolvedValue(result)
    renderDraft()
    await loaded()
    act(() => edit('Submitted'))
    let saving!: Promise<void>
    act(() => { saving = draft.save() })
    act(() => edit('Edited while saving'))
    await act(async () => { save.resolve(result); await saving })
    expect(draft.resources[0].metadata.display).toBe('Edited while saving')
    expect(draft.dirty).toBe(true)
    expect(localStorage.getItem(KEY)).toContain('Edited while saving')
    await act(async () => { await draft.save() })
    expect(vi.mocked(apiClient.builderSave).mock.calls[1][0][0].metadata).toMatchObject({ display: 'Edited while saving' })
  })

  it('retains the dirty draft and reports server details when saving fails', async () => {
    vi.spyOn(apiClient, 'builderSave').mockRejectedValue(new ApiError('INVALID_DSL', 'invalid draft', 422, {
      errors: [{ resource: 'ObjectType/order', message: 'bad property' }],
    }))
    renderDraft()
    await loaded()
    act(() => edit('Keep this failed edit'))
    await act(async () => { await draft.save() })
    expect(draft.dirty).toBe(true)
    expect(draft.saveError).toBe('ObjectType/order: bad property')
    expect(localStorage.getItem(KEY)).toContain('Keep this failed edit')
  })

  it('does not overwrite newer edits with a delayed post-save reload', async () => {
    const reload = pending<ReturnType<typeof resources>>()
    vi.mocked(apiClient.builderResources).mockResolvedValueOnce(resources()).mockReturnValueOnce(reload.promise)
    vi.spyOn(apiClient, 'builderSave').mockResolvedValue(result)
    renderDraft()
    await loaded()
    act(() => edit('Submitted'))
    await act(async () => { await draft.save() })
    act(() => edit('Edited during reload'))
    await act(async () => { reload.resolve(resources()) })
    expect(draft.resources[0].metadata.display).toBe('Edited during reload')
    expect(draft.dirty).toBe(true)
  })
})
