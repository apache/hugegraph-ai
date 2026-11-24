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

import pytest

from hugegraph_mcp.config import MCPConfig
from hugegraph_mcp.confirmation_policy import requires_interactive_confirmation, resolve_confirmation_mode


def test_confirmation_mode_parsing_and_policy():
    assert resolve_confirmation_mode(None) == "manual"
    assert resolve_confirmation_mode("ELICITATION") == "elicitation"
    with pytest.raises(ValueError):
        resolve_confirmation_mode("auto")

    stdio_cfg = MCPConfig(transport="stdio", confirmation_mode="elicitation")
    assert requires_interactive_confirmation(stdio_cfg, side_effect="write") is True
    assert requires_interactive_confirmation(stdio_cfg, side_effect="read") is False

    http_cfg = MCPConfig(transport="streamable-http", confirmation_mode="elicitation")
    assert requires_interactive_confirmation(http_cfg, side_effect="write") is False
