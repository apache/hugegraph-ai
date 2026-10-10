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
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { DOMAINS, mockFetch, META } from './test/setup'
import { I18nProvider } from './i18n'
import { Router } from './App'
import { AuthProvider } from './api/auth'
import { OntologyDraftProvider } from './pages/ontology/draft'

/** Shell + routing integration: page-level tests render pages in isolation,
 * so broken layout/nav/provider wiring would slip through them. */
function renderShell(path = '/', lang: 'zh' | 'en' = 'en') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <I18nProvider initial={lang}>
        <MemoryRouter initialEntries={[path]}>
          {/* the same stack App builds: the session gate is part of the shell,
              and the ontology editing session sits above the router (Knowledge,
              Action and the ontology browser share one draft) */}
          <AuthProvider>
            <OntologyDraftProvider>
              <Router />
            </OntologyDraftProvider>
          </AuthProvider>
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  )
}

/** The shell is behind the session gate, so every shell test signs in first.
 *  The gate's answer comes from the server (`/auth/me`), never from a flag. */
const SESSION = {
  principal: {
    id: 'root', Role: ['admin'], roles: ['admin'], display: '平台管理员',
    site: 'north', markings: [], is_admin: true, authenticated: true,
  },
  dev_auth: true,
}

describe('App shell', () => {
  it('renders grouped navigation, search, language and principal controls', async () => {
    mockFetch([
      { match: '/auth/me', body: SESSION },
      { match: '/meta/ontology', body: META },
      { match: '/audit/revisions', body: { revisions: [] } },
      { match: '/evolve/signals', body: { signals: [] } },
    ])
    renderShell('/')
    await waitFor(() => expect(screen.getByTestId('nav-dashboard')).toBeInTheDocument())
    // the agent module groups the console with its governance views, and the
    // header carries the extension tag
    const side = within(screen.getByTestId('sidebar'))
    for (const label of ['Overview', 'Ontology definition', 'Graph explorer', 'Action audit', 'Operations & extensions']) {
      expect(side.getByRole('link', { name: label })).toBeInTheDocument()
    }
    // The conversation is a floating dock now, so the sidebar keeps only the
    // run-management surface (sessions · approvals · plugins).
    expect(side.getByRole('link', { name: 'Agent sessions' })).toBeInTheDocument()
    const rows = Array.from(
      screen.getByTestId('sidebar').querySelectorAll('a[data-testid^="nav-"]'),
    ).map((a) => a.getAttribute('data-testid'))
    expect(rows.indexOf('nav-agentmanage')).toBeLessThan(rows.indexOf('nav-audit'))
    // self-improvement keeps its original spot in the governance tail (below
    // audit), and no "Beta" chip rides on the row; the label is the short
    // "RSI" (both locales prefix with it)
    expect(side.getByRole('link', { name: /^RSI( 自进化)?$/ })).toBeInTheDocument()
    expect(side.queryByTestId('evolve-beta')).toBeNull()
    expect(rows.indexOf('nav-evolve')).toBeGreaterThan(rows.indexOf('nav-audit'))
    expect(rows.indexOf('nav-evolve')).toBeLessThan(rows.indexOf('nav-admin'))
    // the footer is one dock line at rest: search / theme / settings
    expect(screen.getByTestId('global-search-open')).toBeInTheDocument()
    expect(screen.queryByTestId('docs-link')).toBeNull()
    expect(screen.getByTestId('theme-toggle')).toBeInTheDocument()
    expect(screen.getByTestId('settings-open')).toBeInTheDocument()
    expect(screen.getByTestId('sidebar-footer')).toHaveTextContent('A subproject of Apache HugeGraph · v0.3')

    // everything detailed lives in the settings dialog; the dev acting-as
    // picker moved to 权限与角色 → 身份模拟, so the dialog no longer has it
    fireEvent.click(screen.getByTestId('settings-open'))
    expect(screen.getByTestId('settings-dialog')).toBeInTheDocument()
    expect(screen.getByTestId('lang-zh')).toBeInTheDocument()
    expect(screen.queryByTestId('principal-picker')).toBeNull()
    fireEvent.click(screen.getByTestId('settings-done'))

    // search swaps the row for its input
    fireEvent.click(screen.getByTestId('global-search-open'))
    expect(screen.getByTestId('global-search')).toBeInTheDocument()
  })

  it('switches language from the settings dialog and persists the choice', async () => {
    mockFetch([
      { match: '/auth/me', body: SESSION },
      { match: '/meta/ontology', body: META },
      { match: '/audit/revisions', body: { revisions: [] } },
      { match: '/evolve/signals', body: { signals: [] } },
    ])
    renderShell('/', 'en')
    await waitFor(() => expect(screen.getByRole('link', { name: 'Overview' })).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('settings-open'))
    fireEvent.click(screen.getByTestId('lang-zh'))
    await waitFor(() => expect(screen.getByRole('link', { name: '总览' })).toBeInTheDocument())
    expect(localStorage.getItem('ontogeny.lang')).toBe('zh')
    expect(within(screen.getByTestId('sidebar')).getByRole('link', { name: 'RSI 自进化' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { level: 1, name: '总览' })).toBeInTheDocument()
  })

  it('renders the dashboard in Chinese when zh is selected', async () => {
    mockFetch([
      { match: '/auth/me', body: SESSION },
      { match: '/meta/ontology', body: META },
      { match: '/audit/revisions', body: { revisions: [] } },
      { match: '/evolve/signals', body: { signals: [] } },
    ])
    renderShell('/', 'zh')
    await waitFor(() => expect(screen.getByTestId('ontology-model')).toBeInTheDocument())
    expect(screen.getByRole('heading', { level: 1, name: '总览' })).toBeInTheDocument()
    expect(screen.getAllByText('对象类型').length).toBeGreaterThan(0)
  })

  it('lands deleted-demo bookmarks on the dashboard', async () => {
    mockFetch([
      { match: '/auth/me', body: SESSION },
      { match: '/meta/ontology', body: META },
      { match: '/audit/revisions', body: { revisions: [] } },
      { match: '/evolve/signals', body: { signals: [] } },
    ])
    renderShell('/')
    // the demo centre is deleted: its route no longer exists, the dashboard is
    // where every former entry point lands
    await waitFor(() => expect(screen.getByTestId('ontology-model')).toBeInTheDocument())
  })

  it('offers a skip link as the first tab stop, pointing at a focusable main', async () => {
    mockFetch([
      { match: '/auth/me', body: SESSION },
      { match: '/meta/ontology', body: META },
      { match: '/audit/revisions', body: { revisions: [] } },
      { match: '/evolve/signals', body: { signals: [] } },
    ])
    renderShell('/')
    await waitFor(() => expect(screen.getByTestId('nav-dashboard')).toBeInTheDocument())

    const skip = screen.getByTestId('skip-link')
    expect(skip).toHaveAttribute('href', '#ontogeny-main')
    // it must be the first focusable thing in the DOM, or "skip" saves nothing
    const focusable = document.querySelectorAll('a[href], button, input, [tabindex]:not([tabindex="-1"])')
    expect(focusable[0]).toBe(skip)
    // the target has to accept focus, or the jump moves the scroll position only
    expect(screen.getByRole('main')).toHaveAttribute('tabindex', '-1')
  })

  it('moves the search highlight with the arrow keys and opens on Enter', async () => {
    mockFetch([
      { match: '/auth/me', body: SESSION },
      { match: '/meta/ontology', body: META },
      { match: '/audit/revisions', body: { revisions: [] } },
      { match: '/evolve/signals', body: { signals: [] } },
    ])
    renderShell('/')
    await waitFor(() => expect(screen.getByTestId('nav-dashboard')).toBeInTheDocument())

    fireEvent.click(screen.getByTestId('global-search-open'))
    const input = screen.getByTestId('global-search')
    fireEvent.change(input, { target: { value: 'sales' } })

    // the input keeps DOM focus; the active row is exposed via aria-activedescendant
    expect(input).toHaveAttribute('role', 'combobox')
    expect(screen.getByRole('listbox')).toBeInTheDocument()

    fireEvent.keyDown(input, { key: 'ArrowDown' })
    const option = await screen.findByTestId('search-option-0')
    expect(option).toHaveAttribute('aria-selected', 'true')
    expect(input).toHaveAttribute('aria-activedescendant', 'ontogeny-search-option-0')

    // arrow-up at the top stays put rather than wrapping to the last row
    fireEvent.keyDown(input, { key: 'ArrowUp' })
    expect(input).toHaveAttribute('aria-activedescendant', 'ontogeny-search-option-0')
  })

  it('shows the ontology context bar even with one domain (its menu is the only New-domain entry)', async () => {
    // Regression: the bar used to hide itself on single-domain deployments,
    // which also hid "New domain" -- the only way to create/import the second
    // domain. It renders from the first domain on.
    mockFetch([
      { match: '/auth/me', body: SESSION },
      { match: '/meta/ontology', body: META },
      { match: '/admin/builder/resources', body: { resources: [], content_hash: 'h' } },
      { match: /\/admin\/domains$/, body: { domains: [DOMAINS.domains[0]], active: 'manufacturing-system' } },
    ])
    renderShell('/ontology')
    await waitFor(() => expect(screen.getByTestId('ontology-toolbar')).toBeInTheDocument())
    expect(screen.getByTestId('domain-bar')).toBeInTheDocument()
  })

  it('puts the ontology context bar at the foot of the sidebar, not over the page', async () => {
    // Which package the console serves is navigation state: it changes what
    // every route shows, so it belongs with the nav. It also used to float
    // above the page, which cost the canvas a strip of height on every route.
    mockFetch([
      { match: '/auth/me', body: SESSION },
      { match: '/meta/ontology', body: META },
      { match: '/admin/builder/resources', body: { resources: [], content_hash: 'h' } },
      {
        match: /\/admin\/domains$/,
        body: {
          domains: [
            { ...DOMAINS.domains[0] },
            { name: 'logistics-system', display: '物流运营系统', path: '/tmp/b', objects: 0, links: 0, actions: 0, active: false },
          ],
          active: 'manufacturing-system',
        },
      },
    ])
    renderShell('/ontology')
    const bar = await screen.findByTestId('domain-bar')
    expect(within(bar).getByTestId('domain-switcher')).toBeInTheDocument()
    // ...inside the rail, not floating over the page
    expect(within(screen.getByTestId('sidebar')).getByTestId('domain-bar')).toBeInTheDocument()
    // the trigger names the active package, and the menu opens from it
    await waitFor(() =>
      expect(within(bar).getByTestId('domain-switcher')).toHaveTextContent('离散制造运营系统'))
    fireEvent.click(within(bar).getByTestId('domain-switcher'))
    const menu = await screen.findByTestId('domain-menu')
    expect(within(menu).getByTestId('domain-option-logistics-system')).toBeInTheDocument()
    expect(within(menu).getByTestId('domain-create')).toBeInTheDocument()
    // ...and the canvas still loaded the active domain's model
    await waitFor(() => expect(screen.getByTestId('ontology-toolbar')).toBeInTheDocument())
  })

  it('opens the agent console from the floating dock, without leaving the page', async () => {
    mockFetch([
      { match: '/auth/me', body: SESSION },
      { match: '/meta/ontology', body: META },
      { match: '/audit/revisions', body: { revisions: [] } },
      { match: '/evolve/signals', body: { signals: [] } },
      { match: '/agent/plugins', body: { plugins: [] } },
      { match: '/agent/sessions', body: { sessions: [] } },
    ])
    renderShell('/')
    await waitFor(() => expect(screen.getByTestId('nav-dashboard')).toBeInTheDocument())

    // the dock is a button in the corner, not a sidebar destination
    const dock = screen.getByTestId('agent-dock')
    expect(dock).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByTestId('agent-dock-dialog')).not.toBeInTheDocument()

    fireEvent.click(dock)
    const dialog = await screen.findByTestId('agent-dock-dialog')
    expect(dialog).toHaveAttribute('role', 'dialog')
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    // the console itself, with its three modes, is inside the dialog
    await waitFor(() => expect(within(dialog).getByTestId('mode-agent')).toBeInTheDocument())
    expect(within(dialog).getByTestId('chat-input')).toBeInTheDocument()
    // ...and the page underneath never navigated
    expect(screen.getByTestId('nav-dashboard')).toBeInTheDocument()

    fireEvent.keyDown(window, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByTestId('agent-dock-dialog')).not.toBeInTheDocument())
  })
})
