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
 * Sign-in. The only screen outside the shell — no navigation, no identity
 * picker, nothing to click except the form, because an unauthenticated visitor
 * has exactly one useful action.
 *
 * It is deliberately a *page* rather than a modal over the app: the shell's data
 * (meta, counts, the sidebar) is all fetched per-principal, and rendering it
 * behind a login dialog would mean fetching everything twice and briefly showing
 * a stranger the shape of the deployment.
 */
import { useState } from 'react'
import { useAuth } from '../api/auth'
import { useI18n } from '../i18n'
import { ApiError } from '../api/client'
import { Alert, Button } from '../components/ui'
import { IconShield, IconUser } from '../components/icons'

export function Login() {
  const { t } = useI18n()
  const { signIn } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!username.trim() || !password) return
    setBusy(true)
    setError(null)
    try {
      await signIn(username.trim(), password)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : String(err))
      setPassword('')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div
      className="grid min-h-full place-items-center p-4"
      style={{ background: 'var(--surface-app)' }}
      data-testid="login-page"
    >
      <div className="w-full max-w-[380px]">
        <div className="mb-6 flex items-center gap-3">
          <img src="/icon.png" alt="" width={36} height={36} className="size-9 shrink-0" />
          <div className="min-w-0">
            <div className="ontogeny-wordmark text-[17px]" style={{ color: 'var(--text-primary)' }}>
              {t('app.name')}
            </div>
            <div className="text-[8.5px] leading-snug" style={{ color: 'var(--text-muted)', letterSpacing: '0.08em' }}>
              {t('app.tagline')}
            </div>
          </div>
        </div>

        <form
          onSubmit={submit}
          className="ontogeny-card flex flex-col gap-3.5 p-5"
          style={{ boxShadow: 'var(--shadow-float)' }}
        >
          <div>
            <h1 className="text-[15px] font-semibold">{t('login.title')}</h1>
            <p className="mt-0.5 text-[12px] muted">{t('login.subtitle')}</p>
          </div>

          <label className="block">
            <span className="ontogeny-label" style={{ marginBottom: 4 }}>{t('login.username')}</span>
            <span className="relative block">
              <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 muted">
                <IconUser width={14} height={14} />
              </span>
              <input
                className="ontogeny-input pl-8"
                value={username}
                autoFocus
                autoComplete="username"
                data-testid="login-username"
                onChange={(e) => setUsername(e.target.value)}
              />
            </span>
          </label>

          <label className="block">
            <span className="ontogeny-label" style={{ marginBottom: 4 }}>{t('login.password')}</span>
            <span className="relative block">
              <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 muted">
                <IconShield width={14} height={14} />
              </span>
              <input
                type="password"
                className="ontogeny-input pl-8"
                value={password}
                autoComplete="current-password"
                data-testid="login-password"
                onChange={(e) => setPassword(e.target.value)}
              />
            </span>
          </label>

          {error ? (
            <Alert tone="danger" testId="login-error">{error}</Alert>
          ) : null}

          <Button
            variant="primary"
            type="submit"
            data-testid="login-submit"
            disabled={busy || !username.trim() || !password}
          >
            {busy ? t('login.signingIn') : t('login.signIn')}
          </Button>

          <p className="text-[11px] leading-relaxed muted">{t('login.hint')}</p>
        </form>
      </div>
    </div>
  )
}
