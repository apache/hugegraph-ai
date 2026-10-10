# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Live schema fetch helpers shared by V1 tools."""

import logging
from typing import Any

from hugegraph_mcp import schema_tools

LOGGER = logging.getLogger("hugegraph_mcp.live_schema")


def current_live_schema(live_schema: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return the provided schema or fetch the current HugeGraph schema."""

    if live_schema is not None:
        return live_schema
    return schema_tools.get_live_schema()


def fetch_live_schema_or_none() -> dict[str, Any] | None:
    """Best-effort live schema fetch for write paths that return envelopes."""

    try:
        return current_live_schema()
    except Exception as exc:
        LOGGER.warning("Failed to fetch live schema: %s", exc, exc_info=True)
        return None
