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

# pylint: disable=E1101,E1102,W0223,R1705

"""
 Correct and Smooth (C&S)

References
----------
Paper: https://arxiv.org/abs/2010.13993
Author's code: https://github.com/CUAI/CorrectAndSmooth
DGL code: https://github.com/dmlc/dgl/tree/master/examples/pytorch/correct_and_smooth
"""

import dgl.function as fn
import torch
import torch.nn.functional as F
from torch import nn


class MLPLinear(nn.Module):
    def __init__(self, in_dim, out_dim):
        super().__init__()
        self.linear = nn.Linear(in_dim, out_dim)
        self.reset_parameters()
        self.criterion = nn.CrossEntropyLoss()

    def reset_parameters(self):
        self.linear.reset_parameters()

    def forward(self, graph, x):
        return F.log_softmax(self.linear(x), dim=-1)

    def loss(self, logits, labels):
        return self.criterion(logits, labels)

    def inference(self, graph, feats):
        return self.forward(graph, feats)


class MLP(nn.Module):
    def __init__(self, in_dim, hid_dim, out_dim, num_layers, dropout=0.0):
        super().__init__()
        assert num_layers >= 2

        self.linears = nn.ModuleList()
        self.bns = nn.ModuleList()
        self.linears.append(nn.Linear(in_dim, hid_dim))
        self.bns.append(nn.BatchNorm1d(hid_dim))

        for _ in range(num_layers - 2):
            self.linears.append(nn.Linear(hid_dim, hid_dim))
            self.bns.append(nn.BatchNorm1d(hid_dim))

        self.linears.append(nn.Linear(hid_dim, out_dim))
        self.dropout = dropout
        self.reset_parameters()

        self.criterion = nn.CrossEntropyLoss()

    def reset_parameters(self):
        for layer in self.linears:
            layer.reset_parameters()
        for layer in self.bns:
            layer.reset_parameters()

    def forward(self, graph, x):
        for linear, bn in zip(self.linears[:-1], self.bns, strict=False):
            x = linear(x)
            x = F.relu(x, inplace=True)
            x = bn(x)
            x = F.dropout(x, p=self.dropout, training=self.training)
        x = self.linears[-1](x)
        return F.log_softmax(x, dim=-1)

    def loss(self, logits, labels):
        return self.criterion(logits, labels)

    def inference(self, graph, feats):
        return self.forward(graph, feats)


class LabelPropagation(nn.Module):
    r"""

    Description
    -----------
    .. math::
        \mathbf{Y}^{\prime} = \alpha \cdot \mathbf{D}^{-1/2} \mathbf{A}
        \mathbf{D}^{-1/2} \mathbf{Y} + (1 - \alpha) \mathbf{Y},

    where unlabeled data is inferred by labeled data via propagation.

    Parameters
    ----------
        num_layers: int
            The number of propagations.
        alpha: float
            The :math:`\alpha` coefficient.
        adj: str
            'DAD': D^-0.5 * A * D^-0.5
            'DA': D^-1 * A
            'AD': A * D^-1
    """

    def __init__(self, num_layers, alpha, adj="DAD"):
        super().__init__()

        self.num_layers = num_layers
        self.alpha = alpha
        self.adj = adj

    @torch.no_grad()
    def forward(self, g, labels, mask=None, post_step=lambda y: y.clamp_(0.0, 1.0)):
        with g.local_scope():
            if labels.dtype == torch.long:
                labels = F.one_hot(labels.view(-1)).to(torch.float32)

            y = labels
            if mask is not None:
                y = torch.zeros_like(labels)
                y[mask] = labels[mask]

            last = (1 - self.alpha) * y
            degs = g.in_degrees().float().clamp(min=1)
            norm = torch.pow(degs, -0.5 if self.adj == "DAD" else -1).to(labels.device).unsqueeze(1)

            for _ in range(self.num_layers):
                # Assume the graphs to be undirected
                if self.adj in ["DAD", "AD"]:
                    y = norm * y

                g.ndata["h"] = y
                g.update_all(fn.copy_u("h", "m"), fn.sum("m", "h"))
                y = self.alpha * g.ndata.pop("h")

                if self.adj in ["DAD", "DA"]:
                    y = y * norm

                y = post_step(last + y)

            return y


class CorrectAndSmooth(nn.Module):
    r"""

    Description
    -----------

    Parameters
    ----------
        num_correction_layers: int
            The number of correct propagations.
        correction_alpha: float
            The coefficient of correction.
        correction_adj: str
            'DAD': D^-0.5 * A * D^-0.5
            'DA': D^-1 * A
            'AD': A * D^-1
        num_smoothing_layers: int
            The number of smooth propagations.
        smoothing_alpha: float
            The coefficient of smoothing.
        smoothing_adj: str
            'DAD': D^-0.5 * A * D^-0.5
            'DA': D^-1 * A
            'AD': A * D^-1
        autoscale: bool, optional
            If set to True, will automatically determine the scaling factor :math:`\sigma`. Default is True.
        scale: float, optional
            The scaling factor :math:`\sigma`, in case :obj:`autoscale = False`. Default is 1.
    """

    def __init__(
        self,
        num_correction_layers,
        correction_alpha,
        correction_adj,
        num_smoothing_layers,
        smoothing_alpha,
        smoothing_adj,
        autoscale=True,
        scale=1.0,
    ):
        super().__init__()

        self.autoscale = autoscale
        self.scale = scale

        self.prop1 = LabelPropagation(num_correction_layers, correction_alpha, correction_adj)
        self.prop2 = LabelPropagation(num_smoothing_layers, smoothing_alpha, smoothing_adj)

    def correct(self, g, y_soft, y_true, mask):
        with g.local_scope():
            assert abs(float(y_soft.sum()) / y_soft.size(0) - 1.0) < 1e-2
            numel = int(mask.sum()) if mask.dtype == torch.bool else mask.size(0)
            assert y_true.size(0) == numel

            if y_true.dtype == torch.long:
                y_true = F.one_hot(y_true.view(-1), y_soft.size(-1)).to(y_soft.dtype)

            error = torch.zeros_like(y_soft)
            error[mask] = y_true - y_soft[mask]

            if self.autoscale:
                smoothed_error = self.prop1(g, error, post_step=lambda x: x.clamp_(-1.0, 1.0))
                sigma = error[mask].abs().sum() / numel
                scale = sigma / smoothed_error.abs().sum(dim=1, keepdim=True)
                scale[scale.isinf() | (scale > 1000)] = 1.0

                result = y_soft + scale * smoothed_error
                result[result.isnan()] = y_soft[result.isnan()]
                return result
            else:

                def fix_input(x):
                    x[mask] = error[mask]
                    return x

                smoothed_error = self.prop1(g, error, post_step=fix_input)

                result = y_soft + self.scale * smoothed_error
                result[result.isnan()] = y_soft[result.isnan()]
                return result

    def smooth(self, g, y_soft, y_true, mask):
        with g.local_scope():
            numel = int(mask.sum()) if mask.dtype == torch.bool else mask.size(0)
            assert y_true.size(0) == numel

            if y_true.dtype == torch.long:
                y_true = F.one_hot(y_true.view(-1), y_soft.size(-1)).to(y_soft.dtype)

            y_soft[mask] = y_true
            return self.prop2(g, y_soft)
