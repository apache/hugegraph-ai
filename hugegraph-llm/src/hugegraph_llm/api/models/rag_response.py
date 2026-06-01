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

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


class RAGResponse(BaseModel):
    status_code: int = -1
    message: str = ""


class RAGTrace(BaseModel):
    keywords: Optional[List[Any]] = None
    match_vids: Optional[List[Any]] = None
    graph_result_flag: Optional[int] = None
    gremlin: Optional[str] = None
    graph_result: Optional[List[Any]] = None
    vertex_degree_list: Optional[List[Any]] = None


def serialize_rag_trace(data: Dict[str, Any]) -> Dict[str, Any]:
    return RAGTrace(**data).model_dump(exclude_none=True)
