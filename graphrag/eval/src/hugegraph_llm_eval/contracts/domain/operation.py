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

"""Named-port references."""

import re

from pydantic import field_validator

from hugegraph_llm_eval.contracts.base import StrictModel

_PORT_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


class PortName(StrictModel):
    value: str

    @field_validator("value")
    @classmethod
    def _validate_port(cls, value: str) -> str:
        if not _PORT_RE.fullmatch(value):
            msg = "port name must be lower_snake_case"
            raise ValueError(msg)
        return value

    def __str__(self) -> str:
        return self.value
