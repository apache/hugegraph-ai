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

"""Regenerate REST resources and compare the contract with a server OpenAPI export.

Usage: python scripts/client_api.py --check
       python scripts/client_api.py --write
       python scripts/client_api.py --openapi server-openapi.json
"""

import argparse
import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "hugegraph-python-client/src/pyhugegraph"


def render_resources():
    root = PACKAGE
    contract = json.loads((root / "api/server_contract.json").read_text())
    groups = {}
    for operation, spec in contract["operations"].items():
        group, method = operation.split(".")
        groups.setdefault(group, []).append((operation, method, spec))
    license = (root / "api/olap.py").read_text().split('"""')[0]
    out = (
        license + '"""Explicit low-level REST resources for the pinned server contract.\n\n'
        "Common workflows are available on the client managers; these resources expose\n"
        'every REST operation, including deployment-specific extensions.\n"""\n\n'
        "from typing import Any\n\nfrom pyhugegraph.api.common import RestResource\n\n"
    )
    for group, methods in groups.items():
        cls = "".join(x.title() for x in group.split("_")) + "API"
        out += "\nclass " + cls + "(RestResource):\n"
        for operation, name, op in methods:
            pp = [x for x in re.findall(r"{(\w+)}", op["path"]) if x not in {"graphspace", "graph"}]
            # All operations accept an optional entity. Server-side validation remains authoritative.
            args = ["self"] + [f"{x}: Any" for x in pp]
            args += ["*"] if op["body"] or op["query"] or op["headers"] else []
            args += ["body: Any = None"] if op["body"] else []
            args += ["authorization: str | None = None"] if op["headers"] else []
            args += [f"{q}: Any = None" for q in op["query"] if q not in pp]
            args += ["query: dict[str, Any] | None = None"] if op.get("query_passthrough") else []
            path_arg = ", path_params={" + ", ".join(repr(x) + ": " + x for x in pp) + "}" if pp else ""
            query_arg = ", params={" + ", ".join(repr(q) + ": " + q for q in op["query"]) + "}" if op["query"] else ""
            if op.get("query_passthrough"):
                query_arg += " | (query or {})"
            body_arg = ", body=body" if op["body"] else ""
            body_arg += ', headers={"Authorization": authorization}' if op["headers"] else ""
            out += (
                f"\n    def {name}({', '.join(args)}) -> Any:\n"
                f'        """{op["method"]} /{op["path"]}."""\n'
                f"        return self.request({operation!r}{path_arg}{query_arg}{body_arg})\n"
            )
    out += (
        "\n\nclass RestManager(RestResource):\n"
        '    """Complete REST surface; all child resources share the client session."""\n\n'
        "    def __init__(self, session):\n        super().__init__(session)\n"
    )
    for group in groups:
        cls = "".join(x.title() for x in group.split("_")) + "API"
        out += f"        self.{group} = {cls}(session)\n"
    return out


def render_algorithms(contract):
    source = (PACKAGE / "api/olap.py").read_text()
    marker = "    # BEGIN GENERATED ALGORITHM METHODS\n"
    prefix, _ = source.split(marker, 1)
    methods = []
    for name in contract["algorithms"]:
        methods.append(
            f"\n    def {name}(self, parameters: Mapping[str, Any] | None = None) -> dict:\n"
            f'        """Submit the {name} full-graph algorithm and return its task receipt."""\n'
            f'        return self.submit("{name}", parameters)\n'
        )
    return prefix + marker + "".join(methods)


def check_operation_bindings(contract):
    errors = []
    known = contract["operations"]
    for path in (PACKAGE / "api").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "request"
                and node.args
                and isinstance(node.args[0], ast.Constant)
            ):
                value = node.args[0].value
                if isinstance(value, str) and re.fullmatch(r"[a-z_]+\.[a-z_]+", value) and value not in known:
                    errors.append(f"{path.name}:{node.lineno}: unknown operation {value}")
    return errors


def normalized(path):
    return re.sub(r"{[^}]+}", "{}", path.strip("/"))


def normalized_media_types(content):
    if not isinstance(content, dict):
        return set()
    return {media_type.split(";", 1)[0].strip().lower() for media_type in content}


