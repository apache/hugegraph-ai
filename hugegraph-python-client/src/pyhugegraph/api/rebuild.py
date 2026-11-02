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


from pyhugegraph.api.common import HugeParamsBase


class RebuildManager(HugeParamsBase):
    """
    Manages the rebuilding of index, vertex, and edge labels via HTTP endpoints.

    Methods:
        rebuild_indexlabels(indexlabel: str):
            Rebuilds the specified IndexLabel. Returns a dictionary with the task ID.

        rebuild_vertexlabels(vertexlabel: str):
            Rebuilds the specified VertexLabel. Returns a dictionary with the task ID.

        rebuild_edgelabels(edgelabel: str):
            Rebuilds the specified EdgeLabel. Returns a dictionary with the task ID.
    """

    def rebuild_indexlabels(self, indexlabel: str):
        """
        Rebuild IndexLabel.

        Args:
            indexlabel (str): Name of the indexlabel.

        Returns:
            dict: A dictionary containing the response from the HTTP request.
                  The structure of the response is as follows:
                  response = {
                      "task_id": 1 # Unique identifier for the task.
                  }
        """
        return self.request("rebuild.index_label_rebuild", path_params={"name": indexlabel})

    def rebuild_vertexlabels(self, vertexlabel: str):
        """
        Rebuild VertexLabel.

        Args:
            vertexlabel (str): Name of the vertexlabel.

        Returns:
            dict: A dictionary containing the response from the HTTP request.
                  The structure of the response is as follows:
                  response = {
                      "task_id": 1 # Unique identifier for the task.
                  }
        """
        return self.request("rebuild.vertex_label_rebuild", path_params={"name": vertexlabel})

    def rebuild_edgelabels(self, edgelabel: str):
        """
        Rebuild EdgeLabel.

        Args:
            edgelabel (str): Name of the edgelabel.

        Returns:
            dict: A dictionary containing the response from the HTTP request.
                  The structure of the response is as follows:
                  response = {
                      "task_id": 1 # Unique identifier for the task.
                  }
        """
        return self.request("rebuild.edge_label_rebuild", path_params={"name": edgelabel})
