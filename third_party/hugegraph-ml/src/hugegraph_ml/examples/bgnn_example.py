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

# pylint: disable=C0103

from hugegraph_ml.data.hugegraph2dgl import HugeGraph2DGL
from hugegraph_ml.models.bgnn import (
    BGNNPredictor,
    GNNModelDGL,
    convert_data,
    encode_cat_features,
    replace_na,
)


def bgnn_example():
    hg2d = HugeGraph2DGL()
    g = hg2d.convert_hetero_graph_bgnn(vertex_labels=["AVAZU__N_v"], edge_labels=["AVAZU__E_e"])
    X, y, cat_features, train_mask, val_mask, test_mask = convert_data(g)
    encoded_X = X.copy()
    encoded_X = encode_cat_features(encoded_X, y, cat_features, train_mask, val_mask, test_mask)
    encoded_X = replace_na(encoded_X, train_mask)
    gnn_model = GNNModelDGL(in_dim=y.shape[1], hidden_dim=128, out_dim=y.shape[1])
    bgnn = BGNNPredictor(
        gnn_model,
        task="regression",
        loss_fn=None,
        trees_per_epoch=5,
        backprop_per_epoch=5,
        lr=0.1,
        append_gbdt_pred=False,
        gbdt_depth=6,
        gbdt_lr=0.1,
    )
    metrics = bgnn.fit(
        g,
        encoded_X,
        y,
        train_mask,
        val_mask,
        test_mask,
        original_X=X,
        cat_features=cat_features,
        num_epochs=100,
        patience=10,
        metric_name="loss",
    )
    print(metrics)


if __name__ == "__main__":
    bgnn_example()
