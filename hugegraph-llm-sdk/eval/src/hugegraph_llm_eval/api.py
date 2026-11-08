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

"""Evaluation entry points for callers that do not need the application runtime."""

import asyncio
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor

from hugegraph_llm_eval.contracts.domain.evaluation import EvaluationInput
from hugegraph_llm_eval.evaluation.engine import EvaluationEngine, EvaluationResult, MetricEvaluator
from hugegraph_llm_eval.evaluation.limits import RunLimits
from hugegraph_llm_eval.evaluation.options import EvaluationOptions


def evaluate(
    evaluators: Sequence[MetricEvaluator],
    evaluation_input: EvaluationInput,
    *,
    options: EvaluationOptions | None = None,
    request_key: str = "evaluation",
) -> EvaluationResult:
    """Evaluate one input with every supplied evaluator.

    Evaluator identity, ordering, concurrency, retry, deadline and cancellation
    follow ``EvaluationOptions``. Record-level failures stay in the result; only
    invalid arguments raise.
    """
    return EvaluationEngine().evaluate(
        evaluators,
        evaluation_input,
        options if options is not None else EvaluationOptions(request_key=request_key),
    )


def evaluate_many(
    evaluators: Sequence[MetricEvaluator],
    inputs: Sequence[EvaluationInput],
    *,
    options: EvaluationOptions | None = None,
    request_key: str = "evaluation",
) -> tuple[EvaluationResult, ...]:
    """Evaluate independent inputs in caller order.

    ``max_samples`` bounds how many inputs run at once and ``max_concurrency``
    bounds the evaluators inside each input; every sample and metric of the batch
    shares one provider limit and one cost budget.
    """
    engine = EvaluationEngine()
    resolved_options = options if options is not None else EvaluationOptions(request_key=request_key)
    limits = RunLimits.for_options(resolved_options, samples=len(inputs))
    if resolved_options.max_samples == 1 or len(inputs) <= 1:
        return tuple(engine.evaluate(evaluators, item, resolved_options, limits=limits) for item in inputs)
    workers = min(resolved_options.max_samples, len(inputs))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="hugegraph-llm-eval-sample") as executor:
        return tuple(
            executor.map(
                lambda item: engine.evaluate(evaluators, item, resolved_options, limits=limits),
                inputs,
            )
        )


async def aevaluate(
    evaluators: Sequence[MetricEvaluator],
    evaluation_input: EvaluationInput,
    *,
    options: EvaluationOptions | None = None,
    request_key: str = "evaluation",
) -> EvaluationResult:
    """Asynchronous wrapper; cancelling the task cancels the underlying run."""
    resolved_options = options if options is not None else EvaluationOptions(request_key=request_key)
    try:
        return await asyncio.to_thread(evaluate, evaluators, evaluation_input, options=resolved_options)
    except asyncio.CancelledError:
        resolved_options.cancellation.cancel("asyncio task cancelled")
        raise


async def aevaluate_many(
    evaluators: Sequence[MetricEvaluator],
    inputs: Sequence[EvaluationInput],
    *,
    options: EvaluationOptions | None = None,
    request_key: str = "evaluation",
) -> tuple[EvaluationResult, ...]:
    """Asynchronous wrapper over ``evaluate_many``."""
    resolved_options = options if options is not None else EvaluationOptions(request_key=request_key)
    try:
        return await asyncio.to_thread(evaluate_many, evaluators, inputs, options=resolved_options)
    except asyncio.CancelledError:
        resolved_options.cancellation.cancel("asyncio task cancelled")
        raise
