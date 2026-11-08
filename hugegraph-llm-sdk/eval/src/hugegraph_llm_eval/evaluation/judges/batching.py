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

"""Bound judge payloads while preserving caller-provided global item indices."""

from collections.abc import Callable, Iterator, Sequence

from pydantic import Field, JsonValue

from hugegraph_llm_eval.contracts.base import StrictModel
from hugegraph_llm_eval.contracts.digests import canonical_json_bytes


class BatchingOptions(StrictModel):
    max_items: int = Field(default=256, ge=1, le=4_096, strict=True)
    max_payload_bytes: int = Field(default=512_000, ge=1, le=1_000_000, strict=True)


class BatchInputError(ValueError):
    pass


class BatchOutputError(ValueError):
    pass


def payload_batches[T](
    values: Sequence[T],
    payload_for: Callable[[tuple[T, ...]], JsonValue],
    options: BatchingOptions,
) -> Iterator[tuple[tuple[T, ...], JsonValue]]:
    for offset in range(0, len(values), options.max_items):
        yield from _fit_batch(tuple(values[offset : offset + options.max_items]), payload_for, options)


def _fit_batch[T](
    values: tuple[T, ...],
    payload_for: Callable[[tuple[T, ...]], JsonValue],
    options: BatchingOptions,
) -> Iterator[tuple[tuple[T, ...], JsonValue]]:
    payload = payload_for(values)
    size = len(canonical_json_bytes(payload))
    if size <= options.max_payload_bytes:
        yield values, payload
    elif len(values) > 1:
        middle = len(values) // 2
        yield from _fit_batch(values[:middle], payload_for, options)
        yield from _fit_batch(values[middle:], payload_for, options)
    else:
        raise BatchInputError(
            f"One item plus shared evidence needs {size} payload bytes; "
            f"the configured limit is {options.max_payload_bytes}. "
            "Reduce the input or explicitly raise BatchingOptions.max_payload_bytes; evidence is never truncated."
        )


def paired_payload_batches[L, R](
    left: Sequence[L],
    right: Sequence[R],
    payload_for: Callable[[tuple[L, ...], tuple[R, ...]], JsonValue],
    options: BatchingOptions,
) -> Iterator[tuple[tuple[L, ...], tuple[R, ...], JsonValue]]:
    for left_offset in range(0, len(left), options.max_items):
        for right_offset in range(0, len(right), options.max_items):
            yield from _fit_pair(
                tuple(left[left_offset : left_offset + options.max_items]),
                tuple(right[right_offset : right_offset + options.max_items]),
                payload_for,
                options,
            )


def _fit_pair[L, R](
    left: tuple[L, ...],
    right: tuple[R, ...],
    payload_for: Callable[[tuple[L, ...], tuple[R, ...]], JsonValue],
    options: BatchingOptions,
) -> Iterator[tuple[tuple[L, ...], tuple[R, ...], JsonValue]]:
    payload = payload_for(left, right)
    size = len(canonical_json_bytes(payload))
    if size <= options.max_payload_bytes:
        yield left, right, payload
    elif len(left) > 1 and len(left) >= len(right):
        middle = len(left) // 2
        yield from _fit_pair(left[:middle], right, payload_for, options)
        yield from _fit_pair(left[middle:], right, payload_for, options)
    elif len(right) > 1:
        middle = len(right) // 2
        yield from _fit_pair(left, right[:middle], payload_for, options)
        yield from _fit_pair(left, right[middle:], payload_for, options)
    else:
        raise BatchInputError(
            f"One candidate/reference pair needs {size} payload bytes; "
            f"the configured limit is {options.max_payload_bytes}. Reduce the input or raise the explicit limit."
        )
