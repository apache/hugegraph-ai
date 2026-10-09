# Copyright 2026 Apache HugeGraph Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""ontogeny.policy -- Cedar-subset engine (portable default driver).

If cedarpy is installed it takes precedence at ServiceContext assembly time;
this module remains the deterministic CI reference.
"""

from .engine import PermitRule, PolicyDecision, PolicyEngine, parse_policy_set

__all__ = ["PolicyEngine", "PolicyDecision", "PermitRule", "parse_policy_set"]
