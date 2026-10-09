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
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { mockFetch, META } from '../test/setup'
import { I18nProvider } from '../i18n'
import { AuthProvider, useAuth } from '../api/auth'
import { Login } from './Login'
import { Access } from './Access'

const ADMIN_PRINCIPAL = {
  id: 'root', Role: ['admin'], roles: ['admin'], display: '平台管理员',
  site: 'north', markings: [], is_admin: true, authenticated: true, via: 'session',
}
const OPERATOR_PRINCIPAL = {
  id: 'op', Role: ['operator'], roles: ['operator'], display: '操作工',
  site: 'north', markings: [], is_admin: false, authenticated: true, via: 'session',
}

const USERS = {
  users: [
    { id: 1, username: 'root', display: '平台管理员', roles: ['admin'], site: 'north', markings: [],
      status: 'active', is_admin: true, created_at: null, last_login_at: null },
    { id: 2, username: 'li', display: '李工', roles: ['operator', 'quality_inspector'], site: 'north',
      markings: ['internal'], status: 'active', is_admin: false, created_at: null, last_login_at: null },
  ],
}

const ROLES = {
  roles: [
    { name: 'operator', sources: ['vocabulary'], managedPolicy: 'role-operator', hasManagedPolicy: true, members: ['li'] },
    { name: 'maintenance_supervisor', sources: ['policy'], managedPolicy: 'role-maintenance-supervisor', hasManagedPolicy: false, members: [] },
  ],
  actions: ['close-work-order', 'record-inspection'],
  matrix: {
    operator: {
      'close-work-order': { granted: true, source: 'role-operator', managed: true, conditional: false },
      'record-inspection': { granted: false },
    },
    maintenance_supervisor: {
      'close-work-order': { granted: true, source: 'close-work-order', managed: false, conditional: true },
      'record-inspection': { granted: false },
    },
  },
  grants: [
    { policy: 'role-operator', roles: ['operator'], actions: ['close-work-order'], conditional: false, managed: true },
    { policy: 'close-work-order', roles: ['maintenance_supervisor'], actions: ['close-work-order'], conditional: true, managed: false },
  ],
}

function wrap(ui: React.ReactElement, path = '/') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
  return render(
    <QueryClientProvider client={qc}>
      <I18nProvider initial="en">
        <MemoryRouter initialEntries={[path]}>
          <AuthProvider>{ui}</AuthProvider>
        </MemoryRouter>
      </I18nProvider>
    </QueryClientProvider>,
  )
}

/** Renders the gate the way App does, so "no session -> login page" is a real
 *  assertion about the app rather than about a component in isolation. */
function Gate() {
  const { principal, loading } = useAuth()
  if (loading) return <div data-testid="gate-loading" />
  return principal ? <div data-testid="app-rendered" /> : <Login />
}

describe('session gate', () => {
  it('shows the login page when nobody is signed in', async () => {
    mockFetch([{ match: '/auth/me', status: 401, body: { code: 'UNAUTHENTICATED', message: 'not signed in' } }])
    wrap(<Gate />)
    await waitFor(() => expect(screen.getByTestId('login-page')).toBeInTheDocument())
    expect(screen.queryByTestId('app-rendered')).toBeNull()
  })

  it('renders the app for a signed-in account', async () => {
    mockFetch([{ match: '/auth/me', body: { principal: ADMIN_PRINCIPAL, dev_auth: true } }])
    wrap(<Gate />)
    await waitFor(() => expect(screen.getByTestId('app-rendered')).toBeInTheDocument())
    expect(screen.queryByTestId('login-page')).toBeNull()
  })

  it('signs in, surfaces a bad password, and clears it from the field', async () => {
    const { calls } = mockFetch([
      { match: '/auth/me', status: 401, body: { code: 'UNAUTHENTICATED', message: 'not signed in' } },
      { match: '/auth/login', status: 401, body: { code: 'UNAUTHENTICATED', message: 'invalid username or password' } },
    ])
    wrap(<Gate />)
    await waitFor(() => expect(screen.getByTestId('login-page')).toBeInTheDocument())

    fireEvent.change(screen.getByTestId('login-username'), { target: { value: 'root' } })
    fireEvent.change(screen.getByTestId('login-password'), { target: { value: 'wrong-password' } })
    fireEvent.click(screen.getByTestId('login-submit'))

    await waitFor(() => expect(screen.getByTestId('login-error')).toHaveTextContent(/invalid username or password/))
    // the password never stays in the field after a failed attempt
    expect(screen.getByTestId('login-password')).toHaveValue('')
    expect(calls.some((c) => c.url.includes('/auth/login'))).toBe(true)
  })
})

