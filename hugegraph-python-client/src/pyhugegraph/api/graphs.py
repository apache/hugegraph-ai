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

"""Graph administration; legacy get_* helpers retain their text responses."""

from pyhugegraph.api.rest import GraphsAPI
from pyhugegraph.utils.util import ResponseValidation


class GraphsManager(GraphsAPI):
    def get_all_graphs(self) -> str:
        return self.request("graphs.list", validator=ResponseValidation(content_type="text"))

    def get_version(self) -> str:
        return self.request("version.list", validator=ResponseValidation(content_type="text"))

    def get_graph_info(self) -> str:
        return self.request(
            "graphs.get",
            path_params={"name": self.session.cfg.graph_name},
            validator=ResponseValidation(content_type="text"),
        )

    def clear_graph_all_data(self):
        return self.clear(self.session.cfg.graph_name, confirm_message="I'm sure to delete all data")

    def get_graph_config(self) -> str:
        return self.request(
            "graphs.get_conf",
            path_params={"name": self.session.cfg.graph_name},
            validator=ResponseValidation(content_type="text"),
        )
