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

"""Respect explicit Authorization headers while retaining Requests proxy handling."""

from collections.abc import Mapping

from requests import PreparedRequest
from requests.auth import AuthBase


class _ExplicitAuthorization(AuthBase):
    def __call__(self, r: PreparedRequest) -> PreparedRequest:
        return r


def request_auth(headers: Mapping[str, str], basic_auth: tuple[str, str]) -> AuthBase | tuple[str, str]:
    # auth=None lets Requests apply .netrc credentials over an explicit header.
    if any(key.lower() == "authorization" for key in headers):
        return _ExplicitAuthorization()
    return basic_auth