def compare_openapi(document, contract):
    if not isinstance(document.get("paths"), dict):
        raise ValueError("OpenAPI document must contain a paths object")
    expected = {}
    for spec in contract["operations"].values():
        key = (spec["method"].lower(), normalized(spec["path"]))
        body = bool(spec.get("body", False))
        request_media = {spec["content_type"].split(";", 1)[0].strip().lower()} if body else set()
        shape = expected.setdefault(key, {"query": set(), "body": body, "request_media": request_media})
        if shape["body"] != body or shape["request_media"] != request_media:
            raise ValueError(f"Conflicting contract entries for {key[0].upper()} /{key[1]}")
        shape["query"].update(spec.get("openapi_query", spec["query"]))
    actual = {}
    for path, item in document["paths"].items():
        for method, operation in item.items():
            if method.lower() not in {"get", "post", "put", "delete", "patch", "head", "options"}:
                continue
            params = item.get("parameters", []) + operation.get("parameters", [])
            request_body = operation.get("requestBody")
            actual[(method.lower(), normalized(path))] = {
                "query": {p["name"] for p in params if p.get("in") == "query"},
                "body": request_body is not None,
                "request_media": normalized_media_types(request_body.get("content", {}))
                if isinstance(request_body, dict)
                else set(),
            }
    for spec in contract.get("platform_operations", []):
        actual.pop((spec["method"].lower(), normalized(spec["path"])), None)
    result = []
    for key in sorted(actual.keys() - expected.keys()):
        result.append(f"ADDED {key[0].upper()} /{key[1]}")
    for key in sorted(expected.keys() - actual.keys()):
        result.append(f"MISSING {key[0].upper()} /{key[1]}")
    for key in sorted(expected.keys() & actual.keys()):
        expected_shape = expected[key]
        actual_shape = actual[key]
        if actual_shape["query"] != expected_shape["query"]:
            result.append(
                f"PARAMETERS {key[0].upper()} /{key[1]}: "
                f"added={sorted(actual_shape['query'] - expected_shape['query'])}, "
                f"missing={sorted(expected_shape['query'] - actual_shape['query'])}"
            )
        if actual_shape["body"] != expected_shape["body"]:
            result.append(
                f"BODY {key[0].upper()} /{key[1]}: "
                f"expected={expected_shape['body']}, actual={actual_shape['body']}"
            )
        if actual_shape["request_media"] != expected_shape["request_media"]:
            result.append(
                f"REQUEST MEDIA {key[0].upper()} /{key[1]}: "
                f"added={sorted(actual_shape['request_media'] - expected_shape['request_media'])}, "
                f"missing={sorted(expected_shape['request_media'] - actual_shape['request_media'])}"
            )
    return result


def coverage_table(contract):
    lines = ["| Python REST entry | Method | Path | Query parameters |", "| --- | --- | --- | --- |"]
    for operation, spec in sorted(contract["operations"].items()):
        query = ", ".join(spec["query"]) or "—"
        if spec.get("query_passthrough"):
            query += "; additional query map"
        lines.append(f"| `rest.{operation}()` | {spec['method']} | `/{spec['path']}` | {query} |")
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="check static resources and coverage table")
    parser.add_argument("--write", action="store_true", help="regenerate static resources and coverage table")
    parser.add_argument("--openapi", type=Path, help="compare an offline server OpenAPI JSON document")
    parser.add_argument("--website-root", type=Path, help="also synchronize the bilingual website reference tables")
    args = parser.parse_args()
    contract = json.loads((PACKAGE / "api/server_contract.json").read_text())
    generated = render_resources()
    algorithms = render_algorithms(contract)
    algorithm_target = PACKAGE / "api/olap.py"
    target = PACKAGE / "api/rest.py"
    reference = ROOT / "hugegraph-python-client/API_COVERAGE.md"
    table = "# REST coverage\n\nServer: `" + contract["server_ref"] + "`\n\n" + coverage_table(contract)
    if args.write:
        target.write_text(generated)
        algorithm_target.write_text(algorithms)
        reference.write_text(table)
    elif (
        ast.dump(ast.parse(target.read_text())) != ast.dump(ast.parse(generated))
        or ast.dump(ast.parse(algorithm_target.read_text())) != ast.dump(ast.parse(algorithms))
        or not reference.exists()
        or reference.read_text() != table
    ):
        parser.exit(1, "Generated API/coverage is stale. Run python scripts/client_api.py --write and format.\n")
    errors = check_operation_bindings(contract)
    if errors:
        parser.exit(1, "\n".join(errors) + "\n")
    if args.website_root:
        for lang in ("en", "cn"):
            page = args.website_root / f"content/{lang}/docs/clients/hugegraph-python-client.md"
            source = page.read_text()
            start = "<!-- BEGIN REST CONTRACT -->\n"
            end = "<!-- END REST CONTRACT -->"
            before, tail = source.split(start, 1)
            _, after = tail.split(end, 1)
            updated = before + start + coverage_table(contract) + "{.wide}\n\n" + end + after
            if args.write:
                page.write_text(updated)
            elif updated != source:
                parser.exit(1, f"{page}: stale REST table\n")
    if args.openapi:
        changes = compare_openapi(json.loads(args.openapi.read_text()), contract)
        if changes:
            parser.exit(1, "\n".join(changes) + "\n")
    sys.stdout.write(
        f"{len(contract['operations'])} operations; {len(contract['algorithms'])} OLAP algorithms; "
        f"server {contract['server_ref']}\n"
    )


if __name__ == "__main__":
    main()
