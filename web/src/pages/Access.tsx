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
/**
 * Access control — accounts, the permission matrix, and (dev) identity simulation.
 *
 * Three halves of one question — who may do what:
 *
 * - **Accounts**  who exists, what roles they carry, and the attributes (site,
 *   markings) the policies read. Passwords are set or reset here; the server
 *   never returns a hash and a password change kills that account's sessions.
 * - **Roles & permissions**  a role × action matrix. Reading it parses the compiled Cedar;
 *   toggling a cell writes the role's *managed* policy set, so a grant made here
 *   is enforced by the engine on the next request — the same policy plane that
 *   decides everything else. A grant that comes from a hand-written policy is
 *   shown, attributed, and locked: Cedar is additive, so this surface must not
 *   pretend it can revoke someone else's permit.
 * - **Identity simulation**  development/CI only (`dev_auth` on the server): act as a
 *   preset or custom principal without an account. The server resolves one
 *   identity per request with a fixed precedence — session cookie > bearer
 *   token > the simulated header > anonymous — so this tab's job is to make
 *   that precedence visible (which identity is winning RIGHT NOW) and operable
 *   (apply, sign-out-then-apply, clear).
 *
 * Accounts/roles are administrator-only (the server enforces it with a 403 and the
 * page says so). Identity simulation needs no administrator: it touches no account
 * data, only the local override and `/auth/me`.
 */
import { useEffect, useMemo, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  apiClient, ApiError, getDevPrincipal, headerSafe, PRESET_PRINCIPALS, setPrincipal,
  type AccountUser, type RoleInfo,
} from '../api/client'
import type { Principal } from '../api/types'
import { useAuth } from '../api/auth'
import { useI18n } from '../i18n'
import {
  Alert, Badge, Button, Card, ConfirmDialog, EmptyState, Page, Skeleton, Tabs, toneSurface,
} from '../components/ui'
import { ErrorBanner } from '../components/ErrorBanner'
import { DataTable } from '../components/DataTable'
import { IconBraces, IconCheck, IconPlus, IconShield, IconTrash, IconUser, IconX } from '../components/icons'

/** Mirrors the server's `managed_policy_name`: resource names are kebab-case,
 *  while the role vocabulary allows underscores. */
const managedPolicyName = (role: string) => `role-${role.toLowerCase().replace(/_/g, '-')}`

type Tab = 'users' | 'roles' | 'identity'

export function Access() {
  const { t } = useI18n()
  const { isAdmin, devAuth, principal } = useAuth()
  const [tab, setTab] = useState<Tab>('users')

  // 账号/角色 are administrator surfaces; 身份模拟 is a dev tool that needs
  // neither an account nor an administrator, so dev_auth alone unlocks it.
  if (!isAdmin && !devAuth) {
    return (
      <Page>
        <h1 className="sr-only">{t('access.title')}</h1>
        <Card>
          <EmptyState
            icon={<IconShield width={20} height={20} />}
            title={t('access.notAdmin')}
            description={t('access.notAdminHint', { user: String(principal?.id ?? '—') })}
          />
        </Card>
      </Page>
    )
  }

  const tabs = [
    ...(isAdmin ? [
      { id: 'users' as Tab, label: t('access.tab.users'), icon: <IconUser width={14} height={14} /> },
      { id: 'roles' as Tab, label: t('access.tab.roles'), icon: <IconShield width={14} height={14} /> },
    ] : []),
    ...(devAuth ? [
      { id: 'identity' as Tab, label: t('access.tab.identity'), icon: <IconBraces width={14} height={14} /> },
    ] : []),
  ]
  // a non-admin lands on the only tab they have; an admin's default stays 账号
  const active = tabs.some((x) => x.id === tab) ? tab : tabs[0].id

  return (
    <Page fill testId="access">
      <h1 className="sr-only">{t('access.title')}</h1>
      <Tabs<Tab>
        tabs={tabs}
        value={active}
        onChange={setTab}
      />
      {active === 'users' ? <Accounts /> : active === 'roles' ? <Roles /> : <Identity />}
    </Page>
  )
}

/* --------------------------------------------------------------- accounts */

const EMPTY_FORM = {
  username: '', password: '', display: '', roles: '', site: '', markings: '', is_admin: false,
}

