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


import argparse

from hugegraph_llm.config import (
    PromptConfig,
    admin_settings,
    huge_settings,
    index_settings,
    llm_settings,
)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate hugegraph-llm config file")
    parser.add_argument("-U", "--update", default=True, action="store_true", help="Update the config file")
    args = parser.parse_args()
    if args.update:
        huge_settings.generate_env()
        admin_settings.generate_env()
        llm_settings.generate_env()
        index_settings.generate_env()
        PromptConfig(llm_settings).generate_yaml_file()
