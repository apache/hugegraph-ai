# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Runtime control-plane errors."""


class ExtractionRuntimeError(Exception):
    """Base error for the experimental runtime."""


class RuntimeInvariantError(ExtractionRuntimeError):
    """Raised when runtime-owned state violates an invariant."""


class InvalidGraphError(ExtractionRuntimeError, ValueError):
    """Raised before a non-canonical graph can become authoritative."""


class StaleGraphError(ExtractionRuntimeError):
    """Raised when a repair does not target the current graph digest."""


class BudgetExhaustedError(ExtractionRuntimeError):
    """Raised when a deterministic business budget cannot be consumed."""


class RepairStageError(ExtractionRuntimeError):
    """Raised when a repair candidate cannot be produced or promoted."""


class ArtifactConstructionError(ExtractionRuntimeError):
    """Raised when a semantic terminal cannot be sealed into a data body."""
