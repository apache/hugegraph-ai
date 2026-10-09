# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Exercise an installed MCP command from outside the checkout with an HTTP fixture.

Usage: python distribution_smoke.py -- uvx --from /absolute/package.whl hugegraph-mcp
This verifies packaging and MCP/HTTP wiring, not a real HugeGraph deployment.
"""

import argparse
import json
import logging
import os
import queue
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


class GraphFixture(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/graphspaces/DEFAULT/graphs/hugegraph/schema":
            data = {
                "propertykeys": [],
                "vertexlabels": [{"id": 1, "name": "person", "properties": []}],
                "edgelabels": [],
                "indexlabels": [],
            }
        elif path == "/graphspaces/DEFAULT/graphs/hugegraph/graph/vertices":
            data = {"vertices": [{"id": "1:alice", "label": "person", "properties": {}}], "page": None}
        else:
            self.send_error(404)
            return
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def exercise(process, timeout):
    responses = queue.Queue()

    def read_stdout():
        try:
            for line in process.stdout:
                responses.put(line)
        finally:
            responses.put(None)

    reader = threading.Thread(target=read_stdout, daemon=True)
    reader.start()

    def send(message):
        process.stdin.write(json.dumps({"jsonrpc": "2.0", **message}) + "\n")
        process.stdin.flush()

    def call(request_id, method, params):
        send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + timeout
        while True:
            try:
                line = responses.get(timeout=max(0, deadline - time.monotonic()))
            except queue.Empty as exc:
                raise RuntimeError(f"Timed out waiting for {method}") from exc
            require(line is not None, f"MCP process closed stdout during {method}")
            response = json.loads(line)
            if response.get("id") == request_id:
                require("error" not in response, f"{method} failed: {response.get('error')}")
                return response["result"]

    initialized = call(
        1,
        "initialize",
        {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "package-smoke", "version": "1"}},
    )
    require("tools" in initialized["capabilities"], "Server does not advertise tools")
    send({"method": "notifications/initialized"})
    tools = {tool["name"] for tool in call(2, "tools/list", {})["tools"]}
    require(len(tools) == 16, f"Expected 16 v2 tools, received {len(tools)}")
    require({"inspect_graph_tool", "query_graph_data_tool"} <= tools, "Missing inspection/query tools")

    def tool_call(request_id, name, arguments):
        result = call(request_id, "tools/call", {"name": name, "arguments": arguments})
        require(not result.get("isError"), f"{name} returned an MCP error: {result}")
        envelope = result.get("structuredContent")
        if envelope is None:
            envelope = json.loads(result["content"][0]["text"])
        require(envelope.get("ok") is True, f"{name} failed: {envelope}")
        return envelope["data"]

    inspected = tool_call(3, "inspect_graph_tool", {"include_raw_schema": True})
    require(inspected["hugegraph_server_status"] == "available", "HTTP graph fixture is unavailable")
    require(inspected["toolset"] == "v2_core", "Unexpected toolset")
    queried = tool_call(
        4, "query_graph_data_tool", {"target": "vertex", "operation": "page", "label": "person", "limit": 5}
    )
    require([item["id"] for item in queried["items"]] == ["1:alice"], "Unexpected query result")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=180, help="Maximum seconds per MCP request")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command or args.timeout <= 0:
        parser.error("provide a server command after -- and a positive timeout")

    with (
        tempfile.TemporaryDirectory(prefix="mcp-distribution-") as scratch,
        ThreadingHTTPServer(("127.0.0.1", 0), GraphFixture) as server,
    ):
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        env = {key: value for key, value in os.environ.items() if not key.startswith(("HUGEGRAPH_", "PYTHONPATH"))}
        env.update(
            HUGEGRAPH_URL=f"http://127.0.0.1:{server.server_port}",
            HUGEGRAPH_GRAPH_PATH="DEFAULT/hugegraph",
            HUGEGRAPH_USER="admin",
            HUGEGRAPH_PASSWORD="admin",
            HUGEGRAPH_MCP_READONLY="true",
            HUGEGRAPH_MCP_ALLOW_AI="false",
            HUGEGRAPH_MCP_TOOLSET="v2_core",
            HUGEGRAPH_MCP_STATE_DIR=str(Path(scratch) / "state"),
            NO_PROXY="127.0.0.1,localhost",
            no_proxy="127.0.0.1,localhost",
        )
        try:
            with subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, cwd=scratch, env=env
            ) as process:
                try:
                    exercise(process, args.timeout)
                finally:
                    process.stdin.close()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
        finally:
            server.shutdown()
            worker.join(timeout=5)
    logging.basicConfig(level=logging.INFO)
    logging.info("MCP distribution smoke passed: initialize, 16 tools, inspect, query (HTTP fixture)")


if __name__ == "__main__":
    main()
