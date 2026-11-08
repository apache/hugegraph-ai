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

"""Read-only yield-loss candidates for one CP wafer test.

Only wafer-test and wafer-lot are read. The function never writes;
record-root-cause is the Action that persists a reviewed result.
"""


def analyze_yield_loss(test_id: str) -> dict:
    rows = ontogeny.query("wafer-test", filter={"test_id": test_id}, limit=1)
    if not rows:
        return {"test_id": test_id, "found": False, "candidates": []}
    test = rows[0]
    lot = ontogeny.query("wafer-lot", filter={"lot_id": test.get("lot_id")}, limit=1)
    tested = int(test.get("tested_qty") or 0)
    defects = int(test.get("defect_qty") or 0)
    loss = round(defects / tested, 4) if tested else None

    candidates = []
    if loss is not None and loss > 0.05:
        candidates.append(
            {
                "root_cause": "Process drift on the routed process step",
                "root_cause_class": "PROCESS",
                "evidence": f"yield loss {loss:.2%} on {tested} tested units",
                "confidence": 0.82 if loss > 0.10 else 0.66,
            }
        )
    candidates.append(
        {
            "root_cause": "Marginal design against a tight requirement",
            "root_cause_class": "DESIGN",
            "evidence": "defect signal; verify module margins against the covered requirement",
            "confidence": 0.55,
        }
    )
    candidates.sort(key=lambda cand: cand["confidence"], reverse=True)
    return {
        "test_id": test_id,
        "found": True,
        "lot_id": test.get("lot_id"),
        "lot_status": lot[0].get("status") if lot else None,
        "yield": round(1 - loss, 4) if loss is not None else None,
        "loss": loss,
        "candidates": candidates,
        "recommended_action": "HOLD" if (loss or 0) > 0.05 else "REVIEW",
    }
