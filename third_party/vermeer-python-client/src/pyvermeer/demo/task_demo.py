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

from pyvermeer.client.client import PyVermeerClient
from pyvermeer.structure.task_data import TaskCreateRequest


def main():
    """main"""
    client = PyVermeerClient(
        ip="127.0.0.1",
        port=8688,
        token="",
        log_level="DEBUG",
    )
    client.tasks.get_tasks()

    client.tasks.create_task(
        create_task=TaskCreateRequest(
            task_type="load",
            graph_name="DEFAULT-example",
            params={
                "load.hg_pd_peers": '["127.0.0.1:8686"]',
                "load.hugegraph_name": "DEFAULT/example/g",
                "load.hugegraph_password": "xxx",
                "load.hugegraph_username": "xxx",
                "load.parallel": "10",
                "load.type": "hugegraph",
            },
        )
    )


if __name__ == "__main__":
    main()
