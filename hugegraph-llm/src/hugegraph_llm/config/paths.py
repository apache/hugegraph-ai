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


"""The writable resource root, independent of the installed Python package."""

import os
import shutil
from pathlib import Path

PACKAGED_RESOURCES = Path(__file__).resolve().parent.parent / "resources"


def resolve_resource_path() -> Path:
    value = os.getenv("HUGEGRAPH_LLM_RESOURCE_PATH")
    if value is None:
        return PACKAGED_RESOURCES
    if not value.strip():
        raise ValueError("HUGEGRAPH_LLM_RESOURCE_PATH must not be empty")
    return Path(value).expanduser()


def ensure_resources() -> str:
    target = resolve_resource_path()
    if target.resolve() != PACKAGED_RESOURCES.resolve():
        # Seed missing bundled examples only. Configuration is loaded/generated
        # separately; existing user resources always win across image upgrades.
        for source in PACKAGED_RESOURCES.rglob("*"):
            relative = source.relative_to(PACKAGED_RESOURCES)
            if not source.is_file() or relative.name in {".env", "config_prompt.yaml"}:
                continue
            destination = target / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                with destination.open("xb") as output, source.open("rb") as input_file:
                    shutil.copyfileobj(input_file, output)
            except FileExistsError:
                pass
    return str(target)
