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
 * Who is signed in, for the whole app.
 *
 * One provider above the router answers that question once, from the server
 * (`GET /auth/me`) rather than from a flag in localStorage: the session is an
 * HttpOnly cookie the page cannot read, so "am I logged in?" is only knowable by
 * asking. A 401 is not an error here — it is the answer "nobody".
 *
 * While `loading` the app renders nothing but a splash: flashing the login form
 * at an already-signed-in user on every reload is the classic bug of doing this
 * check in an effect without a loading state.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { apiClient, ApiError, setPrincipal, type AccountUser } from '../api/client'
import type { Principal } from '../api/types'

interface AuthValue {
  principal: Principal | null
  /** True while the first `/auth/me` is in flight. */
  loading: boolean
  /** The backend still accepts the `X-Ontogeny-Principal` dev header. */
  devAuth: boolean
  /** Accounts may be administered by the current user. */
  isAdmin: boolean
  signIn: (username: string, password: string) => Promise<void>
  signOut: () => Promise<void>
  /** Re-read the principal (after an admin edits its own account). */
  refresh: () => Promise<void>
}

const Ctx = createContext<AuthValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [principal, setCurrent] = useState<Principal | null>(null)
  const [loading, setLoading] = useState(true)
  const [devAuth, setDevAuth] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const me = await apiClient.me()
      setCurrent(me.principal)
      setDevAuth(Boolean(me.dev_auth))
    } catch (e) {
      // 401 is the normal "not signed in" answer; anything else is a real
      // failure and also leaves us signed out rather than half-configured
      if (!(e instanceof ApiError) || e.status !== 401) {
        // eslint-disable-next-line no-console -- surfaced by the login page
        console.warn('auth/me failed:', e)
      }
      setCurrent(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { void refresh() }, [refresh])

  const signIn = useCallback(async (username: string, password: string) => {
    const res = await apiClient.login(username, password)
    setCurrent(res.principal)
    // the session cookie IS the identity now; a leftover dev override would be
    // sent as a header on every request and (with a non-ASCII display name) is
    // not even a legal header value
    setPrincipal(null)
  }, [])

  const signOut = useCallback(async () => {
    try {
      await apiClient.logout()
    } finally {
      // signing out means landing in the logged-out state: a leftover dev
      // override would immediately "sign in" a simulated identity instead of
      // showing the login form. The identity tab re-applies its choice AFTER
      // this when the user asked to sign out *into* a simulation.
      setPrincipal(null)
      setCurrent(null)
    }
  }, [])

  const value = useMemo<AuthValue>(() => ({
    principal, loading, devAuth,
    isAdmin: Boolean((principal as Principal & { is_admin?: boolean } | null)?.is_admin),
    signIn, signOut, refresh,
  }), [principal, loading, devAuth, signIn, signOut, refresh])

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>
}

export function useAuth(): AuthValue {
  const ctx = useContext(Ctx)
  if (!ctx) throw new Error('useAuth must be used inside AuthProvider')
  return ctx
}

/** True when the account carries the administrator flag. */
export function isAdminUser(u: AccountUser | null): boolean {
  return Boolean(u?.is_admin)
}
