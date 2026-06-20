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
from numbers import Integral
from urllib.parse import quote
from uuid import UUID

JAVA_LONG_MIN = -(2**63)
JAVA_LONG_MAX = 2**63 - 1


def format_vertex_id(vertex_id, allow_none: bool = False) -> str | None:
    if vertex_id is None:
        if allow_none:
            return None
        raise ValueError("The vertex id can't be None")

    if isinstance(vertex_id, bool):
        raise TypeError("The vertex id must be either str or integer")

    uuid_prefix = ""
    if isinstance(vertex_id, UUID):
        uuid_prefix = "U"
        vertex_id = str(vertex_id)

    if isinstance(vertex_id, Integral):
        if vertex_id < JAVA_LONG_MIN or vertex_id > JAVA_LONG_MAX:
            raise ValueError("The vertex id integer must fit in Java signed long range")
    elif not isinstance(vertex_id, str):
        raise TypeError("The vertex id must be either str or integer")

    return uuid_prefix + json.dumps(vertex_id, allow_nan=False)


def format_vertex_id_path(vertex_id, allow_none: bool = False) -> str | None:
    formatted_id = format_vertex_id(vertex_id, allow_none=allow_none)
    if formatted_id is None:
        return None
    return quote(formatted_id, safe="")
