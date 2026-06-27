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
Gremlin查询结构化表示模块。

定义Step和Traversal数据结构，将解析后的Gremlin查询表示为结构化的"配方"对象。
"""

from typing import Any

# 导入将在 Step 参数中存储的结构化表达式类。


class Step:
    """
    Gremlin 遍历中的单个原子操作（一个步骤）。
    例如：.V(), .has('name', 'marko'), .out('knows'), .addV('person')
    """

    def __init__(self, name: str, params: list[Any] | None = None):
        """
        初始化一个 Step 实例。

        Args:
            name (str): Gremlin 步骤的名称，例如 'V', 'has', 'out', 'addV'。
                        应以一致的格式存储（例如，全小写）。
            params (List[Any], optional): 步骤的参数列表。
                                          这是关键字段，可以包含简单值（str, int）
                                          或来自 GremlinExpr 的复杂对象
                                          （例如 Predicate, AnonymousTraversal）。
                                          默认为 None。
        """
        self.name = name
        self.params = params if params is not None else []

    def __repr__(self) -> str:
        """
        提供一个对开发者友好的、该步骤的字符串表示形式。
        """
        # 格式化参数以便阅读。如果参数有自己的 __repr__ 方法，将会被自动调用。
        param_str = ", ".join(map(repr, self.params))
        return f"Step({self.name}, params=[{param_str}])"


class Traversal:
    """
    将整个 Gremlin 遍历表示为一个由 Step 对象组成的序列，捕获输入查询模板的意图和结构。
    """

    def __init__(self):
        """
        初始化一个空的 Traversal 实例。
        """
        self.steps: list[Step] = []

    def add_step(self, step: Step):
        """
        在遍历序列的末尾追加一个 Step。

        Args:
            step (Step): 要添加的 Step 对象。
        """
        self.steps.append(step)

    def __repr__(self) -> str:
        """
        提供一个链式风格、整个遍历的字符串表示形式。
        """
        if not self.steps:
            return "Traversal(empty)"

        # 创建一个类似方法链的表示形式
        step_chain = " -> ".join([step.name for step in self.steps])
        return f"Traversal({step_chain})"


if __name__ == "__main__":
    # 创建Traversal 实例
    traversal = Traversal()
    traversal.add_step(Step("V"))
    traversal.add_step(Step("has", ["name", "marko"]))
    traversal.add_step(Step("out", ["knows"]))
    traversal.add_step(Step("addV", ["person"]))

    print(traversal)
