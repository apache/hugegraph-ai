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

"""The pinned server contract, shared by resources, checks and documentation."""

import json
from importlib.resources import files

CONTRACT = json.loads(files(__package__).joinpath("server_contract.json").read_text(encoding="utf-8"))
SERVER_REF: str = CONTRACT["server_ref"]
ENDPOINTS: dict[str, dict] = CONTRACT["operations"]
ALGORITHMS: dict[str, dict] = CONTRACT["algorithms"]
