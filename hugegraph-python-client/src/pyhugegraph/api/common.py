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


import json
import re
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from pyhugegraph.api.endpoints import ENDPOINTS
from pyhugegraph.utils.compat import ServerAdapter
from pyhugegraph.utils.exceptions import UnsupportedOperationError
from pyhugegraph.utils.huge_requests import HGraphSession
from pyhugegraph.utils.id_format import format_vertex_id
from pyhugegraph.utils.util import ResponseValidation


class ParameterHolder:
    def __init__(self):
        self._dic = {}

    def set(self, key, value):
        self._dic[key] = value

    def get_value(self, key):
        if key not in self._dic:
            return None
        return self._dic[key]

    def get_dic(self):
        return self._dic

    def get_keys(self):
        return self._dic.keys()


class HGraphContext:
    def __init__(self, sess: HGraphSession) -> None:
        self._sess = sess

    @property
    def session(self) -> HGraphSession:
        return self._sess


_UNSET = object()


class RestResource(HGraphContext):
    """Request an explicit catalog operation through the shared transport."""

    def request(
        self,
        operation: str,
        *,
        path_params: Mapping[str, Any] | None = None,
        params: Mapping[str, Any] | None = None,
        body: Any = _UNSET,
        headers: Mapping[str, str | None] | None = None,
        **kwargs: Any,
    ) -> Any:
        endpoint = ENDPOINTS[operation]
        cfg = self.session.cfg
        if endpoint.get("requires_graphspace") and not cfg.gs_supported:
            raise UnsupportedOperationError(f"{operation} requires a graphspace-enabled server")
        values = {"graphspace": cfg.graphspace, "graph": cfg.graph_name}
        values.update(path_params or {})
        for key in endpoint["vertex_path"]:
            if key in values:
                values[key] = format_vertex_id(values[key])
        path = ServerAdapter(cfg).adapt_path(endpoint["path"])
        required = re.findall(r"{(\w+)}", path)
        for key in required:
            if values.get(key) is None:
                raise ValueError(f"{key} is required for {operation}")
        path = path.format(**{key: quote(str(values[key]), safe="") for key in required})
        query = {}
        for key, value in (params or {}).items():
            if value is None:
                continue
            if key not in endpoint["query"]:
                raise TypeError(f"Unsupported parameter {key!r} for {operation}")

            def encode(item, key=key):
                if key in endpoint["vertex_query"]:
                    return format_vertex_id(item)
                if isinstance(item, bool):
                    return str(item).lower()
                if isinstance(item, Mapping):
                    return json.dumps(item, ensure_ascii=False)
                return item

            query[key] = [encode(item) for item in value] if isinstance(value, (list, tuple)) else encode(value)
        if body is not _UNSET:
            if endpoint["content_type"] == "text/plain":
                kwargs["data"] = body
            else:
                kwargs["data"] = json.dumps(body, ensure_ascii=False)
        merged_headers = {key: value for key, value in (headers or {}).items() if value is not None}
        merged_headers.setdefault("Content-Type", endpoint["content_type"])
        if query:
            kwargs["params"] = query
        content_type = endpoint.get("response_type", "json")
        if endpoint.get("json_when") and all(query.get(key) == value for key, value in endpoint["json_when"].items()):
            content_type = "json"
        kwargs.setdefault("validator", ResponseValidation(content_type=content_type))
        return self.session.request("/" + path, endpoint["method"], headers=merged_headers, **kwargs)


class HugeParamsBase(RestResource):
    """Resource base with state for schema builders."""

    def __init__(self, sess: HGraphSession) -> None:
        super().__init__(sess)
        self._parameter_holder = ParameterHolder()

    def add_parameter(self, key, value):
        self._parameter_holder.set(key, value)

    def get_parameter_holder(self):
        return self._parameter_holder

    def create_parameter_holder(self):
        self._parameter_holder = ParameterHolder()

    def clean_parameter_holder(self):
        self._parameter_holder = ParameterHolder()
