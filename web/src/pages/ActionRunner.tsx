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
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import { useMeta } from '../api/queries'
import { useI18n } from '../i18n'
import { Badge, Button, Card, KeyValue, Page, Skeleton } from '../components/ui'
import { ErrorBanner } from '../components/ErrorBanner'
import { JsonView } from '../components/JsonView'
import { ParamForm, type ParamValues } from '../components/ParamForm'
import { IconArrowLeft, IconCheck, IconPlay, IconX } from '../components/icons'

interface ValidateResult {
  parameters: Record<string, unknown>
  rules: Array<{ expr: string; ok: boolean; message: string | null }>
  policy: { allow: boolean; reason: string }
}
interface ExecuteResult {
  revision_id: number
  outcome: string
  object_id: string
  after: Record<string, unknown> | null
}

export function ActionRunner() {
  const { name = '' } = useParams()
  const { t } = useI18n()
  const qc = useQueryClient()
  const meta = useMeta()
  const action = meta.data?.actions[name]

  const [values, setValues] = useState<ParamValues>({})
  const [targetId, setTargetId] = useState('')
  const [idemKey, setIdemKey] = useState('')
  const [expectedRev, setExpectedRev] = useState('')

  const validate = useMutation({
    mutationFn: () => apiClient.validateAction(name, { parameters: values, target_id: targetId || null }),
  })
  const execute = useMutation({
    mutationFn: () =>
      apiClient.executeAction(name, {
        parameters: values,
        target_id: targetId || null,
        expected_revision: expectedRev ? Number(expectedRev) : null,
        idempotency_key: idemKey || null,
      }),
    // an execute writes the target object, its revision history and the audit
    // trail -- invalidate those, not the whole cache (the unscoped call threw
    // away the loaded meta, extensions and projection too)
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['object'] })
      qc.invalidateQueries({ queryKey: ['history'] })
      qc.invalidateQueries({ queryKey: ['revisions'] })
      qc.invalidateQueries({ queryKey: ['objects'] })
      qc.invalidateQueries({ queryKey: ['data-preview'] })
    },
  })

  if (meta.isLoading) return <Skeleton rows={6} />
  if (!action) return <ErrorBanner error={{ code: 'NOT_FOUND', message: `unknown action: ${name}` }} />

  const missing = Object.entries(action.parameters)
    .filter(([n, p]) => p.required && (values[n] === undefined || values[n] === null || values[n] === ''))
    .map(([n]) => n)

  return (
    <Page>
      <h1 className="sr-only">{name}</h1>

      <div className="grid gap-5 lg:grid-cols-[1.15fr_1fr]">
        {/* breadcrumb, action name and target chip live on the parameters
            panel: it is the page's one primary surface */}
        <Card
          title={
            <span className="flex items-center gap-2">
              <Link className="ontogeny-link inline-flex items-center gap-1 text-[12.5px] muted" to={`/ontology/${action.target}`}>
                <IconArrowLeft width={13} height={13} />
                {action.target}
              </Link>
              <span className="muted">/</span>
              <span className="font-mono">{name}</span>
            </span>
          }
          description={action.display}
          actions={<Badge tone="violet">{t('action.target')}: {action.target}</Badge>}
        >
          <ParamForm parameters={action.parameters} value={values} onChange={setValues} />
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <div>
              <label className="ontogeny-label" htmlFor="target-id">{t('action.targetId')}</label>
              <input id="target-id" className="ontogeny-input font-mono" value={targetId} onChange={(e) => setTargetId(e.target.value)} placeholder={action.target} />
            </div>
            <div>
              <label className="ontogeny-label" htmlFor="idem">{t('action.idempotency')}</label>
              <input id="idem" className="ontogeny-input font-mono" value={idemKey} onChange={(e) => setIdemKey(e.target.value)} placeholder={t('action.optional')} />
            </div>
            <div>
              <label className="ontogeny-label" htmlFor="rev">{t('action.expectedRev')}</label>
              <input id="rev" className="ontogeny-input font-mono" value={expectedRev} onChange={(e) => setExpectedRev(e.target.value)} placeholder="1" />
            </div>
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button onClick={() => validate.mutate()} disabled={missing.length > 0} data-testid="validate-action" icon={<IconCheck width={14} height={14} />}>
              {t('action.validate')}
            </Button>
            <Button variant="primary" onClick={() => execute.mutate()} disabled={missing.length > 0} data-testid="execute-action" icon={<IconPlay width={14} height={14} />}>
              {t('action.execute')}
            </Button>
          </div>
        </Card>

        <div className="flex flex-col gap-5">
          {/* nothing run yet: explain the path the action will take instead of
              leaving half the page blank */}
          {!validate.data && !validate.error && !execute.data && !execute.error ? (
            <Card title={t('action.pathTitle')} description={t('action.pathHint')}>
              <ol className="flex flex-col gap-2.5">
                {[
                  ['action.phase.params', 'action.phase.paramsHint'],
                  ['action.phase.rules', 'action.phase.rulesHint'],
                  ['action.phase.policy', 'action.phase.policyHint'],
                  ['action.phase.effects', 'action.phase.effectsHint'],
                  ['action.phase.audit', 'action.phase.auditHint'],
                ].map(([title, hint], i) => (
                  <li key={title} className="flex items-start gap-3">
                    <span
                      className="mt-0.5 grid size-5 shrink-0 place-items-center rounded-md text-[10.5px] font-semibold tnum"
                      style={{ background: 'var(--brand-tint)', color: 'var(--brand-fg)' }}
                    >
                      {i + 1}
                    </span>
                    <span className="min-w-0">
                      <span className="block text-[12.5px] font-medium">{t(title)}</span>
                      <span className="block text-[11.5px] muted">{t(hint)}</span>
                    </span>
                  </li>
                ))}
              </ol>
            </Card>
          ) : null}
          {validate.error ? <ErrorBanner error={validate.error} /> : null}
          {validate.data ? (
            <Card title={t('action.rulesTitle')} testId="validate-result">
              {(validate.data as unknown as ValidateResult).rules.length === 0 ? (
                <p className="text-[12.5px] muted">{t('common.none')}</p>
              ) : (
                <ul className="flex flex-col gap-2">
                  {(validate.data as unknown as ValidateResult).rules.map((r, i) => (
                    <li key={i} className="flex items-start gap-2.5 rounded-lg px-3 py-2 font-mono text-[11.5px]" style={{ background: 'var(--surface-sunken)' }}>
                      <span style={{ color: r.ok ? 'var(--tone-success-fg)' : 'var(--tone-danger-fg)' }}>{r.ok ? <IconCheck width={13} height={13} /> : <IconX width={13} height={13} />}</span>
                      <span className="min-w-0">
                        <span className="block break-all">{r.expr}</span>
                        {r.message ? <span className="block text-[11px]" style={{ color: 'var(--tone-danger-fg)' }}>{r.message}</span> : null}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              <div className="mt-3 ontogeny-divider" />
              <div className="mt-3">
                <div className="ontogeny-label">{t('action.policyTitle')}</div>
                <Badge tone={(validate.data as unknown as ValidateResult).policy.allow ? 'success' : 'danger'}>
                  {(validate.data as unknown as ValidateResult).policy.allow ? t('action.policyAllow') : t('action.policyDeny')}
                </Badge>
                <p className="mt-2 font-mono text-[11.5px] secondary-text">{(validate.data as unknown as ValidateResult).policy.reason}</p>
              </div>
            </Card>
          ) : null}

          {execute.error ? <ErrorBanner error={execute.error} /> : null}
          {execute.data ? (
            <Card title={t('action.resultTitle')} testId="execute-result">
              <KeyValue
                items={[
                  { key: t('action.revision'), value: `#${(execute.data as ExecuteResult).revision_id}`, mono: true },
                  { key: t('action.outcome'), value: <Badge tone="success">{(execute.data as ExecuteResult).outcome}</Badge> },
                  { key: t('action.target'), value: (execute.data as ExecuteResult).object_id, mono: true },
                ]}
              />
              {(execute.data as ExecuteResult).after ? (
                <div className="mt-3">
                  <div className="ontogeny-label">{t('common.after')}</div>
                  <JsonView value={(execute.data as ExecuteResult).after} />
                </div>
              ) : null}
            </Card>
          ) : null}
        </div>
      </div>
    </Page>
  )
}
