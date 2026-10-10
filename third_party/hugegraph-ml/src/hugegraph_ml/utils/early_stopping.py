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


import copy
from typing import Literal


class EarlyStopping:
    """
    Early stopping utility to stop the training process if validation loss or accuracy doesn't
    improve after a given patience. Also saves the best model observed during training.

    Parameters
    ----------
    patience : int
        How long to wait after last time the monitored quantity improved.
        Default: float('inf')
    min_delta : float
        Minimum change in the monitored quantity to qualify as an improvement.
        Default is 0.0.
    monitor : str
        The metric to monitor for early stopping. Can be 'loss' or 'accuracy'.
        Default is 'loss'.
    """

    def __init__(
        self, patience: int = float("inf"), min_delta: float = 0.0, monitor: Literal["loss", "accuracy"] = "loss"
    ):
        self.patience = patience
        self.min_delta = min_delta
        self.counter = 0
        self.best_value = None
        self.early_stop = False
        self.best_model = None
        self.monitor = monitor

        # Check if monitor is set correctly
        if self.monitor not in ["loss", "accuracy"]:
            raise ValueError("monitor should be either 'loss' or 'accuracy'")

    def __call__(self, current_value, model):
        """
        Call this method at the end of each epoch to check if early stopping is triggered.

        Parameters
        ----------
        current_value : float
            The current monitored value (loss or accuracy).
        model : torch.nn.Module
            The current model being trained. The best model will be saved.
        """
        if self.best_value is None:
            self.best_value = current_value
            self.save_best_model(model)
        elif self._is_improvement(current_value):
            self.best_value = current_value
            self.save_best_model(model)
            self.counter = 0  # Reset the patience counter if there's an improvement
        else:
            self.counter += 1
            if self.counter >= self.patience:
                self.early_stop = True

    def _is_improvement(self, current_value):
        is_improved = False
        if self.monitor == "loss":
            # For loss, improvement is when the current value is smaller
            is_improved = current_value < self.best_value - self.min_delta
        elif self.monitor == "accuracy":
            # For accuracy, improvement is when the current value is larger
            is_improved = current_value > self.best_value + self.min_delta
        return is_improved

    def save_best_model(self, model):
        self.best_model = copy.deepcopy(model.state_dict())

    def load_best_model(self, model):
        model.load_state_dict(self.best_model)