function Accounts() {
  const { t } = useI18n()
  const qc = useQueryClient()
  const { principal } = useAuth()
  const [form, setForm] = useState({ ...EMPTY_FORM })
  const [editing, setEditing] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  const users = useQuery({ queryKey: ['admin-users'], queryFn: apiClient.users })
  const roles = useQuery({ queryKey: ['admin-roles'], queryFn: apiClient.roles })

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ['admin-users'] })
    qc.invalidateQueries({ queryKey: ['admin-roles'] })
  }

  const create = useMutation({
    mutationFn: () => apiClient.createUser({
      username: form.username.trim(),
      password: form.password,
      display: form.display.trim() || form.username.trim(),
      roles: splitList(form.roles),
      site: form.site.trim() || null,
      markings: splitList(form.markings),
      is_admin: form.is_admin,
    }),
    onSuccess: (u) => {
      setNotice(t('access.created', { user: u.username }))
      setForm({ ...EMPTY_FORM })
      invalidate()
    },
  })

  const update = useMutation({
    mutationFn: (args: { username: string; patch: Record<string, unknown> }) =>
      apiClient.updateUser(args.username, args.patch),
    onSuccess: () => { setNotice(null); invalidate() },
  })

  const remove = useMutation({
    mutationFn: (username: string) => apiClient.deleteUser(username),
    onSuccess: () => { setConfirmDelete(null); invalidate() },
  })

  const error = create.error ?? update.error ?? remove.error
  const rows = users.data?.users ?? []
  const knownRoles = useMemo(
    () => (roles.data?.roles ?? []).map((r) => r.name),
    [roles.data],
  )

  if (users.isLoading) return <Skeleton rows={6} />
  if (users.error) return <ErrorBanner error={users.error} />

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      {notice ? <Alert tone="success" action={<Button size="sm" onClick={() => setNotice(null)} icon={<IconX width={12} height={12} />} />}>{notice}</Alert> : null}
      {error ? (
        <Alert tone="danger" title={t('access.failed')}>
          {error instanceof ApiError ? error.message : String(error)}
        </Alert>
      ) : null}

      <Card
        padded={false}
        toolbar={<Badge tone="brand">{t('access.userCount', { count: rows.length })}</Badge>}
        bodyClassName="p-0"
      >
        <DataTable<AccountUser>
          columns={[
            {
              key: 'username', label: t('access.username'),
              render: (u) => (
                <span className="flex items-center gap-2">
                  <span className="font-mono text-[12.5px]">{u.username}</span>
                  {u.username === principal?.id ? <Badge tone="info">{t('access.you')}</Badge> : null}
                  {u.status === 'disabled' ? <Badge tone="danger">{t('access.disabled')}</Badge> : null}
                </span>
              ),
            },
            { key: 'display', label: t('access.display') },
            {
              key: 'roles', label: t('access.roles'),
              render: (u) => (
                <span className="flex flex-wrap gap-1">
                  {u.is_admin ? <Badge tone="violet">{t('access.admin')}</Badge> : null}
                  {u.roles.length === 0 && !u.is_admin ? <span className="muted">—</span> : null}
                  {u.roles.map((r) => <Badge key={r} tone="brand" mono>{r}</Badge>)}
                </span>
              ),
            },
            {
              key: 'scope', label: t('access.scope'),
              render: (u) => (
                <span className="font-mono text-[11.5px] muted">
                  {u.site ?? '—'}{u.markings.length ? ` · ${u.markings.join(', ')}` : ''}
                </span>
              ),
            },
            {
              key: 'last', label: t('access.lastLogin'),
              render: (u) => <span className="text-[11.5px] muted">{u.last_login_at ? u.last_login_at.slice(0, 16).replace('T', ' ') : '—'}</span>,
            },
            {
              key: 'actions', label: '', align: 'right',
              render: (u) => (
                <span className="flex items-center justify-end gap-1.5">
                  <Button size="sm" data-testid={`edit-${u.username}`} onClick={() => setEditing(u.username)}>
                    {t('access.edit')}
                  </Button>
                  <Button
                    size="sm"
                    variant="subtle"
                    data-testid={`toggle-${u.username}`}
                    onClick={() => update.mutate({
                      username: u.username,
                      patch: { status: u.status === 'active' ? 'disabled' : 'active' },
                    })}
                  >
                    {u.status === 'active' ? t('access.disable') : t('access.enable')}
                  </Button>
                  <Button
                    size="sm"
                    variant="subtle"
                    data-testid={`delete-${u.username}`}
                    disabled={u.is_admin || u.username === principal?.id}
                    title={u.is_admin || u.username === principal?.id ? t('access.adminDeleteLocked') : t('access.delete')}
                    aria-label={t('access.delete')}
                    onClick={() => setConfirmDelete(u.username)}
                    icon={<IconTrash width={13} height={13} />}
                    style={{ color: 'var(--tone-danger-fg)' }}
                  />
                </span>
              ),
            },
          ]}
          rows={rows}
          rowKey={(u) => u.username}
          empty={<EmptyState title={t('access.noUsers')} />}
        />
      </Card>

      <Card title={t('access.newUser')} description={t('access.newUserHint')}>
        <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
          <Field label={t('access.username')}>
            <input className="ontogeny-input font-mono" value={form.username} data-testid="new-username"
                   onChange={(e) => setForm({ ...form, username: e.target.value })} />
          </Field>
          <Field label={t('access.password')} hint={t('access.passwordHint')}>
            <input className="ontogeny-input font-mono" type="password" value={form.password} data-testid="new-password"
                   onChange={(e) => setForm({ ...form, password: e.target.value })} />
          </Field>
          <Field label={t('access.display')}>
            <input className="ontogeny-input" value={form.display}
                   onChange={(e) => setForm({ ...form, display: e.target.value })} />
          </Field>
          <Field label={t('access.roles')} hint={t('access.rolesHint')}>
            <input className="ontogeny-input font-mono" list="ontogeny-known-roles" value={form.roles} data-testid="new-roles"
                   placeholder="operator, quality_inspector"
                   onChange={(e) => setForm({ ...form, roles: e.target.value })} />
          </Field>
          <Field label={t('access.site')} hint={t('access.siteHint')}>
            <input className="ontogeny-input font-mono" value={form.site}
                   onChange={(e) => setForm({ ...form, site: e.target.value })} />
          </Field>
          <Field label={t('access.markings')} hint={t('access.markingsHint')}>
            <input className="ontogeny-input font-mono" value={form.markings}
                   onChange={(e) => setForm({ ...form, markings: e.target.value })} />
          </Field>
        </div>
        <datalist id="ontogeny-known-roles">{knownRoles.map((r) => <option key={r} value={r} />)}</datalist>

        <div className="mt-3 flex flex-wrap items-center gap-3">
          <label className="flex cursor-pointer items-center gap-2 text-[12.5px]">
            <input type="checkbox" className="size-3.5" checked={form.is_admin}
                   data-testid="new-is-admin"
                   onChange={(e) => setForm({ ...form, is_admin: e.target.checked })} />
            {t('access.makeAdmin')}
          </label>
          <Button
            variant="primary"
            className="ml-auto"
            data-testid="create-user"
            disabled={!form.username.trim() || form.password.length < 8 || create.isPending}
            onClick={() => create.mutate()}
            icon={<IconPlus width={13} height={13} />}
          >
            {create.isPending ? t('access.creating') : t('access.create')}
          </Button>
        </div>
      </Card>

      {editing ? (
        <EditUserDialog
          user={rows.find((u) => u.username === editing)!}
          onClose={() => setEditing(null)}
          onSave={(patch) => update.mutate({ username: editing, patch }, { onSuccess: () => setEditing(null) })}
          saving={update.isPending}
        />
      ) : null}

      <ConfirmDialog
        open={confirmDelete !== null}
        title={t('access.confirmDelete')}
        message={t('access.confirmDeleteHint', { user: confirmDelete ?? '' })}
        confirmLabel={t('access.delete')}
        cancelLabel={t('common.cancel')}
        onCancel={() => setConfirmDelete(null)}
        onConfirm={() => confirmDelete && remove.mutate(confirmDelete)}
      />
    </div>
  )
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block min-w-0">
      <span className="ontogeny-label" style={{ marginBottom: 4 }}>{label}</span>
      {children}
      {hint ? <span className="mt-1 block text-[11px] muted">{hint}</span> : null}
    </label>
  )
}

