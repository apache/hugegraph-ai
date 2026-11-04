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

from typing import Optional

from pydantic import field_validator

from .models import BaseConfig


class AdminConfig(BaseConfig):
    """Admin settings"""

    hugegraph_llm_enable_thin_writes: bool = False

    @field_validator("hugegraph_llm_enable_thin_writes", mode="before")
    @classmethod
    def strict_write_opt_in(cls, value):
        """Only an explicit true enables writes; malformed input stays closed."""
        return value.strip().lower() == "true" if isinstance(value, str) else value is True

    enable_login: Optional[str] = "False"
    user_token: Optional[str] = "4321"
    admin_token: Optional[str] = "xxxx"

    def is_login_enabled(self) -> bool:
        """Use the same login flag semantics for routing and write protection."""
        return str(self.enable_login).strip().lower() == "true"
