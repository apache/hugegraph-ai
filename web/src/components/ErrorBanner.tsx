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
import type { ReactNode } from 'react'
import { ApiError } from '../api/client'
import { useI18n } from '../i18n'
import { ApiErrorCodeHint } from './ApiErrorCodeHint'
import { Alert } from './ui'

/** Renders the backend's structured error model with a localized explanation. */
export function ErrorBanner({ error, hint }: { error: unknown; hint?: ReactNode }) {
  const { t } = useI18n()
  if (!error) return null
  const e = error instanceof ApiError ? error : null
  const code = e?.code ?? 'ERROR'
  const localized = code ? t(`error.${code}`) : ''
  const message = e?.message ?? String(error)
  const tone = code === 'POLICY_DENIED' || code === 'CONSTITUTION_VIOLATION' ? 'danger'
    : code === 'RULE_REJECTED' ? 'warning'
    : code === 'REVISION_CONFLICT' ? 'warning'
    : 'info'

  return (
    <div data-testid="error-banner">
      <Alert
        tone={tone as 'danger'}
        title={
          <span className="flex items-center gap-2">
            <span className="ontogeny-code">{code}</span>
            <span>{localized && localized !== `error.${code}` ? localized : message}</span>
          </span>
        }
      >
        <div className="flex flex-col gap-1">
          <span className="font-mono text-[11.5px]">{message}</span>
          {hint ? <span>{hint}</span> : null}
          <ApiErrorCodeHint code={code} />
        </div>
      </Alert>
    </div>
  )
}
