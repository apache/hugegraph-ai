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
import { useI18n } from '../i18n'

/** Maps an engine error code to the action hint shown next to it. */
export function ApiErrorCodeHint({ code }: { code: string }) {
  const { t } = useI18n()
  const key =
    code === 'RULE_REJECTED' ? 'action.errorHint.rule'
    : code === 'POLICY_DENIED' ? 'action.errorHint.policy'
    : code === 'REVISION_CONFLICT' ? 'action.errorHint.conflict'
    : null
  if (!key) return null
  return <span className="text-[11.5px] opacity-80">{t(key)}</span>
}
