# Copyright 2026 Apache HugeGraph Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Diagnoser: deterministic gap hypotheses from signals (LLM explains, rules
decide -- the selection function is never outsourced)."""
from __future__ import annotations

from typing import Any

from ..core.types import PropertyType
from .models import EvolveSignalRow

INFORMATIONAL = {"empty_query_rate", "action_rule_reject", "agent_tool_error"}


def diagnose(signals: list[EvolveSignalRow], compiled) -> list[dict[str, Any]]:
    concrete: list[dict[str, Any]] = []
    informational: list[dict[str, Any]] = []
    for sig in signals:
        ev = sig.evidence or {}
        kind = sig.kind
        if kind == "unmapped_filter_field":
            concrete.append({
                "kind": "add-optional-property",
                "object": ev.get("object_type"),
                "prop": ev.get("field"),
                "type": "string",
                "signal_id": sig.id,
                "rationale": (
                    f"filter field {ev.get('field')!r} used {ev.get('count')}x on "
                    f"{ev.get('object_type')!r} but is not modeled; add as optional property"
                ),
            })
        elif kind == "quarantine_rate" and ev.get("code") == "TYPE_MISMATCH":
            # a plausible enum member the source produced -> widen the domain.
            # The evidence (prop/value) is attached by the caller from the
            # quarantine row; without it the gap stays informational.
            widen = enum_widen_gap(ev.get("object_type"), ev.get("prop"), ev.get("value"), compiled) \
                if ev.get("prop") and ev.get("value") else None
            if widen is not None:
                widen["signal_id"] = sig.id
                widen["rationale"] = (
                    f"{ev.get('count')} quarantined rows on {ev.get('object_type')!r} produced "
                    f"{ev.get('value')!r} for {ev.get('prop')!r}; widen the enum domain"
                )
                concrete.append(widen)
            else:
                concrete.append({
                    "kind": "schema-mismatch",
                    "object": ev.get("object_type"),
                    "signal_id": sig.id,
                    "rationale": f"{ev.get('count')} quarantined rows on {ev.get('object_type')!r}; review mapping/types",
                })
        elif kind == "hot_query" and ev.get("object_type") and ev.get("filter"):
            # a recurring filter that returns data -> keep it working forever:
            # synthesize a regression case into the owned eval suite
            synth = eval_case_gap(ev, compiled)
            if synth is not None:
                synth["signal_id"] = sig.id
                synth["rationale"] = (
                    f"filter {ev.get('filter')!r} on {ev.get('object_type')!r} returned data "
                    f"{ev.get('count')}x; pin it as a regression case"
                )
                concrete.append(synth)
            else:
                informational.append(_info_gap(sig, ev))
        else:
            # informational signals (empty results, rule rejects, agent errors,
            # slow queries, approval friction) are surfaced for humans/LLM
            # reasoning, not auto-mutated
            informational.append(_info_gap(sig, ev))

    # direction D: informational signals about the SAME object are one story,
    # not N scattered findings -- cluster them, and attach them as context to
    # the concrete gaps about that object so the proposer sees the full picture
    by_object: dict[str, list[dict[str, Any]]] = {}
    for gap in informational:
        obj = gap.get("object")
        if obj:
            by_object.setdefault(obj, []).append(gap)
    clustered_ids: set[int] = set()
    for obj, items in by_object.items():
        if len(items) >= 2:
            clustered_ids.update(i["signal_id"] for i in items)
            concrete.append({
                "kind": "cluster",
                "object": obj,
                "evidence": {"object": obj, "signals": [i["evidence"] for i in items]},
                "signal_id": items[0]["signal_id"],
                "informational": True,
                "is_cluster": True,
                "rationale": f"{len(items)} signals converge on {obj!r} -- review together",
                "context": items,
            })
    for gap in concrete:
        related = by_object.get(gap.get("object"))
        if related:
            gap["context"] = related[:5]
    return [g for g in concrete
            if not (g.get("informational") and not g.get("is_cluster")
                    and g.get("signal_id") in clustered_ids)]


def _info_gap(sig: EvolveSignalRow, ev: dict[str, Any]) -> dict[str, Any]:
    return {"kind": sig.kind, "evidence": ev, "signal_id": sig.id,
            "object": ev.get("object_type") or ev.get("object"),
            "informational": True}


def eval_case_gap(ev: dict[str, Any], compiled) -> dict[str, Any] | None:
    """Build an eval-case-synth gap for a hot query, deduped against the
    suites already on file (None -> nothing new to pin)."""
    object_type, filt = ev.get("object_type"), ev.get("filter")
    suites = getattr(compiled, "eval_suites", {}) if compiled is not None else {}
    for suite in suites.values():
        for existing in suite.spec.queries:
            if existing.query.get("object") == object_type and \
                    existing.query.get("filter") == filt:
                return None  # already pinned as a regression
    suite_name = next(iter(suites), None)
    if suite_name is None:
        return None  # no owned suite to grow
    obj = compiled.objects.get(object_type) if compiled is not None else None
    pk = obj.spec.primaryKey[0] if obj and obj.spec.primaryKey else None
    expect: dict[str, Any] = {}
    if pk:
        expect["columns"] = [pk]
    return {
        "kind": "eval-case-synth",
        "suite": suite_name,
        "case": {"name": f"hot-{object_type}-{abs(hash(json_dumps(filt))) % 10000}",
                 "query": {"object": object_type, "filter": filt, "limit": 50},
                 "expect": expect},
        "object": object_type,
    }


def json_dumps(x: Any) -> str:
    import json
    return json.dumps(x, sort_keys=True, ensure_ascii=True, default=str)


def enum_widen_gap(object_type: str, prop: str, offending_value: str, compiled) -> dict[str, Any] | None:
    """Build an enum-widen gap when a quarantined value is a plausible enum member."""
    obj = compiled.objects.get(object_type)
    if obj is None:
        return None
    pdef = obj.spec.properties.get(prop)
    if pdef is None:
        return None
    ptype = PropertyType.parse(pdef.type)
    if ptype.kind != "enum":
        return None
    return {
        "kind": "enum-widen",
        "object": object_type,
        "prop": prop,
        "value": offending_value,
        "rationale": f"source produced {offending_value!r} for {object_type}.{prop}; widen the enum domain",
    }
