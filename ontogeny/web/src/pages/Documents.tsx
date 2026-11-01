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
specific language governing permissions and limitations
under the License.
*/
/**
 * Document intelligence — one workspace, not four tabs.
 *
 * The left column is the document inventory (every source file, whether or not
 * it has a task). Selecting a document opens either its task (review/run/
 * confirm) or, for a source without a task, a one-click "create task from this
 * document" panel. Nothing writes object rows until a task is confirmed.
 */
import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import { documentStoresQuery } from '../api/queries'
import { useAuth } from '../api/auth'
import { useI18n } from '../i18n'
import { ErrorBanner } from '../components/ErrorBanner'
import { Button, EmptyState, Page } from '../components/ui'
import { DocumentWorkspace } from './documents/TasksTab'

export function Documents() {
  const { t } = useI18n()
  const { isAdmin } = useAuth()
  const qc = useQueryClient()
  const storesQ = useQuery({ ...documentStoresQuery(), enabled: isAdmin })
  const stores = storesQ.data?.stores ?? []
  const [store, setStore] = useState('')
  useEffect(() => {
    if (!store && stores.length) setStore(stores[0].name)
  }, [stores, store])
  const [defaultError, setDefaultError] = useState<string | null>(null)
  const createDefault = useMutation({
    mutationFn: () => apiClient.createDefaultDocumentSource(),
    onSuccess: async () => {
      setDefaultError(null)
      await qc.invalidateQueries({ queryKey: ['document-stores'] })
    },
    onError: (e) => setDefaultError(e instanceof Error ? e.message : String(e)),
  })

  if (!isAdmin) {
    return (
      <Page fill testId="documents">
        <EmptyState title={t('documents.adminOnly.title')} description={t('documents.adminOnly.body')} />
      </Page>
    )
  }
  if (storesQ.isLoading) {
    return (
      <Page fill testId="documents">
        <EmptyState title={t('common.loading')} />
      </Page>
    )
  }
  if (!stores.length) {
    return (
      <Page fill testId="documents">
        <div className="mx-auto flex w-full max-w-2xl flex-col gap-3">
          <EmptyState
            title={t('documents.noStore.title')}
            description={t('documents.noStore.body')}
            action={
              <Button
                size="sm"
                onClick={() => createDefault.mutate()}
                disabled={createDefault.isPending}
                data-testid="documents-create-default"
              >
                {createDefault.isPending ? t('documents.default.creating') : t('documents.default.action')}
              </Button>
            }
          />
          {defaultError ? <ErrorBanner error={defaultError} /> : null}
        </div>
      </Page>
    )
  }

  return (
    <Page fill testId="documents">
      <DocumentWorkspace
        store={store}
        stores={stores}
        onStoreChange={setStore}
        extractor={storesQ.data?.extractor}
        onInvalidate={async () => {
          await Promise.all([
            qc.invalidateQueries({ queryKey: ['document-stores'] }),
            qc.invalidateQueries({ queryKey: ['documents'] }),
            qc.invalidateQueries({ queryKey: ['storage'] }),
          ])
        }}
      />
    </Page>
  )
}
