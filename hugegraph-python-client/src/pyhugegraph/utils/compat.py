# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""All legacy/graphspace wire differences live at this boundary."""

from urllib.parse import quote

from pyhugegraph.utils.exceptions import UnsupportedOperationError


class ServerAdapter:
    def __init__(self, cfg):
        self.cfg = cfg

    def adapt_path(self, path: str) -> str:
        if not self.cfg.gs_supported and (path == "graphspaces" or path.startswith("graphspaces/")):
            parts = path.split("/", 2)
            tail = parts[2] if len(parts) == 3 else ""
            if tail == "graphs" or tail.startswith("graphs/") or tail.startswith("auth/"):
                return tail
            raise UnsupportedOperationError("This operation requires a graphspace-enabled server")
        return path

    def resolve(self, path: str) -> str:
        # Leading '/' means server-scoped, while preserving a reverse-proxy prefix.
        if path.startswith("/"):
            relative = self.adapt_path(path.lstrip("/"))
        else:
            graph = quote(self.cfg.graph_name, safe="")
            if self.cfg.gs_supported:
                space = quote(self.cfg.graphspace, safe="")
                relative = f"graphspaces/{space}/graphs/{graph}/{path}"
            else:
                relative = f"graphs/{graph}/{path}"
        return self.cfg.url.rstrip("/") + "/" + relative.rstrip("/")

    def aliases(self) -> dict[str, str]:
        graph = self.cfg.graph_name
        if self.cfg.gs_supported:
            graph = f"{self.cfg.graphspace}-{graph}"
        return {"graph": graph, "g": f"__g_{graph}"}
