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
"""Work centre capacity: daily capacity vs open production orders.

Reads work centres and production orders through the sandbox query SDK; the
wall clock and the read capability list are enforced by the sandbox itself.
"""


def capacity_check(work_center_id: str, qty: int) -> dict:
    centers = ontogeny.query("work-center", filter={"work_center_id": work_center_id}, limit=1)
    if not centers:
        return {"work_center_id": work_center_id, "ok": False,
                "reason": "work centre not found"}

    center = centers[0]
    per_shift = int(center.get("capacity_per_shift") or 0)
    shifts = int(center.get("shifts_per_day") or 1) or 1
    daily = per_shift * shifts
    if daily <= 0:
        return {"work_center_id": work_center_id, "ok": False,
                "reason": "no capacity configured"}

    open_orders = [
        o for o in ontogeny.query("production-order", limit=500)
        if o.get("status") in ("PLANNED", "RELEASED")
    ]
    committed = sum(int(o.get("qty") or 0) for o in open_orders)

    days_needed = -(-qty // daily)            # ceil division
    backlog_days = -(-committed // daily)     # ceil division
    lead_days = backlog_days + days_needed

    return {
        "work_center_id": work_center_id,
        "work_center_name": center.get("name"),
        "capacity_per_shift": per_shift,
        "shifts_per_day": shifts,
        "daily_capacity": daily,
        "committed_qty": committed,
        "open_orders": len(open_orders),
        "qty": qty,
        "days_needed": days_needed,
        "backlog_days": backlog_days,
        "lead_days": lead_days,
        "ok": lead_days <= 20,
        "status": center.get("status"),
    }
