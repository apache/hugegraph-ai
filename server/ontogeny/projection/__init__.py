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
"""ontogeny.projection -- the graph-projection *contract* and worker.

``compile_projection`` turns the ontology into store-neutral schema payloads;
``ProjectionWorker`` consumes outbox events against any :class:`GraphStore`.
Concrete stores live in ``extensions/`` (``graph-hugegraph`` ships with the
repo) and are injected via ``sc.graph_store_factory`` -- the graph is a derived,
rebuildable index, so its absence only means SQL-only operation.
"""
from .compiler import compile_projection
from .worker import GraphStore, ProjectionWorker

__all__ = ["compile_projection", "GraphStore", "ProjectionWorker"]
