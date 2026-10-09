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
"""Material availability: explode a product's BOM against on-hand stock.

Inside the sandbox, reads go only through ``ontogeny.query`` and only for the object
types declared in the ``read-objects`` capability (bom, material, product).
Rows come back in the same shape the API returns, so ``stock_qty`` is a plain
column read here.
"""
import math


def material_availability(product_id: str, qty: int) -> dict:
    bom_lines = ontogeny.query("bom", filter={"product_id": product_id}, limit=200)
    if not bom_lines:
        return {"product_id": product_id, "ready": False, "shortage": [],
                "reason": "no BOM defined for this product"}

    products = ontogeny.query("product", filter={"product_id": product_id}, limit=1)
    materials = {m["material_id"]: m for m in ontogeny.query("material", limit=500)}

    shortage = []
    for line in bom_lines:
        material_id = line.get("material_id")
        per = float(line.get("qty_per_unit") or 0)
        scrap = float(line.get("scrap_rate") or 0)
        # the scrap allowance has to be stocked too
        required = math.ceil(per * qty * (1 + scrap))
        on_hand = int(materials.get(material_id, {}).get("stock_qty") or 0)
        if on_hand < required:
            shortage.append({
                "material_id": material_id,
                "material_name": materials.get(material_id, {}).get("name"),
                "required": required,
                "on_hand": on_hand,
                "gap": required - on_hand,
            })

    return {
        "product_id": product_id,
        "product_name": products[0].get("name") if products else None,
        "qty": qty,
        "bom_lines": len(bom_lines),
        "shortage": shortage,
        "ready": not shortage,
    }
