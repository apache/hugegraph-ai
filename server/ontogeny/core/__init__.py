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
"""ontogeny.core -- DSL: models, loading, validation, linting, expression language."""

from .loader import OntologyPackage, load_package
from .linter import lint  # noqa: F401
from .models import (  # noqa: F401
    ActionResource,
    AnyResource,
    EvalSuiteResource,
    EvolutionPolicyResource,
    FunctionResource,
    LinkTypeResource,
    ObjectTypeResource,
    PolicySetResource,
    ProjectionResource,
    StoreResource,
)
from .types import PropertyType  # noqa: F401
from .validator import ValidationReport, effective_owner, validate

__all__ = [
    "OntologyPackage", "load_package", "validate", "lint", "ValidationReport",
    "effective_owner", "PropertyType",
]
