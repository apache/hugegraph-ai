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

"""Document data sources: corpus -> schema-constrained extraction -> review.

The plane is optional at runtime: without a registered extractor capability
``ServiceContext.documents`` still exists (the corpus is visible) and ingest
fails with an actionable error. Extraction never writes the ontology directly;
``binder`` turns proposals into typed objects, and the engine commits them
through the same repository/outbox path as every other source.
"""
