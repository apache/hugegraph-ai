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
# specific language governing permissions and
# limitations under the License.

"""Yield-loss pareto across wafer lots.

Only wafer-test and process-step are read. Each tested lot is ranked by its
CP yield loss and carries its process route (step name @ equipment, in
sequence), so the biggest loss bucket and the equipment behind it surface
first.
"""


def yield_pareto() -> dict:
    tested: dict[str, dict] = {}
    for t in ontogeny.query("wafer-test", limit=500):
        lot_id = t.get("lot_id")
        if not lot_id:
            continue
        lot = tested.setdefault(lot_id, {"lot_id": lot_id, "tested": 0, "defects": 0})
        lot["tested"] += int(t.get("tested_qty") or 0)
        lot["defects"] += int(t.get("defect_qty") or 0)

    steps: dict[str, list[tuple[int, str, str]]] = {}
    for s in ontogeny.query("process-step", limit=1000):
        lot_id = s.get("lot_id")
        if lot_id:
            steps.setdefault(lot_id, []).append(
                (int(s.get("seq") or 0), s.get("name") or "", s.get("equipment") or "")
            )

    ranking = []
    for lot_id, lot in tested.items():
        loss = round(lot["defects"] / lot["tested"], 4) if lot["tested"] else None
        if loss is None:
            continue
        route = [f"{name}@{equipment}" for _seq, name, equipment in sorted(steps.get(lot_id, []))]
        ranking.append({"lot_id": lot_id, "loss": loss, "route": route})
    ranking.sort(key=lambda r: r["loss"], reverse=True)
    return {"lots_with_tests": len(ranking), "ranking": ranking}
