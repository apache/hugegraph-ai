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
# specific language governing permissions and
# limitations under the License.

"""ontogeny.core -- DSL: models, loading, validation, linting, expression language."""

from .loader import OntologyPackage, load_package
from .models import (
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
from .types import PropertyType
from .validator import ValidationReport, effective_owner, validate

__all__ = [
    "ActionResource",
    "AnyResource",
    "EvalSuiteResource",
    "EvolutionPolicyResource",
    "FunctionResource",
    "LinkTypeResource",
    "ObjectTypeResource",
    "OntologyPackage",
    "PolicySetResource",
    "ProjectionResource",
    "PropertyType",
    "StoreResource",
    "ValidationReport",
    "effective_owner",
    "lint",
    "load_package",
    "validate",
]
