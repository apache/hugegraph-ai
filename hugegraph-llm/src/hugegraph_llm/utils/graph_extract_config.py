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
    try:
        workers = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"graph_extract_max_workers must be an integer between 1 and {MAX_GRAPH_EXTRACT_WORKERS}"
        ) from exc

    if workers < 1 or workers > MAX_GRAPH_EXTRACT_WORKERS:
        raise ValueError(f"graph_extract_max_workers must be an integer between 1 and {MAX_GRAPH_EXTRACT_WORKERS}")

    return workers
