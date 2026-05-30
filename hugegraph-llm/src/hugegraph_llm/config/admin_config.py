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


class AdminConfig(BaseConfig):
    """Admin settings"""

    _config_section: ClassVar[str] = "admin"

    _flat_to_nested_mapping: ClassVar[dict] = {
        "enable_login": "login.enable",
        "user_token": "login.user_token",
        "admin_token": "login.admin_token",
    }

    enable_login: Optional[str] = "False"
    user_token: Optional[str] = "4321"
    admin_token: Optional[str] = "xxxx"
    config_reload_interval: int = 5