const splitList = (s: string) => s.split(/[,\s]+/).map((x) => x.trim()).filter(Boolean)

/** Editing an account: roles, scope and status. The username is the identity
 *  the audit trail records, so it is shown but not editable. */
function EditUserDialog({ user, onClose, onSave, saving }: {
  user: AccountUser
  onClose: () => void
  onSave: (patch: Record<string, unknown>) => void
  saving: boolean
}) {
  const { t } = useI18n()
  const [display, setDisplay] = useState(user.display)
  const [roles, setRoles] = useState(user.roles.join(', '))
  const [site, setSite] = useState(user.site ?? '')
  const [markings, setMarkings] = useState(user.markings.join(', '))
  const [isAdmin, setIsAdmin] = useState(user.is_admin)
  const [password, setPassword] = useState('')

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 grid place-items-center p-4" style={{ background: 'rgba(0,0,0,.45)' }}
         onClick={onClose} data-testid="edit-user-dialog">
      <div className="ontogeny-card ontogeny-modal w-full max-w-lg p-5"
           onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-[14px] font-semibold">
            {t('access.editUser')} <span className="font-mono">{user.username}</span>
          </h2>
          <Button size="sm" onClick={onClose} icon={<IconX width={13} height={13} />} />
        </div>

        <div className="mt-4 grid gap-2.5 sm:grid-cols-2">
          <Field label={t('access.display')}>
            <input className="ontogeny-input" value={display} onChange={(e) => setDisplay(e.target.value)} />
          </Field>
          <Field label={t('access.site')} hint={t('access.siteHint')}>
            <input className="ontogeny-input font-mono" value={site} onChange={(e) => setSite(e.target.value)} />
          </Field>
          <Field label={t('access.roles')} hint={t('access.rolesHint')}>
            <input className="ontogeny-input font-mono" list="ontogeny-known-roles" value={roles} data-testid="edit-roles"
                   onChange={(e) => setRoles(e.target.value)} />
          </Field>
          <Field label={t('access.markings')} hint={t('access.markingsHint')}>
            <input className="ontogeny-input font-mono" value={markings} onChange={(e) => setMarkings(e.target.value)} />
          </Field>
          <Field label={t('access.resetPassword')} hint={t('access.resetPasswordHint')}>
            <input className="ontogeny-input font-mono" type="password" value={password} data-testid="edit-password"
                   onChange={(e) => setPassword(e.target.value)} />
          </Field>
          <div className="flex items-end pb-1">
            <label className="flex cursor-pointer items-center gap-2 text-[12.5px]">
              <input type="checkbox" className="size-3.5" checked={isAdmin} onChange={(e) => setIsAdmin(e.target.checked)} />
              {t('access.admin')}
            </label>
          </div>
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <Button onClick={onClose}>{t('common.cancel')}</Button>
          <Button
            variant="primary"
            data-testid="save-user"
            disabled={saving}
            onClick={() => onSave({
              display,
              roles: splitList(roles),
              site: site.trim() || null,
              markings: splitList(markings),
              is_admin: isAdmin,
              ...(password ? { password } : {}),
            })}
            icon={<IconCheck width={13} height={13} />}
          >
            {t('common.save')}
          </Button>
        </div>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ roles */

function Roles() {
  const { t } = useI18n()
  const qc = useQueryClient()
  const roles = useQuery({ queryKey: ['admin-roles'], queryFn: apiClient.roles })
  const [selected, setSelected] = useState<string | null>(null)
  const [draft, setDraft] = useState<Set<string>>(new Set())
  const [site, setSite] = useState('')
  const [newRole, setNewRole] = useState('')
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null)

  const data = roles.data
  // A role typed in but not yet saved has no catalogue entry; the editor still
  // has to open for it, otherwise "add a role" would appear to do nothing.
  const current: RoleInfo | null = selected
    ? data?.roles.find((r) => r.name === selected) ?? {
      name: selected, sources: [], managedPolicy: managedPolicyName(selected),
      hasManagedPolicy: false, members: [],
    }
    : null
  const listed = data
    ? [...data.roles, ...(current && !data.roles.some((r) => r.name === current.name) ? [current] : [])]
    : []

  // seed the editor from the role's MANAGED grants: those are the ones this
  // surface owns, so they are what an unedited save would write back
  useEffect(() => {
    if (!data || !selected) return
    const managed = new Set<string>()
    for (const grant of data.grants) {
      if (!grant.managed || !grant.roles.includes(selected)) continue
      for (const action of grant.actions) managed.add(action)
    }
    setDraft(managed)
    setSite('')
  }, [data, selected])

  const save = useMutation({
    mutationFn: () => apiClient.saveRole(selected!, [...draft], site.trim() || null),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-roles'] }),
  })
  const remove = useMutation({
    mutationFn: (name: string) => apiClient.deleteRole(name),
    onSuccess: () => { setConfirmDelete(null); setSelected(null); qc.invalidateQueries({ queryKey: ['admin-roles'] }) },
  })

  if (roles.isLoading) return <Skeleton rows={6} />
  if (roles.error) return <ErrorBanner error={roles.error} />
  if (!data) return null

  const cell = (role: string, action: string) => data.matrix[role]?.[action]
  const grantedByHand = (role: string, action: string) => {
    const c = cell(role, action)
    return Boolean(c?.granted && !c.managed)
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      {save.error ? (
        <Alert tone="danger" title={t('access.failed')}>
          {save.error instanceof ApiError ? save.error.message : String(save.error)}
        </Alert>
      ) : null}
      {save.isSuccess ? <Alert tone="success">{t('access.roleSaved', { role: selected ?? '' })}</Alert> : null}

      <Card
        padded={false}
        className="flex min-h-0 flex-1 flex-col"
        bodyClassName="flex min-h-0 flex-1 flex-col"
      >
        <div className="grid min-h-0 flex-1 lg:grid-cols-[260px_1fr]">
          <aside className="flex min-h-0 flex-col border-b lg:border-b-0 lg:border-r"
                 style={{ borderColor: 'var(--border-subtle)' }}>
            <div className="flex items-center gap-2 px-3 py-2.5" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
              <input
                className="ontogeny-input font-mono text-[12px]"
                placeholder={t('access.newRole')}
                value={newRole}
                data-testid="new-role"
                onChange={(e) => setNewRole(e.target.value)}
              />
              <Button
                size="sm"
                data-testid="add-role"
                disabled={!newRole.trim()}
                icon={<IconPlus width={13} height={13} />}
                onClick={() => { setSelected(newRole.trim()); setNewRole('') }}
              />
            </div>
            <ul className="min-h-0 flex-1 overflow-y-auto p-2" data-testid="role-list">
              {listed.map((r) => (
                <li key={r.name}>
                  <button
                    type="button"
                    data-testid={`role-${r.name}`}
                    onClick={() => setSelected(r.name)}
                    className="flex w-full items-start gap-2 rounded-lg px-2.5 py-2 text-left transition-colors"
                    style={{ background: r.name === selected ? 'var(--brand-tint)' : 'transparent' }}
                  >
                    <span className="min-w-0 flex-1">
                      <span className="flex items-center gap-1.5">
                        <span className="truncate font-mono text-[12.5px]">{r.name}</span>
                        {r.current ? <Badge tone="info">{t('access.currentIdentity')}</Badge> : null}
                        {r.deletable === false ? <Badge tone="warning" title={t('access.roleLocked')}>!</Badge> : null}
                      </span>
                      <span className="mt-0.5 flex flex-wrap items-center gap-1">
                        <SourceChips role={r} />
                        {r.members.length ? (
                          <span className="text-[10.5px] muted">{t('access.members', { count: r.members.length })}</span>
                        ) : null}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </aside>

          <section className="min-h-0 flex-1 overflow-y-auto p-4">
            {!current ? (
              <EmptyState
                icon={<IconShield width={20} height={20} />}
                title={t('access.pickRole')}
                description={t('access.pickRoleHint')}
              />
            ) : (
              <div className="flex flex-col gap-4">
                <header className="flex flex-wrap items-center justify-between gap-3">
                  <div className="min-w-0">
                    <h2 className="flex flex-wrap items-center gap-2 text-[14px] font-semibold">
                      <span className="font-mono">{current.name}</span>
                      {current.current ? <Badge tone="info">{t('access.currentIdentity')}</Badge> : null}
                      <Badge tone={current.hasManagedPolicy ? 'success' : 'neutral'}>
                        {current.hasManagedPolicy ? t('access.managed') : t('access.notManaged')}
                      </Badge>
                      <Badge tone={current.deletable === false ? 'warning' : 'success'}>
                        {current.deletable === false ? t('access.roleLocked') : t('access.roleDeletable')}
                      </Badge>
                    </h2>
                    <p className="mt-0.5 text-[12px] muted">
                      {t('access.roleHint', { policy: current.managedPolicy })}
                    </p>
                  </div>
                  <span className="flex items-center gap-2">
                    <Button size="sm" variant="danger" data-testid="delete-role"
                            disabled={current.deletable === false}
                            title={current.deletable === false ? t('access.roleLocked') : undefined}
                            onClick={() => setConfirmDelete(current.name)}
                            icon={<IconTrash width={13} height={13} />}>
                      {t('access.deleteRole')}
                    </Button>
                    <Button size="sm" variant="primary" data-testid="save-role"
                            disabled={save.isPending}
                            onClick={() => save.mutate()}
                            icon={<IconCheck width={13} height={13} />}>
                      {save.isPending ? t('access.saving') : t('access.saveRole')}
                    </Button>
                  </span>
                </header>

                <div className="flex flex-wrap items-center gap-3">
                  <label className="flex items-center gap-2 text-[12.5px]">
                    <span className="ontogeny-label" style={{ marginBottom: 0 }}>{t('access.scopeToSite')}</span>
                    <input className="ontogeny-input w-40 font-mono" value={site} data-testid="role-site"
                           placeholder="north" onChange={(e) => setSite(e.target.value)} />
                  </label>
                  <span className="text-[11.5px] muted">{t('access.scopeHint')}</span>
                  <span className="ml-auto text-[11.5px] muted tnum">
                    {t('access.grantCount', { count: draft.size })}
                  </span>
                </div>

                <div className="overflow-hidden rounded-xl" style={{ border: '1px solid var(--border-subtle)' }}>
                  <table className="w-full">
                    <thead>
                      <tr>
                        <th scope="col" className="ontogeny-th">{t('access.action')}</th>
                        <th scope="col" className="ontogeny-th" style={{ width: 90, textAlign: 'center' }}>
                          {t('access.allowed')}
                        </th>
                        <th scope="col" className="ontogeny-th">{t('access.grantedBy')}</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.actions.map((action) => {
                        const c = cell(current.name, action)
                        const byHand = grantedByHand(current.name, action)
                        const on = draft.has(action) || byHand
                        return (
                          <tr key={action}>
                            <td className="ontogeny-td font-mono text-[12px]">{action}</td>
                            <td className="ontogeny-td" style={{ textAlign: 'center' }}>
                              <input
                                type="checkbox"
                                className="size-4"
                                data-testid={`grant-${current.name}-${action}`}
                                checked={on}
                                disabled={byHand}
                                title={byHand ? t('access.byHandLocked') : undefined}
                                onChange={(e) => {
                                  const next = new Set(draft)
                                  if (e.target.checked) next.add(action)
                                  else next.delete(action)
                                  setDraft(next)
                                }}
                              />
                            </td>
                            <td className="ontogeny-td">
                              {byHand ? (
                                <span className="flex flex-wrap items-center gap-1.5">
                                  <Badge tone="warning" mono>{c?.source}</Badge>
                                  {c?.conditional ? <Badge tone="info">{t('access.conditional')}</Badge> : null}
                                  {c?.anyPrincipal ? <Badge tone="neutral">{t('access.anyPrincipal')}</Badge> : null}
                                  <span className="text-[11px] muted">{t('access.byHandLocked')}</span>
                                </span>
                              ) : draft.has(action) ? (
                                <Badge tone="success">{t('access.managed')}</Badge>
                              ) : (
                                <span className="muted text-[12px]">—</span>
                              )}
                            </td>
                          </tr>
                        )
                      })}
                    </tbody>
                  </table>
                </div>

                <Alert tone="info">{t('access.planeNote')}</Alert>
              </div>
            )}
          </section>
        </div>
      </Card>

      <ConfirmDialog
        open={confirmDelete !== null}
        title={t('access.confirmDeleteRole')}
        message={t('access.confirmDeleteRoleHint', { role: confirmDelete ?? '' })}
        confirmLabel={t('access.deleteRole')}
        cancelLabel={t('common.cancel')}
        onCancel={() => setConfirmDelete(null)}
        onConfirm={() => confirmDelete && remove.mutate(confirmDelete)}
      />
    </div>
  )
}

/** Where a role comes from: the declared vocabulary, a policy, or an account. */
function SourceChips({ role }: { role: RoleInfo }) {
  const { t } = useI18n()
  const tone = role.sources.includes('policy') ? 'info' : role.sources.includes('user') ? 'brand' : 'neutral'
  return (
    <span className="flex flex-wrap gap-1">
      {role.sources.map((s) => (
        <span
          key={s}
          className="rounded-full px-1.5 py-px text-[9.5px] font-semibold"
          style={toneSurface(tone)}
          title={t(`access.source.${s}`)}
        >
          {t(`access.source.${s}`)}
        </span>
      ))}
    </span>
  )
}

/* --------------------------------------------------------------- identity */

/** The roles a principal carries, however it spells them (presets use `Role`,
 *  account principals carry both spellings). */
function rolesOf(p: Principal | null): string[] {
  return ((p?.Role ?? p?.roles ?? []) as string[])
}

function PrincipalFacts({ p }: { p: Principal | null }) {
  const { t } = useI18n()
  const roles = rolesOf(p)
  return (
    <div data-testid="principal-facts">
      <div className="flex items-center gap-2">
        <span className="truncate font-mono text-[13px]">{p?.id ?? '—'}</span>
        {p?.display && p.display !== p.id ? (
          <span className="truncate text-[11.5px] muted">{p.display}</span>
        ) : null}
      </div>
      <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
        {roles.length === 0 ? <span className="text-[11px] muted">{t('access.noRoles')}</span> : null}
        {roles.map((r) => <span key={r} className="ontogeny-code">{r}</span>)}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-4 text-[11.5px] muted">
        <span>{t('topbar.site')}: <span className="font-mono">{p?.site ?? '—'}</span></span>
        <span>{t('access.markings')}: <span className="font-mono">{(p?.markings ?? []).join(', ') || '—'}</span></span>
      </div>
    </div>
  )
}

/** Actions a role may perform, read out of the same compiled-Cedar matrix the
 *  roles tab edits — the two halves of this page are one dataset. */
function GrantedActions({ role }: { role: string }) {
  const { t } = useI18n()
  const roles = useQuery({ queryKey: ['admin-roles'], queryFn: apiClient.roles })
  const cells = roles.data?.matrix[role]
  const granted = cells ? Object.entries(cells).filter(([, c]) => c.granted).map(([a]) => a) : []
  if (!cells) return <span className="text-[11.5px] muted">—</span>
  if (granted.length === 0) return <span className="text-[11.5px] muted">{t('access.identity.noGrants')}</span>
  return (
    <span className="flex flex-wrap gap-1">
      {granted.map((a) => <Badge key={a} tone="brand" mono>{a}</Badge>)}
    </span>
  )
}

/** 身份模拟 — the acting-as surface for development and CI.
 *
 * The server resolves ONE principal per request with a fixed precedence
 * (session cookie > bearer token > the `X-Ontogeny-Principal` dev header > anonymous).
 * This tab makes that precedence a visible fact instead of a silent surprise:
 * the status card names the winner, a chosen-but-shadowed simulation says so,
 * and applying a preset signs the session out first — because a simulation
 * chosen *under* a session is stored, sent, and then ignored by the server.
 * The override itself lives in localStorage (`ontogeny.principal`) and rides every
 * request as the dev header; `dev_auth` off on the server disables this tab
 * and the header together.
 */
function Identity() {
  const { t } = useI18n()
  const { principal, devAuth, isAdmin, signOut, refresh } = useAuth()
  const [custom, setCustom] = useState('')
  const [customError, setCustomError] = useState<'json' | 'header' | null>(null)
  const override = getDevPrincipal()
  const via = principal?.via ?? 'anonymous'

  const apply = async (p: Principal | null) => {
    setPrincipal(p)
    // re-ask the server: the status card must reflect the resolution that will
    // actually decide the NEXT request, not the one we assume happened
    await refresh()
  }
  const simulate = async (p: Principal) => {
    // a live session outranks the header, so becoming someone else means
    // leaving this account first; signOut clears the override, so re-set it
    if (via === 'session' || via === 'bearer') {
      await signOut()
      setPrincipal(p)
      await refresh()
    } else {
      await apply(p)
    }
  }
  const applyCustom = () => {
    try {
      const parsed = JSON.parse(custom) as Principal
      if (!parsed?.id) { setCustomError('json'); return }
      // non-ASCII cannot ride an HTTP header: fail here rather than inside fetch
      if (!headerSafe(parsed)) { setCustomError('header'); return }
      setCustomError(null)
      void simulate(parsed)
    } catch {
      setCustomError('json')
    }
  }

  const simulated = via === 'dev-header'
  const shadowed = (via === 'session' || via === 'bearer') && override !== null
  const roles = [...new Set([...rolesOf(principal), ...(override ? rolesOf(override) : [])])]

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4" data-testid="identity-sim">
      {/* the resolution status: WHICH identity the server will decide with */}
      <Card>
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-[13.5px] font-semibold">{t('access.identity.effective')}</h2>
          <span data-testid="identity-via">
            <Badge tone={simulated ? 'warning' : via === 'anonymous' ? 'danger' : 'info'}>
              {t(`access.identity.via.${via}`)}
            </Badge>
          </span>
          {principal?.authenticated === false ? (
            <span className="text-[11px] muted">{t('access.identity.notAnAccount')}</span>
          ) : null}
        </div>
        <div className="mt-3">
          <PrincipalFacts p={principal} />
        </div>

        {simulated ? (
          <div className="mt-3">
            <Alert tone="info" title={t('access.identity.simActive')}>
              {t('access.identity.simActiveHint')}
            </Alert>
            <div className="mt-2 flex justify-end">
              <Button size="sm" data-testid="sim-exit" onClick={() => void apply(null)}>
                {t('access.identity.exitSim')}
              </Button>
            </div>
          </div>
        ) : null}

        {shadowed ? (
          <div className="mt-3">
            <Alert tone="warning" title={t('access.identity.shadowed', { id: override!.id })}>
              {t('access.identity.shadowedHint')}
            </Alert>
            <div className="mt-2 flex justify-end">
              <Button size="sm" variant="primary" data-testid="sim-activate"
                      onClick={() => void simulate(override!)}>
                {t('access.identity.signOutAndSimulate')}
              </Button>
            </div>
          </div>
        ) : null}

        {!devAuth && override ? (
          <div className="mt-3">
            <Alert tone="warning">{t('access.identity.devAuthOff')}</Alert>
          </div>
        ) : null}
      </Card>

      {/* the picker: presets and ad-hoc JSON, moved here from the settings
          dialog — next to the roles it simulates */}
      <Card>
        <h2 className="text-[13.5px] font-semibold">{t('access.identity.pick')}</h2>
        <p className="mt-0.5 text-[12px] muted">{t('access.identity.pickHint')}</p>
        <div className="mt-3 grid grid-cols-2 gap-1.5 lg:grid-cols-3">
          {Object.entries(PRESET_PRINCIPALS).map(([key, p]) => {
            const activePreset = simulated && override?.id === p.id
            return (
              <button
                key={key}
                type="button"
                data-testid={`sim-preset-${key}`}
                title={shadowed || via === 'session' || via === 'bearer'
                  ? t('access.identity.signOutAndSimulateTitle') : undefined}
                onClick={() => void simulate(p)}
                className="rounded-lg px-2.5 py-2 text-left text-[12px] transition-colors"
                style={{
                  background: activePreset ? 'var(--brand-tint)' : 'var(--surface-sunken)',
                  boxShadow: activePreset ? 'inset 0 0 0 1px var(--brand-tint-ring)' : 'none',
                }}
              >
                <div className="font-mono text-[11.5px]">{p.id}</div>
                <div className="muted">{(p.Role ?? []).join(', ')}</div>
              </button>
            )
          })}
        </div>

        <div className="my-3 ontogeny-divider" />
        <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-[0.06em] muted">
          {t('access.identity.custom')}
        </div>
        <div className="flex gap-2">
          <input
            className="ontogeny-input font-mono"
            placeholder='{"id":"u","Role":["planner"],"site":"north"}'
            value={custom}
            data-testid="sim-custom"
            onChange={(e) => setCustom(e.target.value)}
          />
          <Button data-testid="sim-apply" onClick={applyCustom}>{t('access.identity.apply')}</Button>
        </div>
        {customError === 'json' ? (
          <div className="mt-2"><Alert tone="danger">{t('access.identity.badJson')}</Alert></div>
        ) : null}
        {customError === 'header' ? (
          <div className="mt-2"><Alert tone="danger">{t('access.identity.badHeader')}</Alert></div>
        ) : null}

        <div className="mt-3 flex items-center justify-between gap-2">
          <span className="text-[11.5px] muted">{t('access.identity.overrideNote')}</span>
          <Button size="sm" data-testid="sim-clear" disabled={!override} onClick={() => void apply(null)}>
            {t('access.identity.clearSim')}
          </Button>
        </div>
      </Card>

      {/* the bridge to the roles tab: what these roles may do, per the matrix */}
      {isAdmin ? (
        <Card>
          <h2 className="text-[13.5px] font-semibold">{t('access.identity.grantsTitle')}</h2>
          <p className="mt-0.5 text-[12px] muted">{t('access.identity.grantsHint')}</p>
          <div className="mt-3 flex flex-col gap-2.5">
            {roles.length === 0 ? (
              <span className="text-[12px] muted">{t('access.noRoles')}</span>
            ) : roles.map((r) => (
              <div key={r} className="flex flex-wrap items-center gap-2" data-testid={`sim-role-${r}`}>
                <span className="ontogeny-code">{r}</span>
                <span className="muted">→</span>
                <GrantedActions role={r} />
              </div>
            ))}
          </div>
        </Card>
      ) : null}
    </div>
  )
}
