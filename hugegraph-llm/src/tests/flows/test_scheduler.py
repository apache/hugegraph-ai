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

"""Regression tests for ``Scheduler.schedule_stream_flow``.

Issue #360: when ``manager.fetch()`` returns ``None`` (no reusable pipeline),
the build/run/stream branch was missing a ``return`` and fell through into the
reuse ``try`` block below, running and streaming the freshly built pipeline a
second time (duplicate LLM calls, doubled streaming output).
"""

import asyncio
from unittest.mock import MagicMock

import pytest

from hugegraph_llm.flows.scheduler import Scheduler

pytestmark = pytest.mark.unit

FLOW_NAME = "test_flow"


class _StreamRecorder:
    """Stand-in for ``flow.post_deal_stream``.

    Records how many times it is invoked and yields a fixed sequence of chunks
    on each invocation, so the test can assert the stream is produced exactly
    once.
    """

    def __init__(self, chunks):
        self._chunks = list(chunks)
        self.call_count = 0

    def __call__(self, _pipeline):
        self.call_count += 1
        return self._aiter()

    async def _aiter(self):
        for chunk in self._chunks:
            yield chunk


def _ok_status():
    status = MagicMock()
    status.isErr.return_value = False
    return status


def _make_scheduler_no_reusable_pipeline():
    """Build a Scheduler whose manager has no cached pipeline to reuse.

    ``Scheduler.__init__`` eagerly constructs every real flow/manager (and
    depends on ``pycgraph``), so the instance is created via ``__new__`` and a
    single mocked pool entry is injected instead.
    """
    manager = MagicMock()
    manager.fetch.return_value = None  # -> take the "build fresh pipeline" path

    pipeline = MagicMock()
    pipeline.init.return_value = _ok_status()
    pipeline.run.return_value = _ok_status()
    # getGParamWithNoEmpty("wkflow_input") must expose a settable `.stream`.
    pipeline.getGParamWithNoEmpty.return_value = MagicMock()

    flow = MagicMock()
    flow.build_flow.return_value = pipeline
    flow.post_deal_stream = _StreamRecorder(["chunk-1", "chunk-2"])

    scheduler = Scheduler.__new__(Scheduler)
    scheduler.pipeline_pool = {FLOW_NAME: {"manager": manager, "flow": flow}}
    scheduler.max_pipeline = 10
    return scheduler, manager, pipeline, flow


def _drain(scheduler, flow_name=FLOW_NAME):
    async def _run():
        return [chunk async for chunk in scheduler.schedule_stream_flow(flow_name)]

    return asyncio.run(_run())


def test_stream_flow_runs_once_when_no_reusable_pipeline():
    """When there is no reusable pipeline, the flow is built, run, and streamed
    exactly once -- it must not fall through into the reuse path (#360)."""
    scheduler, manager, pipeline, flow = _make_scheduler_no_reusable_pipeline()

    results = _drain(scheduler)

    # The stream is emitted exactly once, not duplicated.
    assert results == ["chunk-1", "chunk-2"]

    # Built once, run once, streamed once -- the heart of the regression.
    assert flow.build_flow.call_count == 1
    assert pipeline.init.call_count == 1
    assert pipeline.run.call_count == 1
    assert flow.post_deal_stream.call_count == 1

    # The freshly built pipeline is cached exactly once, and the reuse/release
    # path is never entered (mirrors the early `return res` in `schedule_flow`).
    manager.add.assert_called_once_with(pipeline)
    assert manager.release.call_count == 0
    assert flow.prepare.call_count == 0


def test_stream_flow_rejects_unknown_flow_name():
    scheduler, _manager, _pipeline, _flow = _make_scheduler_no_reusable_pipeline()

    with pytest.raises(ValueError):
        _drain(scheduler, flow_name="does-not-exist")
