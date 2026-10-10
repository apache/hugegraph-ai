# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#     http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Gremlin 安全分类器 — 兼容 wrapper。

.. deprecated::
    实际实现已迁入 gremlin_policy.py。本模块保留公共 API 以兼容现有导入。
    新代码应使用 gremlin_policy.check_gremlin_read() 或 GremlinPolicy.check_read()。

原模块文档：
    不是完整的 Gremlin parser，而是保守的安全门：
    - safe: 明确只读遍历（g.V()/g.E() + 已知只读方法）
    - unsafe: 检测到 write/mutate 方法或模式
    - uncertain: 无法确定 → 拒绝执行

    宁可误拒 ambiguous 查询，也不放行潜在写操作。
"""

# Compatibility imports: re-export the public API from gremlin_policy.
from hugegraph_mcp.gremlin_policy import (  # noqa: F401
    GremlinSafety,
    classify_gremlin_read_safety,
    is_safe_gremlin_read,
)
