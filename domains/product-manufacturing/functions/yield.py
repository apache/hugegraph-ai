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
"""Order yield: inspection results and routing progress for one order.

Only reads the object types the capability declares (quality-inspection,
operation, production-order); everything arrives as plain rows.
"""


def order_yield(order_id: str) -> dict:
    orders = ontogeny.query("production-order", filter={"order_id": order_id}, limit=1)
    if not orders:
        return {"order_id": order_id, "ok": False, "reason": "order not found"}

    inspections = ontogeny.query("quality-inspection", filter={"order_id": order_id}, limit=100)
    operations = ontogeny.query("operation", filter={"order_id": order_id}, limit=100)

    inspected = sum(int(i.get("inspected_qty") or 0) for i in inspections)
    defects = sum(int(i.get("defect_qty") or 0) for i in inspections)
    good = inspected - defects
    pass_rate = round(good / inspected, 4) if inspected else None

    done = [o for o in operations if o.get("status") == "COMPLETED"]

    return {
        "order_id": order_id,
        "product_id": orders[0].get("product_id"),
        "order_status": orders[0].get("status"),
        "operations_total": len(operations),
        "operations_completed": len(done),
        "routing_complete": bool(operations) and len(done) == len(operations),
        "inspections": len(inspections),
        "inspected_qty": inspected,
        "defect_qty": defects,
        "pass_rate": pass_rate,
        "ok": inspected > 0 and defects <= inspected,
    }
