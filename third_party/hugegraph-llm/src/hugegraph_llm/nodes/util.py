#  Licensed to the Apache Software Foundation (ASF) under one or more
#  contributor license agreements.  See the NOTICE file distributed with
#  this work for additional information regarding copyright ownership.
#  The ASF licenses this file to You under the Apache License, Version 2.0
#  (the "License"); you may not use this file except in compliance with
#  the License.  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

from typing import Any

from pycgraph import CStatus


def init_context(obj: Any) -> CStatus:
    """
    Initialize workflow context for a node.

    Retrieves wkflow_state and wkflow_input from obj's global parameters
    and assigns them to obj.context and obj.wk_input respectively.

    Args:
        obj: Node object with getGParamWithNoEmpty method

    Returns:
        CStatus: Empty status on success, error status with code -1 on failure
    """
    obj.context = obj.getGParamWithNoEmpty("wkflow_state")
    obj.wk_input = obj.getGParamWithNoEmpty("wkflow_input")
    if obj.context is None or obj.wk_input is None:
        return CStatus(-1, "Required workflow parameters not found")
    return CStatus()
