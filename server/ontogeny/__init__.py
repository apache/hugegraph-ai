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
"""ontogeny reference backend (v0.3 implementation).

Architecture: docs/ARCHITECTURE.md; implementation plan: docs/implementation.md.
Layers map 1:1 to subpackages: core / registry / stores / engine / action /
policy / functions / projection / telemetry / evolve / api.
All entrypoints (REST API, MCP, CLI, background workers) are thin shells over
`ontogeny.service.ServiceContext` so governance (policy, audit, transactions) has a
single path -- there is no second door.
"""

__version__ = "0.3.0"
