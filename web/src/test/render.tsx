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
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import type { ReactElement } from 'react'
import { I18nProvider, type Language } from '../i18n'

/** Renders a component/page with the real providers (query + i18n + router). */
export function renderWithProviders(
  ui: ReactElement,
  { path = '/', route = '*', lang = 'en' as Language, onClient }: {
    path?: string
    route?: string
    lang?: Language
    /** Handed the QueryClient, for the tests that drive a refetch themselves
     *  (a domain switch invalidates the whole cache from outside React). */
    onClient?: (client: QueryClient) => void
  } = {},
) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  onClient?.(client)
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider initial={lang}>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path={route} element={ui} />
          </Routes>
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  )
}
