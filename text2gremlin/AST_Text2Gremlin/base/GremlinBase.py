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
Gremlin翻译引擎模块。

提供Gremlin术语到中文的智能翻译，负责生成自然流畅的中文查询描述。
"""

import os
import random

from .gremlin.GremlinParser import GremlinParser

TOKEN_TEMPLATE_ALIASES = {
    "V": "v",
    "E": "e",
    "addV": "addv",
    "addE": "adde",
    "toList": "tolist",
    "toSet": "toset",
    "hasNext": "hasnext",
    "tryNext": "trynext",
}


class GremlinBase:
    def __init__(self, config):
        """
        Gremlin 基础类，作为项目的“工具箱”和“字典”。
        """
        self.config = config

        # 从 GremlinParser 加载rule_names
        self.rule_names = GremlinParser.ruleNames

        self.token_dict = {}
        self.template = []  # 索引对应 token_dict 的值，每个元素是一个包含多种中文翻译模板的子列表。
        self._initialize_translation_templates()

        # 复用 schema_dict 加载同义词等
        self.schema_dict = {}
        self._load_schema_translations()

    def get_rule_name(self, rule_index: int) -> str:
        """根据索引获取 ANTLR 规则名。"""
        if 0 <= rule_index < len(self.rule_names):
            return self.rule_names[rule_index]
        return "UnknownRule"

    def _load_schema_translations(self):
        """加载schema翻译字典"""
        current_dir = os.path.dirname(os.path.abspath(__file__))

        def collect_config_paths(method_name: str) -> list[str]:
            if not hasattr(self.config, method_name):
                return []
            try:
                configured_paths = getattr(self.config, method_name)()
            except Exception as e:
                print(f"[INFO] Config path {method_name} not available: {e}")
                return []
            if isinstance(configured_paths, list):
                return configured_paths
            if isinstance(configured_paths, str):
                return [configured_paths]
            return []

        def existing_or_default(configured_paths: list[str], default_filename: str) -> list[str]:
            existing_paths = [path for path in configured_paths if os.path.exists(path)]
            if existing_paths:
                return existing_paths
            default_path = os.path.join(current_dir, "template", default_filename)
            if os.path.exists(default_path):
                return [default_path]
            return []

        schema_paths = existing_or_default(collect_config_paths("get_schema_dict_path"), "schema_dict.txt")
        syn_paths = existing_or_default(collect_config_paths("get_syn_dict_path"), "syn_dict.txt")
        existing_paths = schema_paths + syn_paths

        if existing_paths:
            self.load_dict_from_file(existing_paths)
        else:
            print("[WARNING] No dictionary files found")

    def _initialize_translation_templates(self):
        """
        初始化 Gremlin 步骤的翻译模板。
        """
        # 定义模板数据
        templates_data = {
            # --- 起始步骤 ---
            "v": ["查询图中的所有顶点", "获取所有节点"],
            "e": ["查询图中的所有边", "获取所有关系"],
            "addv": ["添加一个标签为 '{}' 的新顶点"],
            "adde": ["添加一条从一个顶点到另一个顶点的 '{}' 边"],
            # --- 导航步骤 ---
            "out": ["从当前位置出发，沿着 '{}' 方向的出边前进", "找到 '{}' 类型的邻居"],
            "in": ["从当前位置出发，沿着 '{}' 方向的入边前进", "找到拥有 '{}' 类型关系的来源"],
            "both": ["沿着 '{}' 方向的双向边进行遍历"],
            "outE": ["获取出边"],
            "inE": ["获取入边"],
            "bothE": ["获取双向边"],
            "outV": ["从当前边，找到它的出射顶点", "获取边的头节点"],
            "inV": ["从当前边，找到它的入射顶点", "获取边的尾节点"],
            "otherV": ["获取边的另一端顶点"],
            "bothV": ["从当前边，找到它的两个端点"],
            # --- 过滤步骤 ---
            "hasLabel": ["并筛选出标签为 '{}' 的元素"],
            "has": ["并筛选出属性 '{}' 为 '{}' 的元素", "查找其中 '{}' 是 '{}' 的数据"],
            "hasId": ["筛选ID为 '{}' 的元素"],
            "hasKey": ["筛选包含键 '{}' 的元素"],
            "hasValue": ["筛选包含值 '{}' 的元素"],
            "where": ["并根据 '{}' 的条件进行过滤"],
            "is": ["判断值是否为 '{}'"],
            "not": ["取反"],
            # --- 数值参数步骤 ---
            "limit": ["并限制最多返回 {} 个结果", "取前 {} 条数据"],
            "skip": ["跳过前 {} 个结果"],
            "tail": ["取最后 {} 个结果"],
            "sample": ["随机采样 {} 个结果"],
            "range": ["取范围内的结果"],
            # --- 转换步骤 ---
            "dedup": ["并对结果进行去重"],
            "order": ["然后对结果进行排序"],
            "simplePath": ["过滤出简单路径"],
            "cyclicPath": ["过滤出循环路径"],
            # --- 属性访问步骤 ---
            "values": ["然后获取它们的属性值", "提取属性值"],  # 无参数版本
            "values_with_key": ["然后获取它们的 '{}' 属性值", "提取 '{}' 字段的值"],  # 有参数版本
            "properties": ["获取属性对象"],
            "properties_with_key": ["获取 '{}' 属性对象"],  # 有参数版本
            "valueMap": ["然后以键值对的形式返回它们的属性"],
            "valueMap_with_key": ["返回 '{}' 的键值对"],  # 有参数版本
            "elementMap": ["获取元素映射"],
            "keys": ["获取键"],
            "key": ["获取键"],
            "value": ["获取属性的值"],
            # --- 聚合步骤 ---
            "count": ["最后统计结果的总数"],
            "group": ["然后对结果进行分组"],
            "groupCount": ["分组并统计数量"],
            "sum": ["求和"],
            "mean": ["求平均值"],
            "min": ["求最小值"],
            "max": ["求最大值"],
            # --- 终端步骤 ---
            "tolist": ["转为列表"],
            "toset": ["转为集合"],
            "next": ["获取下一个"],
            "hasnext": ["判断是否有下一个"],
            "trynext": ["尝试获取下一个"],
            # --- 简单步骤 ---
            "fold": ["折叠为列表"],
            "unfold": ["展开列表"],
            "iterate": ["迭代执行"],
            "explain": ["解释查询计划"],
            "profile": ["性能分析"],
            # --- 其他步骤 ---
            "label": ["然后获取它们的标签"],
            "id": ["然后获取它们的ID"],
            "path": ["然后返回完整的遍历路径"],
            "project": ["然后将结果投影为指定字段"],
            "by": ["按指定属性进行分组或投影"],
            "property": ["并将其 '{}' 属性的值更新为 '{}'"],
            "drop": ["最后将这些元素从图中删除", "移除这些数据"],
            "as": ["标记为 '{}'", "标记"],
            "select": ["选择标记的元素"],
            "repeat": ["重复遍历"],
            "until": ["直到满足条件"],
            "times": ["重复指定次数"],
            "emit": ["发射中间结果"],
            "choose": ["条件分支"],
            "coalesce": ["合并多个遍历"],
            "optional": ["可选遍历"],
            "union": ["联合多个遍历"],
            "match": ["模式匹配"],
            "flatMap": ["扁平映射"],
            "map": ["映射转换"],
            "tree": ["构建树结构"],
            # --- 新增步骤 ---
            "loops": ["获取当前循环的次数"],
            "coin": ["以 {} 的概率保留结果"],
            "filter": ["应用过滤条件"],
            "and": ["应用逻辑与过滤"],
            "or": ["应用逻辑或过滤"],
            "aggregate": ["将它们聚合到名为 '{}' 的侧边变量中"],
            "store": ["将它们存储到名为 '{}' 的侧边变量中"],
            "sideEffect": ["执行附加操作"],
            "cap": ["然后取出 '{}' 中存储的内容"],
            "sack": ["获取携带的值"],
            "barrier": ["等待所有结果到齐"],
            "constant": ["映射为常量值"],
            "identity": ["保持元素不变"],
            "local": ["在本地作用域内执行"],
            # --- 剩余15个步骤 ---
            # 图算法
            "pageRank": ["计算PageRank值"],
            "peerPressure": ["应用同伴压力算法"],
            "connectedComponent": ["计算连通分量"],
            "shortestPath": ["计算最短路径"],
            # 工具步骤
            "math": ["应用数学表达式"],
            "subgraph": ["提取子图"],
            "timeLimit": ["设置时间限制"],
            "inject": ["注入值到遍历"],
            "call": ["调用服务"],
            "io": ["执行IO操作"],
            "mergeE": ["合并边"],
            "mergeV": ["合并顶点"],
            "with": ["配置选项"],
            # 边修改
            "from": ["指定边的起始顶点"],
            "to": ["指定边的目标顶点"],
            # --- 谓词 ---
            # 数值谓词
            "eq": ["等于"],
            "neq": ["不等于"],
            "gt": ["大于"],
            "gte": ["大于等于"],
            "lt": ["小于"],
            "lte": ["小于等于"],
            "between": ["在...之间"],
            "inside": ["在范围内"],
            "outside": ["在范围外"],
            "within": ["在集合中"],
            "without": ["不在集合中"],
            # 文本谓词
            "startingWith": ["以...开始"],
            "endingWith": ["以...结束"],
            "containing": ["包含"],
            "notStartingWith": ["不以...开始"],
            "notEndingWith": ["不以...结束"],
            "notContaining": ["不包含"],
            "regex": ["匹配正则表达式"],
            "notRegex": ["不匹配正则表达式"],
        }

        # 填充 self.token_dict 和 self.template
        # 保持原始大小写，不进行转换
        for index, (key, value) in enumerate(templates_data.items()):
            self.token_dict[key] = index
            self.template.append(value)
        for alias, canonical_key in TOKEN_TEMPLATE_ALIASES.items():
            self.token_dict[alias] = self.token_dict[canonical_key]

    def get_token_desc(self, token_key: str, *args) -> str:
        """
        根据 token 和参数获取一个随机的、格式化后的中文描述。
        """
        key = token_key  # 保持原始大小写
        if key in self.token_dict:
            index = self.token_dict[key]
            # 随机选择一个模板
            selected_template = random.choice(self.template[index])
            try:
                # 翻译参数中的schema术语
                translated_args = []
                for arg in args:
                    if isinstance(arg, str):
                        # 尝试翻译schema术语
                        translated_arg = self.get_schema_desc(arg)
                        translated_args.append(translated_arg)
                    else:
                        translated_args.append(arg)

                # 使用翻译后的参数格式化模板
                return selected_template.format(*translated_args)
            except (IndexError, KeyError):
                # 如果参数数量不匹配，返回原始模板
                return selected_template
        return ""  # 如果 token 不存在，返回空字符串

    # 复用的通用方法
    def merge_desc(self, desc_list: list) -> str:
        """合并多个描述片段，移除空字符串并用合适的连接词连接。"""
        # 过滤掉空字符串
        filtered_list = [s for s in desc_list if s and s.strip()]
        return ",".join(filtered_list)

    def load_dict_from_file(self, file_paths: list):
        """从文件加载字典，例如同义词词典。"""
        for file_path in file_paths:
            if not os.path.exists(file_path):
                print(f"[WARNING] Dictionary file not found: {file_path}")
                continue
            with open(file_path, encoding="utf-8") as file:
                for line in file:
                    elements = line.strip().split()
                    if elements:
                        key = elements[0]
                        values = elements[1:]
                        self.schema_dict[key] = values

    def get_schema_desc(self, key: str) -> str:
        """从加载的字典中获取一个随机的同义词或描述。"""
        try:
            # 确保键存在
            if self.schema_dict.get(key):
                return random.choice(self.schema_dict[key])
            return key  # 如果没有同义词，返回原词
        except KeyError:
            return key


if __name__ == "__main__":
    # 临时创建config 对象，用于测试
    class MockConfig:
        def get_schema_dict_path(self):
            return ["./template/schema_dict.txt"]

        def get_syn_dict_path(self):
            return ["./template/syn_dict.txt"]

    config = MockConfig()
    gremlin_base = GremlinBase(config)

    print("--- GremlinBase.py 测试 ---")

    # 1. 测试规则名加载
    print(f"\n成功加载 {len(gremlin_base.rule_names)} 条 Gremlin 语法规则。")
    print(f"第一条规则是: '{gremlin_base.get_rule_name(0)}'")

    # 2. 测试翻译模板
    print("\n--- 测试翻译功能 ---")
    print("OUT('acted_in') 的一个翻译: ", gremlin_base.get_token_desc("OUT", "acted_in"))
    print("HAS('name', 'marko') 的一个翻译: ", gremlin_base.get_token_desc("HAS", "name", "marko"))
    print("LIMIT(10) 的一个翻译: ", gremlin_base.get_token_desc("LIMIT", 10))
    print("COUNT() 的一个翻译: ", gremlin_base.get_token_desc("COUNT"))

    # 3. 测试描述合并
    desc_parts = ["查找所有电影", "筛选出其中类型为科幻的", "最后统计总数"]
    merged = gremlin_base.merge_desc(desc_parts)
    print("\n合并后的描述: ", merged)
