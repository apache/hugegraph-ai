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
# specific language governing permissions and limitations
# under the License.

"""Register the external-agent document extractor.

The capability is only wired when ``ONTOGENY_DOC_AGENT_CMD`` or
``ONTOGENY_DOC_AGENT_URL`` is configured: an "extractor loaded but unusable"
state is worse than telling the console to configure one.
"""

from __future__ import annotations

from .adapter import AgentExtractor

__all__ = ["AgentExtractor", "register"]


def register(sc, host) -> None:
    configured = bool(sc.settings.doc_agent_cmd or sc.settings.doc_agent_url)
    if configured:
        sc.document_extractor_factory = lambda service: AgentExtractor(service)
    host.provide(
        "capability:document-extractor",
        {"extension": "doc-extract-agent", "configured": configured},
    )
