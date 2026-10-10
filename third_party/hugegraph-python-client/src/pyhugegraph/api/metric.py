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

from pyhugegraph.api.common import HugeParamsBase
from pyhugegraph.utils import huge_router as router


class MetricsManager(HugeParamsBase):
    @router.http("GET", "/metrics/?type=json")
    def get_all_basic_metrics(self) -> dict:
        return self._invoke_request()

    @router.http("GET", "/metrics/gauges")
    def get_gauges_metrics(self) -> dict:
        return self._invoke_request()

    @router.http("GET", "/metrics/counters")
    def get_counters_metrics(self) -> dict:
        return self._invoke_request()

    @router.http("GET", "/metrics/gauges")
    def get_histograms_metrics(self) -> dict:
        return self._invoke_request()

    @router.http("GET", "/metrics/meters")
    def get_meters_metrics(self) -> dict:
        return self._invoke_request()

    @router.http("GET", "/metrics/timers")
    def get_timers_metrics(self) -> dict:
        return self._invoke_request()

    @router.http("GET", "/metrics/statistics/?type=json")
    def get_statistics_metrics(self) -> dict:
        return self._invoke_request()

    @router.http("GET", "/metrics/system")
    def get_system_metrics(self) -> dict:
        return self._invoke_request()

    @router.http("GET", "/metrics/backend")
    def get_backend_metrics(self) -> dict:
        return self._invoke_request()
