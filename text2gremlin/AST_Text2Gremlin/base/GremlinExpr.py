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
Gremlin复杂表达式定义模块。

定义谓词、匿名遍历、连接器等复杂Gremlin表达式的数据结构。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .GremlinParse import Step


class RawGremlinToken:
    def __init__(self, text: str):
        self.text = text

    def __str__(self) -> str:
        return self.text

    def __repr__(self) -> str:
        return self.text


class Predicate:
    """
    表示一个 Gremlin 谓词，例如 P.gt(30)、P.within('a', 'b') 等。
    此类捕获操作符（如 'gt'、'within'）及其参数。
    """

    def __init__(self, operator: str, value: Any):
        """
        参数:
            operator (str): 谓词操作符名称（例如 'gt'、'lt'、'inside'、'neq'）。
            value (Any): 与操作符关联的值。可以是单个值或多个值（例如用于 'within'）。
        """
        self.operator = operator
        self.value = value

    def __repr__(self) -> str:
        return f"P.{self.operator}({self.value!r})"


class TextPredicate:
    """
    表示一个 Gremlin TextP 谓词，例如 TextP.startingWith('mark')。
    这是用于基于文本比较的谓词的专用版本。
    """

    def __init__(self, operator: str, value: Any):
        """
        参数:
            operator (str): 文本谓词操作符名称（例如 'startingWith'、'endingWith'、'containing'）。
            value (Any): 用于比较的字符串值。
        """
        self.operator = operator
        self.value = value

    def __repr__(self) -> str:
        return f"TextP.{self.operator}({self.value!r})"


class AnonymousTraversal:
    """
    表示一个匿名遍历，通常以 __ 开头。
    示例：__.out('knows')，__.values('age').mean()

    该类保存构成遍历的一系列 Step 对象。
    """

    def __init__(self):
        # 构成此匿名遍历的 Step 对象列表。
        # 'Step' 是前向声明，以避免与 GremlinParse 的循环导入。
        self.steps: list[Step] = []

    def add_step(self, step: Step):
        """向匿名遍历中添加一个步骤。"""
        self.steps.append(step)

    def __repr__(self) -> str:
        step_reprs = ".".join(map(repr, self.steps))
        return f"__.{step_reprs}"


class Connector:
    """
    表示用于组合遍历过滤器的逻辑连接符，如 .and() 和 .or()。
    示例：g.V().where(__.out('knows').and().out('likes'))
    """

    def __init__(self, operator: str, traversals: list[AnonymousTraversal]):
        """
        参数:
            operator (str): 逻辑操作符，通常是 'and' 或 'or'。
            traversals (List[AnonymousTraversal]): 需要连接的匿名遍历列表。
        """
        self.operator = operator
        self.traversals = traversals

    def __repr__(self) -> str:
        traversal_reprs = ", ".join(map(repr, self.traversals))
        return f".{self.operator}({traversal_reprs})"


class Terminal:
    """
    表示不返回迭代器的终端步骤，例如 .next()、.hasNext()、.toList()。
    虽然我们的生成器可能不会频繁生成这些步骤，但解析器需要能够识别它们。
    """

    def __init__(self, name: str):
        """
        参数:
            name (str): 终端步骤的名称（例如 'next'、'toList'）。
        """
        self.name = name

    def __repr__(self) -> str:
        return f".{self.name}()"
