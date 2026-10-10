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

from unittest.mock import Mock

import pytest

from hugegraph_llm.config import huge_settings
from hugegraph_llm.utils.hugegraph_utils import get_hg_client


def test_request_connection_passes_canonical_validated_url(monkeypatch):
    monkeypatch.setattr(huge_settings, "graph_url", "127.0.0.1:8080")
    client = Mock()
    factory = Mock(return_value=client)
    monkeypatch.setattr("hugegraph_llm.utils.hugegraph_utils.PyHugeClient", factory)

    result = get_hg_client(
        {
            "url": "http://127.0.0.1:8080/",
            "graph": "hugegraph",
            "user": "admin",
            "pwd": "secret",
            "graphspace": "DEFAULT",
        }
    )

    assert result is client
    assert factory.call_args.kwargs["url"] == "http://127.0.0.1:8080"


@pytest.mark.parametrize("url", ["http://:80", "http://user@127.0.0.1:8080", "http://[::1"])
def test_request_connection_rejects_invalid_url_before_client_construction(monkeypatch, url):
    monkeypatch.setattr(huge_settings, "graph_url", "http://127.0.0.1:8080")
    factory = Mock()
    monkeypatch.setattr("hugegraph_llm.utils.hugegraph_utils.PyHugeClient", factory)

    with pytest.raises(ValueError, match="Graph URL"):
        get_hg_client(
            {
                "url": url,
                "graph": "hugegraph",
                "user": "admin",
                "pwd": "secret",
                "graphspace": None,
            }
        )

    factory.assert_not_called()
