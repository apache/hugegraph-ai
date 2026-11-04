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

from typing import ClassVar, Optional

from pydantic import field_validator

from .models import BaseConfig


class HugeGraphConfig(BaseConfig):
    """HugeGraph settings"""

    allow_empty_environment: ClassVar[frozenset[str]] = frozenset({"graph_pwd"})
    credential_endpoints: ClassVar[dict[str, tuple[str, ...]]] = {"graph_pwd": ("graph_url",)}

    @field_validator("graph_url", mode="before")
    @classmethod
    def normalize_graph_url(cls, value):
        if isinstance(value, str) and value.strip():
            value = value.strip()
            if "://" not in value:
                value = "http://" + value
            scheme, rest = value.split("://", 1)
            return scheme.lower() + "://" + rest
        return value

    # graph server config
    graph_url: str = "127.0.0.1:8080"
    graph_name: str = "hugegraph"
    graph_user: str = "admin"
    graph_pwd: str = "xxx"
    graph_space: Optional[str] = None

    # graph query config
    limit_property: str = "False"
    max_graph_path: int = 10
    max_graph_items: int = 30
    edge_limit_pre_label: int = 8

    # vector config
    vector_dis_threshold: float = 0.9
    topk_per_keyword: int = 1

    # rerank config
    topk_return_results: int = 20
