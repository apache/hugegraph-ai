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

"""Schema-aware graph extraction quality layer.

The enhanced extraction strategy compiles the request-provided graph schema into a
runtime constraint index (``GraphSchemaIndex``) and layers a candidate parser,
schema-aware normalizer, document-level assembler, and quality gate on top of the
baseline extraction pipeline. All modules in this package are pure Python and
require no external services; they operate only on data already handed in by
existing baseline nodes (schema, chunks, LLM outputs).
"""

from hugegraph_llm.operators.llm_op.property_graph_extract_enhanced.schema_index import (
    GraphSchemaIndex,
)
from hugegraph_llm.operators.llm_op.property_graph_extract_enhanced.warnings import (
    StructuredWarning,
    WarningCode,
    warning_code_distribution,
)

__all__ = [
    "GraphSchemaIndex",
    "StructuredWarning",
    "WarningCode",
    "warning_code_distribution",
]
