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
from typing import Optional

from .models import BaseConfig


class IndexConfig(BaseConfig):
    """LLM settings"""

    qdrant_host: Optional[str] = os.environ.get("QDRANT_HOST", None)
    qdrant_port: int = int(os.environ.get("QDRANT_PORT", "6333"))
    qdrant_api_key: Optional[str] = os.environ.get("QDRANT_API_KEY") if os.environ.get("QDRANT_API_KEY") else None

    milvus_host: Optional[str] = os.environ.get("MILVUS_HOST", None)
    milvus_port: int = int(os.environ.get("MILVUS_PORT", "19530"))
    milvus_user: str = os.environ.get("MILVUS_USER", "")
    milvus_password: str = os.environ.get("MILVUS_PASSWORD", "")

    cur_vector_index: str = os.environ.get("CUR_VECTOR_INDEX", "Faiss")
