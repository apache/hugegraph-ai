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
"""Agent plugin surface: the ontology compiled into a governed tool catalog.

External agents (any runtime: HTTP client, MCP client, scripted driver) never
get raw stores or SQL. They get a session-bounded view of tools the ontology
itself compiles -- searching objects, invoking functions, traversing links,
executing actions -- and every call runs through the same ServiceContext as
humans: same Cedar policy, same masking, same audit (invariants I1-I3).
"""
