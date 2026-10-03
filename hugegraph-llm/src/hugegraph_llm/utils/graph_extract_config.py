# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

MAX_GRAPH_EXTRACT_WORKERS = 8


def validate_graph_extract_max_workers(value) -> int:
    if isinstance(value, bool):
        raise ValueError(f"graph_extract_max_workers must be an integer between 1 and {MAX_GRAPH_EXTRACT_WORKERS}")

    if isinstance(value, int):
        workers = value
    elif isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"graph_extract_max_workers must be an integer between 1 and {MAX_GRAPH_EXTRACT_WORKERS}")
        workers = int(value)
    elif isinstance(value, str):
        stripped_value = value.strip()
        if not stripped_value or not stripped_value.lstrip("+-").isdigit():
            raise ValueError(f"graph_extract_max_workers must be an integer between 1 and {MAX_GRAPH_EXTRACT_WORKERS}")
        workers = int(stripped_value)
    else:
        raise ValueError(f"graph_extract_max_workers must be an integer between 1 and {MAX_GRAPH_EXTRACT_WORKERS}")

    if workers < 1 or workers > MAX_GRAPH_EXTRACT_WORKERS:
        raise ValueError(f"graph_extract_max_workers must be an integer between 1 and {MAX_GRAPH_EXTRACT_WORKERS}")

    return workers
