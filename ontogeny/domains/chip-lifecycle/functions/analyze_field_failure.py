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

"""Read-only root-cause candidates for one field failure.

Only field-failure and customer are read. The function never writes;
record-failure-root-cause is the Action that persists a reviewed result.
"""


def analyze_field_failure(failure_id: str) -> dict:
    rows = ontogeny.query("field-failure", filter={"failure_id": failure_id}, limit=1)
    if not rows:
        return {"failure_id": failure_id, "found": False, "candidates": []}
    failure = rows[0]
    customer = ontogeny.query("customer", filter={"customer_id": failure.get("customer_id")}, limit=1)

    candidates = [
        {
            "root_cause": "Lot-related process excursion",
            "root_cause_class": "PROCESS",
            "evidence": "cluster failures by wafer lot via shipment trace, then compare CP yield",
            "confidence": 0.55,
        }
    ]
    if failure.get("failure_mode") == "PARAMETRIC":
        candidates.append(
            {
                "root_cause": "Marginal design against a tight requirement",
                "root_cause_class": "DESIGN",
                "evidence": "parametric drift points at spec margin; check the covered requirement and its FMEA notes",
                "confidence": 0.62,
            }
        )
    candidates.sort(key=lambda cand: cand["confidence"], reverse=True)
    return {
        "failure_id": failure_id,
        "found": True,
        "customer_id": failure.get("customer_id"),
        "customer": customer[0].get("name") if customer else None,
        "symptom": failure.get("symptom"),
        "failure_mode": failure.get("failure_mode"),
        "candidates": candidates,
        "recommended_action": "REVIEW",
    }
