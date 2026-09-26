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
图数据库Schema管理模块。

负责解析Schema定义和CSV数据文件，为查询生成器提供图结构信息和真实数据实例。
"""

import json
import os
import random
from typing import Any

import pandas as pd

DEFAULT_SAMPLE_MIN = 2
DEFAULT_SAMPLE_MAX = 5


class Schema:
    def __init__(self, schema_file: str, data_dir: str):
        self.data_dir = data_dir
        self.vertices: dict[str, dict[str, Any]] = {}
        self.edges: dict[str, dict[str, Any]] = {}
        self.vertex_data: dict[str, pd.DataFrame] = {}
        self.edge_data: dict[str, pd.DataFrame] = {}

        with open(schema_file, encoding="utf-8") as f:
            schema_data = json.load(f)

        # 解析 schema 定义
        for item in schema_data.get("schema", []):
            label = item["label"]
            if item["type"] == "VERTEX":
                self.vertices[label] = {
                    "primary": item.get("primary", None),
                    "properties": {
                        prop["name"]: {"type": prop["type"], "optional": prop.get("optional", False)}
                        for prop in item.get("properties", [])
                    },
                }
            elif item["type"] == "EDGE":
                self.edges[label] = {
                    "source": None,
                    "destination": None,
                    "properties": {
                        prop["name"]: {"type": prop["type"], "optional": prop.get("optional", False)}
                        for prop in item.get("properties", [])
                    },
                }

        # 2. 解析 files 定义，获取路径、header行数和边的端点
        self.vertex_files: dict[str, dict] = {}
        self.edge_files: dict[str, dict] = {}
        for file_info in schema_data.get("files", []):
            label = file_info["label"]
            path = os.path.join(self.data_dir, file_info["path"])
            header_rows = file_info.get("header", 1)  # 获取header行数，默认为1

            file_details = {"path": path, "header_rows": header_rows}

            is_edge = "SRC_ID" in file_info and "DST_ID" in file_info
            if is_edge:
                self.edge_files[label] = file_details
                if label in self.edges:
                    self.edges[label]["source"] = file_info["SRC_ID"]
                    self.edges[label]["destination"] = file_info["DST_ID"]
            else:
                self.vertex_files[label] = file_details

    def _parse_custom_csv(self, file_path: str, header_line_index: int) -> pd.DataFrame:
        """解析自定义多行表头的 CSV 文件。"""
        try:
            with open(file_path, encoding="utf-8") as f:
                lines = f.readlines()

            # 从第二行解析列名
            header_line = lines[header_line_index - 1]
            column_defs = header_line.strip().split(",")
            column_names = [d.split(":")[0] for d in column_defs]

            # 处理重复的列名（为重复的列添加后缀）
            seen = {}
            unique_names = []
            for name in column_names:
                if name in seen:
                    seen[name] += 1
                    unique_names.append(f"{name}_{seen[name]}")
                else:
                    seen[name] = 0
                    unique_names.append(name)
            column_names = unique_names

            # 从指定header行之后开始读取数据
            data_lines = lines[header_line_index:]

            if not data_lines:
                return pd.DataFrame(columns=column_names)

            # 使用pandas从内存中的字符串列表读取数据
            from io import StringIO

            csv_data = StringIO("".join(data_lines))
            df = pd.read_csv(csv_data, header=None, names=column_names)
            return df

        except (FileNotFoundError, IndexError) as e:
            print(f"警告: 读取或解析文件失败: {file_path}, 错误: {e}")
            return pd.DataFrame()

    def _load_vertex_data(self, label: str):
        if label not in self.vertex_data and label in self.vertex_files:
            file_info = self.vertex_files[label]
            self.vertex_data[label] = self._parse_custom_csv(file_info["path"], file_info["header_rows"])

    def _load_edge_data(self, label: str):
        if label not in self.edge_data and label in self.edge_files:
            file_info = self.edge_files[label]
            self.edge_data[label] = self._parse_custom_csv(file_info["path"], file_info["header_rows"])

    # --- Schema 查询方法 (保持不变) ---
    def get_vertex_labels(self) -> list[str]:
        return list(self.vertices.keys())

    def get_edge_labels(self) -> list[str]:
        return list(self.edges.keys())

    def get_properties_with_type(self, label: str) -> list[dict[str, str]]:
        props_dict = self.vertices.get(label, {}).get("properties", {}) or self.edges.get(label, {}).get(
            "properties", {}
        )
        return [{"name": name, "type": meta["type"]} for name, meta in props_dict.items()]

    def get_valid_steps(self, current_label: str, element_type: str = "vertex") -> list[dict]:
        if element_type == "vertex":
            if current_label not in self.vertices:
                return []
            valid_steps = []
            outgoing = [l for l, e in self.edges.items() if e["source"] == current_label]
            if outgoing:
                valid_steps.append({"step": "out", "params": outgoing})
            incoming = [l for l, e in self.edges.items() if e["destination"] == current_label]
            if incoming:
                valid_steps.append({"step": "in", "params": incoming})
            props = self.get_properties_with_type(current_label)
            if props:
                valid_steps.append({"step": "properties", "params": [p["name"] for p in props]})
                valid_steps.append({"step": "has", "params": props})
            return valid_steps
        return []

    def get_step_result_label(self, start_label: str, step: dict) -> tuple[str, str]:
        step_name, step_param = step.get("step"), step.get("param")
        if step_name == "out":
            if step_param not in self.edges:
                raise KeyError(f"边标签 '{step_param}' 不存在于 schema 中")
            return self.edges[step_param]["destination"], "vertex"
        if step_name == "in":
            if step_param not in self.edges:
                raise KeyError(f"边标签 '{step_param}' 不存在于 schema 中")
            return self.edges[step_param]["source"], "vertex"
        if step_name in ["properties", "has", "values"]:
            return start_label, "vertex"
        return None, None

    def get_vertex_creation_info(self, label: str) -> dict:
        if label not in self.vertices:
            return {}
        schema_info = self.vertices[label]
        required = [name for name, meta in schema_info["properties"].items() if not meta["optional"]]
        return {"primary": schema_info.get("primary"), "required": required}

    def get_edge_creation_info(self, label: str) -> tuple[str, str]:
        if label in self.edges:
            return (self.edges[label]["source"], self.edges[label]["destination"])
        return (None, None)

    def get_updatable_properties(self, label: str) -> list[dict[str, str]]:
        if label not in self.vertices:
            return []
        schema_info = self.vertices[label]
        primary_key = schema_info.get("primary")
        return [
            {"name": name, "type": meta["type"]}
            for name, meta in schema_info["properties"].items()
            if name != primary_key
        ]

    def get_instance(self, label: str) -> dict:
        """获取单个实例（保持向后兼容）"""
        instances = self.get_instances(label, count=1)
        return instances[0] if instances else {}

    def get_instances(self, label: str, count: int | None = None) -> list[dict]:
        """获取多个实例

        Args:
            label: 标签名
            count: 要获取的实例数量，如果为None则随机选择2-5个

        Returns:
            实例列表
        """

        is_edge = label in self.edges
        data_cache = self.edge_data if is_edge else self.vertex_data
        load_func = self._load_edge_data if is_edge else self._load_vertex_data

        if label not in data_cache:
            load_func(label)

        df = data_cache.get(label)
        if df is None or df.empty:
            return []

        # 如果没有指定数量，使用默认随机样本范围
        if count is None:
            count = random.randint(DEFAULT_SAMPLE_MIN, DEFAULT_SAMPLE_MAX)

        # 如果实际数据量小于要求的数量，就全部取出
        actual_count = min(count, len(df))

        # 随机采样
        sampled_df = df.sample(actual_count)
        return sampled_df.to_dict("records")
