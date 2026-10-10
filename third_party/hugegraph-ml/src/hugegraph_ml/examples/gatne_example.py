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


from hugegraph_ml.data.hugegraph2dgl import HugeGraph2DGL
from hugegraph_ml.models.gatne import DGLGATNE
from hugegraph_ml.tasks.hetero_sample_embed_gatne import HeteroSampleEmbedGATNE


def gatne_example(n_epochs=200):
    hg2d = HugeGraph2DGL()
    graph = hg2d.convert_hetero_graph(
        vertex_labels=["AMAZONGATNE__N_v"],
        edge_labels=[
            "AMAZONGATNE_1_e",
            "AMAZONGATNE_2_e",
        ],
    )
    model = DGLGATNE(
        graph.number_of_nodes(),
        200,
        10,
        graph.etypes,
        len(graph.etypes),
        20,
    )
    gatne_task = HeteroSampleEmbedGATNE(graph, model)
    gatne_task.train_and_embed(lr=0.005, n_epochs=n_epochs)


if __name__ == "__main__":
    gatne_example()
