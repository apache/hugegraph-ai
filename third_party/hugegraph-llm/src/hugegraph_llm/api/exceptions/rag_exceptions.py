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

from fastapi import HTTPException

from hugegraph_llm.api.models.rag_response import RAGResponse


class ExternalException(HTTPException):
    def __init__(self):
        super().__init__(status_code=400, detail="Connect failed with error code -1, please check the input.")


class ConnectionFailedException(HTTPException):
    def __init__(self, status_code: int, message: str):
        super().__init__(status_code=status_code, detail=message)


def generate_response(response: RAGResponse) -> dict:
    if response.status_code == -1:
        raise ExternalException()
    if not 200 <= response.status_code < 300:
        raise ConnectionFailedException(response.status_code, response.message)
    return {"message": "Connection successful. Configured finished."}
