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


"""
项目配置管理模块。

负责加载和管理项目配置文件，提供各模块所需的配置参数。
"""

import json
import os


class Config:
    def __init__(self, file_path):
        self.file_path = file_path
        self.config_data = self.load_config()
        self.gen_query = self.config_data.get("genQuery")  # default genQuery，can be set as translate
        self.db_id = self.config_data.get("db_id")

    def load_config(self):
        try:
            with open(self.file_path, encoding="utf-8") as file:
                return json.load(file)
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"配置文件不存在: {self.file_path}") from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f"配置文件 JSON 格式错误: {self.file_path}, 错误: {exc}") from exc

    def get_input_query_path(self):
        return self.config_data.get("input_query_path")

    def get_input_query_template_path(self):
        return self.config_data.get("input_query_template_path")

    def get_input_corpus_dir_or_file(self):
        return self.config_data.get("input_corpus_dir_or_path")

    def set_input_corpus_dir_or_file(self, dir_or_file):
        self.config_data["input_corpus_dir_or_path"] = dir_or_file

    def get_output_path(self):
        if self.gen_query:
            dir_or_file = self.config_data.get("output_query_dir_or_file")
            if os.path.isdir(dir_or_file):
                output_path = os.path.join(dir_or_file, self.db_id + ".txt")
                return output_path
            else:
                return dir_or_file
        else:
            return self.config_data.get("output_prompt_path")

    def get_output_corpus(self):
        return self.config_data.get("output_corpus_path")

    def get_schema_dict_path(self):
        return self.config_data.get("schema_dict_path")

    def get_syn_dict_path(self):
        return self.config_data.get("syn_dict_path")

    def get_db_id(self):
        return self.db_id

    def get_schema_path(self, db_id):
        schema_dict = self.config_data.get("db_schema_path")
        if not schema_dict:
            raise ValueError("配置中缺少 'db_schema_path' 字段")
        if db_id not in schema_dict:
            raise KeyError(f"未找到 db_id '{db_id}' 对应的 schema 路径")
        return schema_dict[db_id]

    def get_config(self, module_name):
        return self.config_data.get(module_name)
