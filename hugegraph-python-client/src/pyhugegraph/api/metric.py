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

"""Server metrics, including their JSON and text representations."""

from pyhugegraph.api.rest import MetricsAPI


class MetricsManager(MetricsAPI):
    def get_all_basic_metrics(self):
        return self.all(type="json")

    def get_gauges_metrics(self):
        return self.gauges()

    def get_counters_metrics(self):
        return self.counters()

    def get_histograms_metrics(self):
        return self.histograms()

    def get_meters_metrics(self):
        return self.meters()

    def get_timers_metrics(self):
        return self.timers()

    def get_statistics_metrics(self):
        return self.statistics(type="json")

    def get_system_metrics(self):
        return self.system()

    def get_backend_metrics(self):
        return self.backend()
