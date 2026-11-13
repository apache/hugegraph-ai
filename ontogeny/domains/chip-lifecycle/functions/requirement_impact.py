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

"""Forward impact of one requirement across the lifecycle chain.

Inside the sandbox, reads go only through ``ontogeny.query`` and only for the
object types declared in the ``read-objects`` capability (requirement,
design-module, tapeout-version, wafer-lot). The function never writes;
changing a requirement is the change-requirement Action.
"""


def requirement_impact(requirement_id: str) -> dict:
    reqs = ontogeny.query("requirement", filter={"requirement_id": requirement_id}, limit=1)
    if not reqs:
        return {"requirement_id": requirement_id, "found": False}
    requirement = reqs[0]

    modules = ontogeny.query("design-module", filter={"requirement_id": requirement_id}, limit=200)
    version_ids = {m.get("version_id") for m in modules if m.get("version_id")}
    versions = [v for v in ontogeny.query("tapeout-version", limit=500) if v.get("version_id") in version_ids]
    lots = [lot for lot in ontogeny.query("wafer-lot", limit=500) if lot.get("version_id") in version_ids]
    at_risk = [lot for lot in lots if lot.get("status") == "RUNNING"]

    return {
        "requirement_id": requirement_id,
        "found": True,
        "title": requirement.get("title"),
        "priority": requirement.get("priority"),
        "status": requirement.get("status"),
        "modules": [{"module_id": m.get("module_id"), "name": m.get("name")} for m in modules],
        "versions": [
            {"version_id": v.get("version_id"), "project": v.get("project"), "status": v.get("status")}
            for v in versions
        ],
        "lots": [{"lot_id": lot.get("lot_id"), "status": lot.get("status")} for lot in lots],
        "at_risk_lots": [lot.get("lot_id") for lot in at_risk],
        "at_risk_wafers": sum(int(lot.get("qty_wafers") or 0) for lot in at_risk),
    }
