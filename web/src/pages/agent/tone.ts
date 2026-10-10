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
/** Tone mapping shared by the agent surfaces (console transcript + panels).
 *
 * Its own module so the panel file exports only components (React Fast Refresh)
 * and so the console and the session list can never disagree about what
 * "pending_approval" or "blocked_on_approval" looks like. */

export const outcomeTone = (code: string): 'success' | 'warning' | 'danger' | 'neutral' => {
  if (code === 'ok' || code === 'executed') return 'success'
  if (code === 'pending_approval') return 'warning'
  if (code === 'POLICY_DENIED' || code === 'RULE_REJECTED' || code === 'AGENT_BUDGET_EXCEEDED') return 'danger'
  return 'neutral'
}

export const statusTone = (status: string): 'success' | 'warning' | 'danger' | 'brand' | 'neutral' => {
  if (status === 'open') return 'success'
  if (status === 'running') return 'brand'
  if (status === 'blocked_on_approval') return 'warning'
  if (status === 'budget_exhausted') return 'danger'
  return 'neutral'
}
