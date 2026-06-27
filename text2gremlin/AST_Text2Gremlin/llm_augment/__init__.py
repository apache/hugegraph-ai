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
LLM 增强数据生成包

基于大语言模型对 AST 泛化后的 Gremlin 语料进行多阶段增强：
  1. generalize_llm   — 多风格自然语言翻译
  2. migrate_scenario  — 多场景迁移
  3. merge_dataset     — 数据集合并与统计
  4. generate_dpo_data — DPO 偏好数据生成
"""
