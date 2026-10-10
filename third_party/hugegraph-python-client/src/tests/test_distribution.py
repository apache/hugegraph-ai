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

from importlib.metadata import distribution

import pytest
from pyhugegraph.client import PyHugeClient

pytestmark = pytest.mark.contract


def test_distribution_preserves_import_contract():
    installed = distribution("hugegraph-python")
    assert installed.metadata["Name"] == "hugegraph-python"
    assert installed.metadata["Requires-Python"] == ">=3.10"
    assert PyHugeClient.__module__ == "pyhugegraph.client"
