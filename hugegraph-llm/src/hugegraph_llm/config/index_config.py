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


class IndexConfig(BaseConfig):
    """LLM settings"""

    section: ClassVar[str] = "index"
    connection_groups: ClassVar[dict[str, tuple[str, ...]]] = {
        'qdrant': ('qdrant_host', 'qdrant_port', 'qdrant_api_key'),
        'milvus': ('milvus_host', 'milvus_port', 'milvus_user', 'milvus_password'),
    }

    qdrant_host: Optional[str] = None
    qdrant_port: int = 6333
    qdrant_api_key: Optional[str] = None

    milvus_host: Optional[str] = None
    milvus_port: int = 19530
    milvus_user: str = ""
    milvus_password: str = ""

    cur_vector_index: str = "Faiss"
