# Copyright 2026 Apache HugeGraph Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Accounts, sessions, and role/permission administration.

The platform's authorization is Cedar, evaluated by the engine on every request.
This package adds *identity* (who is calling) and an *administrative surface*
over the same policy plane (which role may do what) — it deliberately adds no
second authorization system: see ``roles.py``.
"""
from .models import SessionRow, UserRow
from .passwords import hash_password, verify_password
from .roles import (
    Grant, compile_role_policy, effective_matrix, managed_policy_name,
    parse_grants, role_catalogue, slug_conflicts,
)
from .service import SESSION_TTL, AuthService

__all__ = [
    "AuthService", "SESSION_TTL",
    "UserRow", "SessionRow", "hash_password", "verify_password",
    "Grant", "parse_grants", "compile_role_policy", "effective_matrix",
    "role_catalogue", "managed_policy_name", "slug_conflicts",
]
