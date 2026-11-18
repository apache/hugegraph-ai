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

"""Line-delimited JSON-RPC connection to one ``codex app-server`` child process."""

import json
import queue
import subprocess
import threading
from collections.abc import Mapping, Sequence
from contextlib import suppress
from typing import IO, Protocol

Message = dict[str, object]


class ConnectionClosedError(RuntimeError):
    """The app-server process exited or its pipes broke."""


class RpcError(RuntimeError):
    """The app-server answered a request with a JSON-RPC error."""


class AppServerProcess(Protocol):
    stdin: IO[str] | None
    stdout: IO[str] | None

    def poll(self) -> int | None: ...

    def wait(self, timeout: float | None = None) -> int: ...

    def kill(self) -> None: ...


def spawn_app_server(argv: Sequence[str], *, cwd: str, env: Mapping[str, str]) -> AppServerProcess:
    return subprocess.Popen(
        list(argv),
        cwd=cwd,
        env=dict(env),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )


class AppServerConnection:
    """Multiplexes requests and per-thread notifications over one stdio pipe pair."""

    def __init__(self, process: AppServerProcess) -> None:
        self._process = process
        self._write_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._next_id = 1
        self._responses: dict[int, queue.Queue[Message | None]] = {}
        self._threads: dict[str, queue.Queue[Message | None]] = {}
        self._alive = True
        self._reader = threading.Thread(target=self._read_loop, name="codex-app-server-reader", daemon=True)
        self._reader.start()

    @property
    def alive(self) -> bool:
        return self._alive and self._process.poll() is None

    def request(self, method: str, params: Mapping[str, object], timeout: float) -> Message:
        box: queue.Queue[Message | None] = queue.Queue()
        with self._state_lock:
            if not self._alive:
                raise ConnectionClosedError(method)
            request_id = self._next_id
            self._next_id += 1
            self._responses[request_id] = box
        try:
            self._send({"id": request_id, "method": method, "params": params})
            message = box.get(timeout=timeout)
        except queue.Empty:
            raise TimeoutError(method) from None
        finally:
            with self._state_lock:
                self._responses.pop(request_id, None)
        if message is None:
            raise ConnectionClosedError(method)
        error = message.get("error")
        if error is not None:
            detail = error.get("message") if isinstance(error, dict) else None
            raise RpcError(str(detail or method))
        result = message.get("result")
        return result if isinstance(result, dict) else {}

    def notify(self, method: str) -> None:
        self._send({"method": method})

    def fire(self, method: str, params: Mapping[str, object]) -> None:
        """Send a request without awaiting its response; a closed connection is ignored."""
        with self._state_lock:
            request_id = self._next_id
            self._next_id += 1
        with suppress(ConnectionClosedError):
            self._send({"id": request_id, "method": method, "params": params})

    def watch(self, thread_id: str) -> "queue.Queue[Message | None]":
        events: queue.Queue[Message | None] = queue.Queue()
        with self._state_lock:
            self._threads[thread_id] = events
            if not self._alive:
                events.put(None)
        return events

    def unwatch(self, thread_id: str) -> None:
        with self._state_lock:
            self._threads.pop(thread_id, None)

    def close(self) -> None:
        try:
            if self._process.stdin is not None:
                self._process.stdin.close()
            self._process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            self._process.kill()
        self._reader.join(timeout=5)

    def _send(self, message: Message) -> None:
        line = json.dumps(message, separators=(",", ":"), ensure_ascii=False) + "\n"
        with self._write_lock:
            try:
                if self._process.stdin is None:
                    raise ConnectionClosedError("stdin closed")
                self._process.stdin.write(line)
                self._process.stdin.flush()
            except (OSError, ValueError) as exc:
                raise ConnectionClosedError(str(exc)) from exc

    def _read_loop(self) -> None:
        try:
            if self._process.stdout is not None:
                for line in self._process.stdout:
                    try:
                        message = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(message, dict):
                        self._dispatch(message)
        finally:
            self._release_waiters()

    def _dispatch(self, message: Message) -> None:
        method = message.get("method")
        message_id = message.get("id")
        if method is None and isinstance(message_id, int):
            with self._state_lock:
                box = self._responses.get(message_id)
            if box is not None:
                box.put(message)
        elif method is not None and message_id is not None:
            reply: Message = {"id": message_id, "error": {"code": -32601, "message": f"unsupported request: {method}"}}
            try:
                self._send(reply)
            except ConnectionClosedError:
                return
        elif method is not None:
            params = message.get("params")
            thread_id = params.get("threadId") if isinstance(params, dict) else None
            with self._state_lock:
                events = self._threads.get(thread_id) if isinstance(thread_id, str) else None
            if events is not None:
                events.put(message)

    def _release_waiters(self) -> None:
        with self._state_lock:
            self._alive = False
            waiters = [*self._responses.values(), *self._threads.values()]
        for box in waiters:
            box.put(None)
