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

"""Minimal stand-in for ``codex app-server``; the prompt's [scenario:NAME] picks the behaviour."""

import json
import os
import re
import sys
from pathlib import Path

LOG = Path(os.environ["FAKE_CODEX_LOG"])
CRASH_FLAG = LOG.with_suffix(".crashed")
USAGE = {"inputTokens": 100, "cachedInputTokens": 40, "outputTokens": 7, "reasoningOutputTokens": 3, "totalTokens": 107}
counts: dict[str, int] = {}
turns = 0


def send(message: dict) -> None:
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def notify(method: str, **params: object) -> None:
    send({"method": method, "params": params})


def finish(thread_id: str, turn_id: str, status: str, error: dict | None = None) -> None:
    turn = {"id": turn_id, "status": status, "items": []}
    if error is not None:
        turn["error"] = error
    notify("turn/completed", threadId=thread_id, turn=turn)


def run_turn(thread_id: str, turn_id: str, scenario: str) -> None:
    counts[scenario] = counts.get(scenario, 0) + 1
    answer = '{"verdict":"yes","note":null}'
    if scenario == "bad-json":
        answer = "not json"
    failures = {
        "usage-limit": {"message": "limit", "codexErrorInfo": "usageLimitExceeded"},
        "unauthorized": {"message": "401", "codexErrorInfo": {"httpConnectionFailed": {"httpStatusCode": 401}}},
        "overloaded-once": {"message": "busy", "codexErrorInfo": "serverOverloaded"},
    }
    if scenario == "crash-once" and not CRASH_FLAG.exists():
        CRASH_FLAG.touch()
        os._exit(1)
    if scenario == "hang":
        return
    if scenario in failures and not (scenario == "overloaded-once" and counts[scenario] > 1):
        notify("error", threadId=thread_id, turnId=turn_id, willRetry=False, error=failures[scenario])
        notify("thread/tokenUsage/updated", threadId=thread_id, turnId=turn_id, tokenUsage={"total": USAGE})
        finish(thread_id, turn_id, "failed", failures[scenario])
        return
    item = {"type": "agentMessage", "id": "item-1", "text": answer}
    notify("item/completed", threadId=thread_id, turnId=turn_id, completedAtMs=0, item=item)
    notify("thread/tokenUsage/updated", threadId=thread_id, turnId=turn_id, tokenUsage={"total": USAGE, "last": USAGE})
    finish(thread_id, turn_id, "completed")


for line in sys.stdin:
    message = json.loads(line)
    method, request_id, params = message.get("method"), message.get("id"), message.get("params") or {}
    with LOG.open("a") as log:
        log.write(json.dumps({"pid": os.getpid(), "method": method, "params": params}) + "\n")
    if method == "initialize":
        send({"id": request_id, "result": {"userAgent": "fake-codex"}})
    elif method == "config/read":
        send({"id": request_id, "result": {"config": {"mcp_servers": {"user_mcp": {}}}, "origins": {}}})
    elif method == "account/read":
        kind = os.environ.get("FAKE_CODEX_ACCOUNT", "chatgpt")
        account = None if kind == "none" else {"type": kind}
        send({"id": request_id, "result": {"account": account, "requiresOpenaiAuth": True}})
    elif method == "thread/start":
        turns += 1
        send({"id": request_id, "result": {"model": "fake-model-resolved", "thread": {"id": f"thread-{turns}"}}})
    elif method == "turn/start":
        thread_id = params["threadId"]
        send({"id": request_id, "result": {"turn": {"id": f"turn-{thread_id}", "status": "inProgress", "items": []}}})
        marker = re.search(r"\[scenario:([a-z-]+)\]", params["input"][0]["text"])
        run_turn(thread_id, f"turn-{thread_id}", marker.group(1) if marker else "ok")
    elif method == "turn/interrupt":
        send({"id": request_id, "result": {}})
        finish(params["threadId"], params["turnId"], "interrupted")
    elif request_id is not None:
        send({"id": request_id, "result": {}})
