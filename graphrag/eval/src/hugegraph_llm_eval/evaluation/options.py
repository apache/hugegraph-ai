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

"""Call-scoped Evaluation execution controls."""

import math
import threading
from dataclasses import dataclass, field
from datetime import datetime

from hugegraph_llm_eval.contracts.domain.evaluation import (
    MAX_CONCURRENCY,
    MAX_SAMPLES,
)

MAX_ATTEMPTS = 20


def _validate_request_key(value: str) -> None:
    if not value.strip() or len(value) > 255:
        msg = "request_key must contain 1 to 255 non-whitespace characters"
        raise ValueError(msg)


def _validate_positive_counts(*values: int) -> None:
    if any(value < 1 for value in values):
        msg = "max_attempts, max_samples and max_concurrency must be positive"
        raise ValueError(msg)


def _validate_bounded(name: str, value: int, upper: int) -> None:
    if value < 1 or value > upper:
        msg = f"{name} must be between 1 and {upper}"
        raise ValueError(msg)


def _validate_attempts(value: int) -> None:
    """Match the judge-level upper bound so a bad option fails at construction."""
    _validate_bounded("max_attempts", value, MAX_ATTEMPTS)


def _validate_deadline(value: datetime | None) -> None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        msg = "deadline must include a timezone"
        raise ValueError(msg)


def _validate_non_negative(name: str, value: float | None) -> None:
    if value is not None and (not math.isfinite(value) or value < 0):
        msg = f"{name} must be finite and non-negative"
        raise ValueError(msg)


class CancellationToken:
    """Thread-safe cooperative cancellation state owned by one call graph."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._reason: str | None = None

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    @property
    def reason(self) -> str | None:
        with self._lock:
            return self._reason

    def cancel(self, reason: str) -> None:
        normalized = reason.strip()
        if not normalized:
            msg = "cancellation reason must not be empty"
            raise ValueError(msg)
        if len(normalized) > 2_000:
            msg = "cancellation reason exceeds 2000 characters"
            raise ValueError(msg)
        with self._lock:
            if self._reason is None:
                self._reason = normalized
                self._event.set()

    def wait(self, timeout: float) -> bool:
        """Wait up to timeout seconds and report whether cancellation occurred."""

        return self._event.wait(timeout)


@dataclass(frozen=True, slots=True)
class EvaluationOptions:
    request_key: str
    deadline: datetime | None = None
    max_attempts: int = 3
    max_concurrency: int = 1
    max_samples: int = 1
    budget_usd: float | None = None
    retry_backoff_seconds: float = 0
    cancellation: CancellationToken = field(default_factory=CancellationToken)

    def __post_init__(self) -> None:
        _validate_request_key(self.request_key)
        _validate_positive_counts(self.max_attempts, self.max_concurrency, self.max_samples)
        _validate_attempts(self.max_attempts)
        _validate_bounded("max_concurrency", self.max_concurrency, MAX_CONCURRENCY)
        _validate_bounded("max_samples", self.max_samples, MAX_SAMPLES)
        _validate_deadline(self.deadline)
        _validate_non_negative("budget_usd", self.budget_usd)
        _validate_non_negative("retry_backoff_seconds", self.retry_backoff_seconds)
