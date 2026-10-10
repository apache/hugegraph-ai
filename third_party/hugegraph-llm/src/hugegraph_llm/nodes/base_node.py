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

import traceback
from typing import Dict, Optional

from pycgraph import CStatus, GNode

from hugegraph_llm.nodes.util import init_context
from hugegraph_llm.state.ai_state import WkFlowInput, WkFlowState
from hugegraph_llm.utils.log import log


def _format_node_err(node, exc: Exception, prefix: str = "Node failed") -> str:
    node_info = f"Node type: {type(node).__name__}, Node object: {node}"
    return f"{prefix}: {exc}\n{node_info}\n{traceback.format_exc()}"


class BaseNode(GNode):
    """
    Base class for workflow nodes, providing context management and operation scheduling.

    All custom nodes should inherit from this class and implement the operator_schedule method.

    Attributes:
        context: Shared workflow state
        wk_input: Workflow input parameters
    """

    context: Optional[WkFlowState] = None
    wk_input: Optional[WkFlowInput] = None

    def init(self):
        return init_context(self)

    def node_init(self):
        """
        Node initialization method, can be overridden by subclasses.
        Returns a CStatus object indicating whether initialization succeeded.
        """
        if self.wk_input is None or self.context is None:
            return CStatus(-1, "wk_input or context not initialized")
        if self.wk_input.data_json is not None:
            self.context.assign_from_json(self.wk_input.data_json)
            self.wk_input.data_json = None
        return CStatus()

    def run(self):
        """
        Main logic for node execution, can be overridden by subclasses.
        Returns a CStatus object indicating whether execution succeeded.
        """
        sts = self.node_init()
        if sts.isErr():
            return sts
        if self.context is None:
            return CStatus(-1, "Context not initialized")
        self.context.lock()
        try:
            data_json = self.context.to_json()
        finally:
            self.context.unlock()

        try:
            res = self.operator_schedule(data_json)
        except (ValueError, TypeError, KeyError, NotImplementedError) as exc:
            err_msg = _format_node_err(self, exc)
            log.error(err_msg)
            return CStatus(-1, err_msg)
        # For unexpected exceptions, re-raise to let them propagate or be caught elsewhere

        self.context.lock()
        try:
            if res is not None and isinstance(res, dict):
                self.context.assign_from_json(res)
            elif res is not None:
                log.warning("operator_schedule returned non-dict type: %s", type(res))
        finally:
            self.context.unlock()
        return CStatus()

    def operator_schedule(self, data_json) -> Optional[Dict]:
        """
        Operation scheduling method that must be implemented by subclasses.

        Args:
            data_json: Context serialized as JSON data

        Returns:
            Dictionary of processing results, or None to indicate no update

        Raises:
            NotImplementedError: If the subclass has not implemented this method
        """
        raise NotImplementedError("Subclasses must implement operator_schedule")
