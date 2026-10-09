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

import json
from dataclasses import asdict, dataclass, field


@dataclass
class ServiceCreateParameters:
    """
    Data class representing the request body for HugeGraph services.

    Attributes:
      - name (str): The name of the service. It must consist of lowercase letters, numbers, and underscores.
                    The first character must be a lowercase letter and the length must not exceed 48.
      - description (str): A description of the service.
      - type (str): The type of service. Currently, only 'OLTP' is allowed. Default is 'OLTP'.
      - count (int): The number of HugeGraphServer instances. Must be greater than 0. Default is 1.
      - cpu_limit (int): The number of CPU cores per HugeGraphServer instance. Must be greater than 0. Default is 1.
      - memory_limit (int): The memory size per HugeGraphServer instance in GB. Must be greater than 0. Default is 4.
      - storage_limit (int): The disk size for HStore in GB. Must be greater than 0. Default is 100.
      - route_type (str): Required when deployment_type is 'K8S'.
                          Accepted values are 'ClusterIP', 'LoadBalancer', 'NodePort'.
      - port (int): Required when deployment_type is 'K8S'. Must be greater than 0.
                    Default is None and invalid for other deployment types.
      - urls (List[str]): Required when deployment_type is 'MANUAL'.
                          Should not be provided for other deployment types.
      - deployment_type (str): The deployment type of the service.
                               'K8S' indicates service deployment through a Kubernetes cluster,
                               'MANUAL' indicates manual service deployment. Default is an empty string.
    """

    name: str
    description: str
    type: str = "OLTP"
    count: int = 1
    cpu_limit: int = 1
    memory_limit: int = 4
    storage_limit: int = 100
    route_type: str | None = None
    port: int | None = None
    urls: list[str] = field(default_factory=list)
    deployment_type: str | None = None

    def dumps(self):
        return json.dumps(asdict(self))
