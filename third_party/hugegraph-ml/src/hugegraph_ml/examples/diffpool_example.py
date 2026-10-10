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
from hugegraph_ml.models.diffpool import DiffPool
from hugegraph_ml.tasks.graph_classify import GraphClassify


def diffpool_example(n_epochs=1000):
    hg2d = HugeGraph2DGL()
    dataset = hg2d.convert_graph_dataset(
        graph_vertex_label="MUTAG_graph_vertex", vertex_label="MUTAG_vertex", edge_label="MUTAG_edge"
    )
    model = DiffPool(
        n_in_feats=dataset.info["n_feat_dim"],
        n_out_feats=dataset.info["n_classes"],
        max_n_nodes=dataset.info["max_n_nodes"],
        pool_ratio=0.2,
    )
    graph_clf_task = GraphClassify(dataset, model)
    graph_clf_task.train(lr=1e-3, n_epochs=n_epochs, patience=300, early_stopping_monitor="accuracy")
    print(graph_clf_task.evaluate())


if __name__ == "__main__":
    diffpool_example()
