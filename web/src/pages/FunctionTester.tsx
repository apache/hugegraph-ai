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
import { useMutation } from '@tanstack/react-query'
import { apiClient } from '../api/client'
import { useMeta } from '../api/queries'
import { useI18n } from '../i18n'
import { Badge, Button, Card, KeyValue, Page, Skeleton } from '../components/ui'
import { ErrorBanner } from '../components/ErrorBanner'
import { JsonView } from '../components/JsonView'
import { ParamForm, type ParamValues } from '../components/ParamForm'
import { IconArrowLeft, IconPlay } from '../components/icons'

export function FunctionTester() {
  const { name = '' } = useParams()
  const { t } = useI18n()
  const meta = useMeta()
  const fn = meta.data?.functions[name]
  const [values, setValues] = useState<ParamValues>({})
  const invoke = useMutation({ mutationFn: () => apiClient.invokeFunction(name, values as Record<string, unknown>) })

  if (meta.isLoading) return <Skeleton rows={6} />
  if (!fn) return <ErrorBanner error={{ code: 'NOT_FOUND', message: `unknown function: ${name}` }} />

  const missing = Object.entries(fn.parameters)
    .filter(([n, p]) => p.required && (values[n] === undefined || values[n] === null || values[n] === ''))
    .map(([n]) => n)

  return (
    <Page>
      <h1 className="sr-only">{name}</h1>

      <div className="grid gap-5 lg:grid-cols-2">
        {/* breadcrumb, function name and entry chip live on the parameters
            panel: it is the page's one primary surface */}
        <Card
          title={
            <span className="flex items-center gap-2">
              <Link className="ontogeny-link inline-flex items-center gap-1 text-[12.5px] muted" to="/ontology">
                <IconArrowLeft width={13} height={13} />
                {t('nav.ontology')}
              </Link>
              <span className="muted">/</span>
              <span className="font-mono">{name}</span>
            </span>
          }
          description={t('function.sandbox')}
          actions={<Badge tone="info" mono>{fn.entry}</Badge>}
        >
          <ParamForm parameters={fn.parameters} value={values} onChange={setValues} />
          <div className="mt-4">
            <Button variant="primary" onClick={() => invoke.mutate()} disabled={missing.length > 0} data-testid="invoke-function" icon={<IconPlay width={14} height={14} />}>
              {t('function.invoke')}
            </Button>
          </div>
        </Card>
        <div className="flex flex-col gap-5">
          {!invoke.data && !invoke.error ? (
            <Card title={t('function.contractTitle')} description={t('function.contractHint')}>
              <KeyValue items={[{ key: t('function.entry'), value: fn.entry, mono: true }]} />
              <ul className="mt-3 flex flex-col gap-1.5 text-[12px] secondary-text">
                <li>· {t('function.contractSandbox')}</li>
                <li>· {t('function.contractCapabilities')}</li>
                <li>· {t('function.contractVersion')}</li>
              </ul>
            </Card>
          ) : null}
          {invoke.error ? <ErrorBanner error={invoke.error} /> : null}
          {invoke.data ? (
            <Card title={t('function.returnValue')}>
              <JsonView value={invoke.data.value} />
            </Card>
          ) : null}
        </div>
      </div>
    </Page>
  )
}
