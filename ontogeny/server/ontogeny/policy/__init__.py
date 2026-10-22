# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and
# limitations under the License.

"""ontogeny.policy -- Cedar-subset engine (the deterministic driver).

``forbid`` statements follow Cedar precedence: a matching forbid overrides
any permit.
"""

from .engine import PermitRule, PolicyDecision, PolicyEngine, parse_forbids, parse_policy_set

__all__ = ["PermitRule", "PolicyDecision", "PolicyEngine", "parse_forbids", "parse_policy_set"]
