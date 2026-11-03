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

import os
from typing import ClassVar, Optional
from urllib.parse import urlsplit

from dotenv import dotenv_values

from .models import BaseConfig, base_config


class HugeGraphConfig(BaseConfig):
    """HugeGraph settings"""

    allow_empty_environment: ClassVar[frozenset[str]] = frozenset({"graph_pwd"})

    @classmethod
    def _clears_file_password(cls):
        source = super().environment_source("graph_url")
        if not source or super().environment_source("graph_pwd"):
            return False
        values = {key.upper(): value for key, value in dotenv_values(base_config.env_path).items()}

        def endpoint(value):
            value = value or ""
            parsed = urlsplit(value if "://" in value else "http://" + value)
            return parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/")

        return endpoint(os.environ[source]) != endpoint(values.get("GRAPH_URL"))

    @classmethod
    def environment_source(cls, field):
        if field == "graph_pwd" and cls._clears_file_password():
            return super().environment_source("graph_url")
        return super().environment_source(field)

    @classmethod
    def settings_customise_sources(cls, *args, **kwargs):
        sources = super().settings_customise_sources(*args, **kwargs)

        def scoped_environment():
            values = sources[1]()
            if cls._clears_file_password():
                values["graph_pwd"] = ""
            return values

        return sources[0], scoped_environment, *sources[2:]

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
