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

from .models import BaseConfig


class HugeGraphConfig(BaseConfig):
    """HugeGraph settings"""

    _config_section: ClassVar[str] = "hugegraph"

    _flat_to_nested_mapping: ClassVar[dict] = {
        "graph_url": "graph.url",
        "graph_name": "graph.name",
        "graph_user": "graph.user",
        "graph_pwd": "graph.pwd",
        "graph_space": "graph.space",
        "limit_property": "query.limit_property",
        "max_graph_path": "query.max_graph_path",
        "max_graph_items": "query.max_graph_items",
        "edge_limit_pre_label": "query.edge_limit_pre_label",
        "vector_dis_threshold": "vector.dis_threshold",
        "topk_per_keyword": "vector.topk_per_keyword",
        "topk_return_results": "rerank.topk_return_results",
    }

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
