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

import unittest

from hugegraph_ml.examples.agnn_example import agnn_example
from hugegraph_ml.examples.appnp_example import appnp_example
from hugegraph_ml.examples.arma_example import arma_example
from hugegraph_ml.examples.bgnn_example import bgnn_example
from hugegraph_ml.examples.bgrl_example import bgrl_example
from hugegraph_ml.examples.cluster_gcn_example import cluster_gcn_example
from hugegraph_ml.examples.correct_and_smooth_example import cs_example
from hugegraph_ml.examples.dagnn_example import dagnn_example
from hugegraph_ml.examples.deepergcn_example import deepergcn_example
from hugegraph_ml.examples.dgi_example import dgi_example
from hugegraph_ml.examples.diffpool_example import diffpool_example
from hugegraph_ml.examples.gin_example import gin_example
from hugegraph_ml.examples.grace_example import grace_example
from hugegraph_ml.examples.grand_example import grand_example
from hugegraph_ml.examples.jknet_example import jknet_example
from hugegraph_ml.examples.pgnn_example import pgnn_example
from hugegraph_ml.examples.seal_example import seal_example


class TestHugegraph2DGL(unittest.TestCase):
    def setUp(self):
        self.test_n_epochs = 3

    def test_dgi_example(self):
        try:
            dgi_example(n_epochs_embed=self.test_n_epochs, n_epochs_clf=self.test_n_epochs)
        except ValueError:
            self.fail("model dgi example failed")

    def test_grace_example(self):
        try:
            grace_example(n_epochs_embed=self.test_n_epochs, n_epochs_clf=self.test_n_epochs)
        except ValueError:
            self.fail("model grace example failed")

    def test_grand_example(self):
        try:
            grand_example(n_epochs=self.test_n_epochs)
        except ValueError:
            self.fail("model grand example failed")

    def test_jknet_example(self):
        try:
            jknet_example(n_epochs=self.test_n_epochs)
        except ValueError:
            self.fail("model jknet example failed")

    def test_diffpool_example(self):
        try:
            diffpool_example(n_epochs=self.test_n_epochs)
        except ValueError:
            self.fail("model diffpool example failed")

    def test_gin_example(self):
        try:
            gin_example(n_epochs=self.test_n_epochs)
        except ValueError:
            self.fail("model gin example failed")

    def test_agnn_example(self):
        try:
            agnn_example(n_epochs=self.test_n_epochs)
        except ValueError:
            self.fail("model agnn example failed")

    def test_appnp_example(self):
        try:
            appnp_example(n_epochs=self.test_n_epochs)
        except ValueError:
            self.fail("model appnp example failed")

    def test_arma_example(self):
        try:
            arma_example(n_epochs=self.test_n_epochs)
        except ValueError:
            self.fail("model arma example failed")

    def test_bgnn_example(self):
        try:
            bgnn_example()
        except ValueError:
            self.fail("model bgnn example failed")

    def test_bgrl_example(self):
        try:
            bgrl_example(n_epochs_embed=self.test_n_epochs, n_epochs_clf=self.test_n_epochs)
        except ValueError:
            self.fail("model bgrl example failed")

    def test_cluster_gcn_example(self):
        try:
            cluster_gcn_example(n_epochs=self.test_n_epochs)
        except ValueError:
            self.fail("model cluster-gcn example failed")

    def test_correct_and_smooth_example(self):
        try:
            cs_example(n_epochs=self.test_n_epochs)
        except ValueError:
            self.fail("model correct and smooth example failed")

    def test_dagnn_example(self):
        try:
            dagnn_example(n_epochs=self.test_n_epochs)
        except ValueError:
            self.fail("model dagnn example failed")

    def test_deepergcn_example(self):
        try:
            deepergcn_example(n_epochs=self.test_n_epochs)
        except ValueError:
            self.fail("model deepergcn example failed")

    def test_pgnn_example(self):
        try:
            pgnn_example(n_epochs=self.test_n_epochs)
        except ValueError:
            self.fail("model p-gnn example failed")

    def test_seal_example(self):
        try:
            seal_example(n_epochs=self.test_n_epochs)
        except ValueError:
            self.fail("model seal example failed")
