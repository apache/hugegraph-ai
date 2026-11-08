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

"""Run-scoped limits: one provider cap and one cost budget per call graph."""

import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from hugegraph_llm_eval.contracts.domain.evaluation import ConcurrencyLimiter
from hugegraph_llm_eval.contracts.domain.judge import JudgeCallRecord, judge_call_cost_is_unknown
from hugegraph_llm_eval.contracts.errors import FailureDetail
from hugegraph_llm_eval.evaluation.options import EvaluationOptions

_POLL_SECONDS = 0.05


class SemaphoreLimiter:
    """Cap in-flight provider calls for one run, including nested evaluator batches."""

    def __init__(self, capacity: int) -> None:
        if capacity < 1:
            msg = "limiter capacity must be positive"
            raise ValueError(msg)
        self.capacity = capacity
        self._semaphore = threading.BoundedSemaphore(capacity)

    def acquire(self, should_abort: Callable[[], FailureDetail | None]) -> FailureDetail | None:
        """Wait for a slot and give up as soon as the run is cancelled or out of time."""
        while not self._semaphore.acquire(timeout=_POLL_SECONDS):
            failure = should_abort()
            if failure is not None:
                return failure
        return None

    def release(self) -> None:
        self._semaphore.release()


class CostBudget:
    """Thread-safe spend accumulator so a batch cannot reset its own budget."""

    def __init__(self, limit_usd: float | None) -> None:
        self._limit = limit_usd
        self._lock = threading.Lock()
        self._spent = 0.0
        self._unknown = False

    @property
    def limit_usd(self) -> float | None:
        return self._limit

    @property
    def spent(self) -> float:
        with self._lock:
            return self._spent

    def charge(self, calls: Sequence[JudgeCallRecord]) -> None:
        """Accumulate reported attempt costs, including billed output failures."""
        known = sum(
            attempt.usage.cost_usd or 0
            for call in calls
            for attempt in call.provenance.attempts
            if attempt.usage is not None
        )
        unknown = any(judge_call_cost_is_unknown(call) for call in calls)
        with self._lock:
            self._spent += known
            self._unknown = self._unknown or unknown

    def exhausted(self) -> bool:
        """Report whether the budget cannot fund another call."""
        with self._lock:
            return self._limit is not None and self._spent >= self._limit

    def exceeded(self) -> bool:
        """Report whether the run has already spent past its budget."""
        with self._lock:
            return self._limit is not None and self._spent > self._limit

    def unverifiable(self) -> bool:
        """Report whether a budgeted run spent calls the provider could not price."""
        with self._lock:
            return self._limit is not None and self._unknown


@dataclass(frozen=True, slots=True)
class RunLimits:
    """Limits shared by every sample and evaluator of one evaluation call."""

    limiter: ConcurrencyLimiter
    budget: CostBudget

    @classmethod
    def for_options(cls, options: EvaluationOptions, *, samples: int = 1) -> "RunLimits":
        capacity = options.max_concurrency * max(1, min(samples, options.max_samples))
        return cls(limiter=SemaphoreLimiter(capacity), budget=CostBudget(options.budget_usd))
