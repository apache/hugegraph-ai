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

"""DSL surface of the document data source: the declarations must fail closed."""

from __future__ import annotations

import shutil

import yaml
from doc_fixtures import DOMAIN

from ontogeny.core import load_package
from ontogeny.core.validator import validate
from ontogeny.projection import compile_projection
from ontogeny.registry import compile_package


def _codes(report) -> set[str]:
    return {i.code for i in report.issues}


def _copy(tmp_path):
    pkg = tmp_path / "pkg"
    shutil.copytree(DOMAIN, pkg)
    return pkg


def test_supplier_risk_package_is_valid():
    report = validate(load_package(DOMAIN))
    assert report.ok, report.entries


def test_document_store_is_read_only(tmp_path):
    pkg = _copy(tmp_path)
    path = pkg / "stores" / "supplier-docs.yaml"
    doc = yaml.safe_load(path.read_text())
    doc["spec"]["access"] = "read-write"
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    report = validate(load_package(pkg))
    assert "STORE-DOC-RO" in _codes(report)


def test_extract_strategy_requires_a_document_store(tmp_path):
    pkg = _copy(tmp_path)
    path = pkg / "objects" / "supplier-note.yaml"
    doc = yaml.safe_load(path.read_text())
    doc["spec"]["backing"]["store"] = "suppliers"
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    report = validate(load_package(pkg))
    assert "SYNC-EXTRACT-STORE" in _codes(report)


def test_extract_key_must_be_a_property(tmp_path):
    pkg = _copy(tmp_path)
    path = pkg / "objects" / "supplier-note.yaml"
    doc = yaml.safe_load(path.read_text())
    doc["spec"]["backing"]["extract"]["key"] = ["nope"]
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    report = validate(load_package(pkg))
    assert "SYNC-EXTRACT-KEY" in _codes(report)


def test_composite_primary_key_is_rejected_for_extraction(tmp_path):
    pkg = _copy(tmp_path)
    path = pkg / "objects" / "supplier-note.yaml"
    doc = yaml.safe_load(path.read_text())
    doc["spec"]["primaryKey"] = ["note_id", "supplier_name"]
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    report = validate(load_package(pkg))
    assert "SYNC-EXTRACT-PK" in _codes(report)


def test_extracted_link_without_a_document_endpoint_warns(tmp_path):
    pkg = _copy(tmp_path)
    for name in ("supplier.yaml", "supplier-note.yaml"):
        path = pkg / "objects" / name
        doc = yaml.safe_load(path.read_text())
        doc["spec"]["backing"]["sync"]["strategy"] = "snapshot"
        path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    report = validate(load_package(pkg))
    assert "LINK-EXTRACT-SOURCE" in _codes(report)


def test_projection_compiles_extracted_links():
    compiled = compile_package(load_package(DOMAIN))
    projection = compiled.projections["supplier-graph"]
    schema = compile_projection(compiled, projection)
    edges = {e["name"]: e for e in schema["edgelabels"]}
    assert "supplier-risk-note" in edges
    assert edges["supplier-risk-note"]["source_label"] == "supplier"
    labels = {v["label"] for v in schema["vertexlabels"]}
    assert {"supplier", "supplier-note"} <= labels
