# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Strict URI parsing and canonical construction for HugeGraph MCP resources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote, unquote, urlsplit

MAX_SEGMENT_LENGTH = 128
MAX_PLAN_ID_LENGTH = 128

ResourceKind = Literal["schema", "summary", "embeddings_vid", "plan"]


class InvalidResourceURIError(ValueError):
    """Raised when a resource URI violates canonical syntax or security rules."""


def _validate_segment(raw: str, *, field_name: str, max_length: int = MAX_SEGMENT_LENGTH) -> str:
    if not raw:
        raise InvalidResourceURIError(f"{field_name} segment must not be empty")
    decoded = unquote(raw)
    # Reject double-encoding such as %252e%252e
    if "%" in decoded and unquote(decoded) != decoded:
        raise InvalidResourceURIError(f"{field_name} segment must not be double-encoded")
    if "\x00" in decoded or "/" in decoded or "\\" in decoded:
        raise InvalidResourceURIError(f"{field_name} segment contains forbidden characters")
    if decoded in {".", ".."}:
        raise InvalidResourceURIError(f"{field_name} segment must not be '.' or '..'")
    if len(decoded) > max_length:
        raise InvalidResourceURIError(f"{field_name} segment exceeds {max_length} characters")
    return decoded


def _encode_segment(value: str) -> str:
    return quote(value, safe="-_.~")


@dataclass(frozen=True)
class GraphResourceURI:
    deployment: str
    graphspace: str
    graph: str
    kind: Literal["schema", "summary", "embeddings_vid"]

    def to_uri(self) -> str:
        base = (
            f"hugegraph://{_encode_segment(self.deployment)}"
            f"/{_encode_segment(self.graphspace)}"
            f"/{_encode_segment(self.graph)}"
        )
        if self.kind == "embeddings_vid":
            return f"{base}/embeddings/vid"
        return f"{base}/{self.kind}"


@dataclass(frozen=True)
class PlanResourceURI:
    plan_id: str
    kind: Literal["plan"] = "plan"

    def to_uri(self) -> str:
        return f"plan://{_encode_segment(self.plan_id)}"


ParsedResourceURI = GraphResourceURI | PlanResourceURI


def build_graph_resource_uri(
    deployment: str,
    graphspace: str | None,
    graph: str,
    kind: Literal["schema", "summary", "embeddings_vid"],
) -> str:
    """Build a canonical hugegraph:// resource URI."""
    gs = _validate_segment(graphspace or "DEFAULT", field_name="graphspace")
    dep = _validate_segment(deployment or "default", field_name="deployment")
    g = _validate_segment(graph, field_name="graph")
    return GraphResourceURI(deployment=dep, graphspace=gs, graph=g, kind=kind).to_uri()


def build_plan_resource_uri(plan_id: str) -> str:
    """Build a canonical plan://{plan_id} resource URI."""
    pid = _validate_segment(plan_id, field_name="plan_id", max_length=MAX_PLAN_ID_LENGTH)
    return PlanResourceURI(plan_id=pid).to_uri()


def parse_resource_uri(uri: str) -> ParsedResourceURI:
    """Parse and validate a hugegraph:// or plan:// resource URI."""
    if not isinstance(uri, str) or not uri:
        raise InvalidResourceURIError("Resource URI must be a non-empty string")
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in uri):
        raise InvalidResourceURIError("Resource URI must not contain control characters")
    if "?" in uri or "#" in uri:
        raise InvalidResourceURIError("Resource URI must not contain query parameters or fragments")
    parsed = urlsplit(uri)

    scheme = parsed.scheme.lower()
    if scheme == "plan":
        if parsed.path != "":
            raise InvalidResourceURIError("plan:// URI must have no path segments")
        plan_id = _validate_segment(parsed.netloc, field_name="plan_id", max_length=MAX_PLAN_ID_LENGTH)
        return PlanResourceURI(plan_id=plan_id)

    if scheme == "hugegraph":
        deployment = _validate_segment(parsed.netloc, field_name="deployment")
        raw_parts = [p for p in parsed.path.split("/") if p != ""]
        # Reject trailing slash or empty middle segments (e.g., //)
        if parsed.path.endswith("/") or "//" in parsed.path:
            raise InvalidResourceURIError("hugegraph:// URI must not contain empty path segments")
        if len(raw_parts) < 3:
            raise InvalidResourceURIError("hugegraph:// URI requires /{graphspace}/{graph}/{resource}")
        graphspace = _validate_segment(raw_parts[0], field_name="graphspace")
        graph = _validate_segment(raw_parts[1], field_name="graph")
        tail = [_validate_segment(seg, field_name="resource") for seg in raw_parts[2:]]
        if tail == ["schema"]:
            return GraphResourceURI(deployment=deployment, graphspace=graphspace, graph=graph, kind="schema")
        if tail == ["summary"]:
            return GraphResourceURI(deployment=deployment, graphspace=graphspace, graph=graph, kind="summary")
        if tail == ["embeddings", "vid"]:
            return GraphResourceURI(deployment=deployment, graphspace=graphspace, graph=graph, kind="embeddings_vid")
        raise InvalidResourceURIError(f"Unsupported hugegraph:// resource path: /{'/'.join(tail)}")

    raise InvalidResourceURIError(f"Unsupported resource URI scheme: {parsed.scheme!r}")
