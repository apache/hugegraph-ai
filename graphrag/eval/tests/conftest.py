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

"""Make the ``src`` layout importable without installing the package."""

import os
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if not os.environ.get("HUGEGRAPH_LLM_EVAL_TEST_INSTALLED") and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