/** The standard admin surface: a signed-in administrator over the users/roles
 *  fixtures, with room for per-test overrides. Shared by both describes — the
 *  identity tab reads the same /admin/roles payload as the matrix. */
const mock = (principal = ADMIN_PRINCIPAL, extra: Parameters<typeof mockFetch>[0] = []) => mockFetch([
  { match: '/auth/me', body: { principal, dev_auth: true } },
  { match: '/meta/ontology', body: META },
  { match: '/admin/users', body: USERS },
  { match: '/admin/roles', body: ROLES },
  ...extra,
])

describe('Access control', () => {
  it('refuses the administration surfaces for a non-administrator while dev_auth is off', async () => {
    mockFetch([
      { match: '/auth/me', body: { principal: OPERATOR_PRINCIPAL, dev_auth: false } },
      { match: '/meta/ontology', body: META },
    ])
    wrap(<Access />)
    await waitFor(() => expect(screen.getByText(/Administrator account required/)).toBeInTheDocument())
    expect(screen.queryByTestId('access')).toBeNull()
  })

  it('lists accounts with their roles and scope', async () => {
    mock()
    wrap(<Access />)
    await waitFor(() => expect(screen.getByText('li')).toBeInTheDocument())
    expect(screen.getByText('quality_inspector')).toBeInTheDocument()
    expect(screen.getByText(/internal/)).toBeInTheDocument()
  })

  it('creates an account and sends the roles as a list', async () => {
    const { calls } = mock(ADMIN_PRINCIPAL, [
      { match: '/admin/users', body: { id: 3, username: 'wang', display: '王工', roles: ['operator'], site: null, markings: [], status: 'active', is_admin: false, created_at: null, last_login_at: null } },
    ])
    wrap(<Access />)
    await waitFor(() => expect(screen.getByTestId('create-user')).toBeInTheDocument())

    fireEvent.change(screen.getByTestId('new-username'), { target: { value: 'wang' } })
    fireEvent.change(screen.getByTestId('new-password'), { target: { value: 'wang-password' } })
    fireEvent.change(screen.getByTestId('new-roles'), { target: { value: 'operator, quality_inspector' } })
    fireEvent.click(screen.getByTestId('create-user'))

    await waitFor(() => {
      const call = calls.find((c) => c.url.endsWith('/admin/users') && c.init?.method === 'POST')
      expect(call).toBeTruthy()
      const body = JSON.parse(String(call!.init?.body))
      expect(body.username).toBe('wang')
      expect(body.roles).toEqual(['operator', 'quality_inspector'])
    })
  })

  it('disables an account from the row action', async () => {
    const { calls } = mock(ADMIN_PRINCIPAL, [{ match: '/admin/users/li', body: { ...USERS.users[1], status: 'disabled' } }])
    wrap(<Access />)
    await waitFor(() => expect(screen.getByTestId('toggle-li')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('toggle-li'))
    await waitFor(() => {
      const call = calls.find((c) => c.url.includes('/admin/users/li') && c.init?.method === 'PATCH')
      expect(call).toBeTruthy()
      expect(JSON.parse(String(call!.init?.body))).toEqual({ status: 'disabled' })
    })
  })

  it('seeds the matrix from the managed grants and saves a toggle as Cedar', async () => {
    const { calls } = mock(ADMIN_PRINCIPAL, [{ match: '/admin/roles/operator', body: { saved: 'role-operator', actions: [] } }])
    wrap(<Access />)
    await waitFor(() => expect(screen.getByTestId('tab-roles')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('tab-roles'))
    await waitFor(() => expect(screen.getByTestId('role-operator')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('role-operator'))

    // a MANAGED grant is ticked and toggleable -- that is what this page owns
    const managed = await screen.findByTestId('grant-operator-close-work-order')
    expect(managed).toBeChecked()
    expect(managed).toBeEnabled()

    // a hand-written grant is shown with its source policy and cannot be revoked here
    fireEvent.click(screen.getByTestId('role-maintenance_supervisor'))
    const byHand = await screen.findByTestId('grant-maintenance_supervisor-close-work-order')
    expect(byHand).toBeChecked()
    expect(byHand).toBeDisabled()
    // the source policy is named after the action, so assert on the attribution
    // badge rather than on the bare action name (which is also the row label)
    expect(screen.getAllByText('close-work-order').length).toBeGreaterThan(1)

    // toggling a managed action and saving PUTs the grant set
    fireEvent.click(screen.getByTestId('role-operator'))
    const cell = await screen.findByTestId('grant-operator-record-inspection')
    expect(cell).not.toBeChecked()
    fireEvent.click(cell)
    fireEvent.click(screen.getByTestId('save-role'))
    await waitFor(() => {
      const call = calls.find((c) => c.url.includes('/admin/roles/operator') && c.init?.method === 'PUT')
      expect(call).toBeTruthy()
      const body = JSON.parse(String(call!.init?.body))
      expect(body.name).toBe('operator')
      expect(body.actions.sort()).toEqual(['close-work-order', 'record-inspection'])
    })
  })

  it('adds a role by name and can delete it', async () => {
    const { calls } = mock(ADMIN_PRINCIPAL, [
      { match: '/admin/roles/new_role', body: { deleted: 'new_role', reassigned: [] } },
    ])
    wrap(<Access />)
    await waitFor(() => expect(screen.getByTestId('tab-roles')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('tab-roles'))

    fireEvent.change(screen.getByTestId('new-role'), { target: { value: 'new_role' } })
    fireEvent.click(screen.getByTestId('add-role'))
    await waitFor(() => expect(screen.getByTestId('role-new_role')).toBeInTheDocument())

    fireEvent.click(screen.getByTestId('delete-role'))
    await waitFor(() => expect(screen.getByTestId('confirm-dialog')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('confirm-accept'))
    await waitFor(() => {
      const call = calls.find((c) => c.url.includes('/admin/roles/new_role') && c.init?.method === 'DELETE')
      expect(call).toBeTruthy()
    })
  })
})

describe('Identity simulation', () => {
  const SIM_PRINCIPAL = {
    id: 'u-sup', Role: ['maintenance_supervisor'], roles: ['maintenance_supervisor'],
    display: 'u-sup', site: 'north', markings: [], is_admin: false, authenticated: false,
    via: 'dev-header',
  }

  const override = (p: unknown) =>
    localStorage.setItem('ontogeny.principal', JSON.stringify(p))

  it('is the only tab for a non-administrator while dev_auth is on', async () => {
    mockFetch([
      { match: '/auth/me', body: { principal: OPERATOR_PRINCIPAL, dev_auth: true } },
      { match: '/meta/ontology', body: META },
    ])
    wrap(<Access />)
    await waitFor(() => expect(screen.getByTestId('tab-identity')).toBeInTheDocument())
    expect(screen.queryByTestId('tab-users')).toBeNull()
    expect(screen.queryByTestId('tab-roles')).toBeNull()
    expect(screen.getByTestId('identity-via')).toHaveTextContent('Sign-in session')
  })

  it('says which resolution is winning and lists the presets', async () => {
    mock(ADMIN_PRINCIPAL)
    wrap(<Access />)
    await waitFor(() => expect(screen.getByTestId('tab-identity')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('tab-identity'))

    expect(screen.getByTestId('identity-via')).toHaveTextContent('Sign-in session')
    expect(screen.getByTestId('sim-preset-planner')).toBeInTheDocument()
    expect(screen.getByTestId('sim-preset-visitor')).toBeInTheDocument()
    // no override chosen -> nothing to clear, nothing shadowed
    expect(screen.getByTestId('sim-clear')).toBeDisabled()
    expect(screen.queryByTestId('sim-activate')).toBeNull()
  })

  it('warns when a chosen simulation is shadowed by the session, and can sign out into it', async () => {
    override({ id: 'u-sup', Role: ['maintenance_supervisor'], site: 'north' })
    const { calls } = mock(ADMIN_PRINCIPAL, [{ match: '/auth/logout', body: { ok: true } }])
    wrap(<Access />)
    await waitFor(() => expect(screen.getByTestId('tab-identity')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('tab-identity'))

    // the precedence made visible: the session wins, the simulation names itself
    expect(screen.getByTestId('identity-via')).toHaveTextContent('Sign-in session')
    expect(screen.getByTestId('sim-activate')).toBeInTheDocument()
    expect(screen.getByText(/u-sup is NOT in effect/)).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('sim-activate'))
    await waitFor(() => {
      expect(calls.some((c: { url: string }) => c.url.includes('/auth/logout'))).toBe(true)
    })
    // signOut cleared the override, and simulate re-applied the choice — wait
    // for the re-apply, which lands after the logout round-trip resolves
    await waitFor(() => {
      expect(JSON.parse(localStorage.getItem('ontogeny.principal')!)).toMatchObject({ id: 'u-sup' })
    })
  })

  it('shows an active simulation and can exit it', async () => {
    override({ id: 'u-sup', Role: ['maintenance_supervisor'] })
    mockFetch([
      { match: '/auth/me', body: { principal: SIM_PRINCIPAL, dev_auth: true } },
      { match: '/meta/ontology', body: META },
    ])
    wrap(<Access />)
    await waitFor(() => expect(screen.getByTestId('tab-identity')).toBeInTheDocument())

    // landed straight into the simulation: the server answered /auth/me with it
    expect(screen.getByTestId('identity-via')).toHaveTextContent('Simulated identity')
    expect(screen.getByText(/Simulated identity is active/)).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('sim-exit'))
    await waitFor(() => expect(localStorage.getItem('ontogeny.principal')).toBeNull())
  })

  it('bridges the simulation to the role matrix grants', async () => {
    override({ id: 'u-sup', Role: ['maintenance_supervisor'] })
    mock(ADMIN_PRINCIPAL)
    wrap(<Access />)
    await waitFor(() => expect(screen.getByTestId('tab-identity')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('tab-identity'))

    // the override's role, read against the same matrix the roles tab edits.
    // The row mounts before its grants arrive (async matrix parse), so wait
    // for the grant text, not merely for the row.
    await waitFor(() => expect(screen.getByTestId('sim-role-maintenance_supervisor'))
      .toHaveTextContent('close-work-order'))
  })

  it('validates the custom identity JSON before applying it', async () => {
    mock(ADMIN_PRINCIPAL)
    wrap(<Access />)
    await waitFor(() => expect(screen.getByTestId('tab-identity')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('tab-identity'))

    fireEvent.change(screen.getByTestId('sim-custom'), { target: { value: '{not json' } })
    fireEvent.click(screen.getByTestId('sim-apply'))
    expect(screen.getByText(/Invalid JSON/)).toBeInTheDocument()

    fireEvent.change(screen.getByTestId('sim-custom'), { target: { value: '{"id":"u","display":"张三"}' } })
    fireEvent.click(screen.getByTestId('sim-apply'))
    expect(screen.getByText(/Non-ASCII characters/)).toBeInTheDocument()
    // nothing was applied
    expect(localStorage.getItem('ontogeny.principal')).toBeNull()
  })
})
