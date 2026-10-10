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
from hugegraph_ml.models.grace import GRACE
from hugegraph_ml.models.mlp import MLPClassifier
from hugegraph_ml.tasks.node_classify import NodeClassify
from hugegraph_ml.tasks.node_embed import NodeEmbed


def grace_example(n_epochs_embed=300, n_epochs_clf=400):
    hg2d = HugeGraph2DGL()
    graph = hg2d.convert_graph(vertex_label="CORA_vertex", edge_label="CORA_edge")
    model = GRACE(n_in_feats=graph.ndata["feat"].shape[1])
    node_embed_task = NodeEmbed(graph=graph, model=model)
    embedded_graph = node_embed_task.train_and_embed(
        add_self_loop=True, lr=0.001, weight_decay=1e-5, n_epochs=n_epochs_embed, patience=40
    )
    model = MLPClassifier(
        n_in_feat=embedded_graph.ndata["feat"].shape[1],
        n_out_feat=embedded_graph.ndata["label"].unique().shape[0],
        n_hidden=128,
    )
    node_clf_task = NodeClassify(graph=embedded_graph, model=model)
    node_clf_task.train(lr=1e-3, n_epochs=n_epochs_clf, patience=30)
    print(node_clf_task.evaluate())


if __name__ == "__main__":
    grace_example()
