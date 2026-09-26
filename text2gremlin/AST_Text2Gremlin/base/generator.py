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
Gremlin语料库生成器主入口脚本。

从Gremlin查询模板生成大量多样化的查询-描述对，用于Text-to-Gremlin任务的训练数据。
"""

import json
import os
from datetime import datetime

from antlr4 import CommonTokenStream, InputStream
from antlr4.error.ErrorListener import ErrorListener

from .Config import Config
from .gremlin.GremlinLexer import GremlinLexer
from .gremlin.GremlinParser import GremlinParser
from .GremlinBase import GremlinBase
from .GremlinTransVisitor import GremlinTransVisitor
from .Schema import Schema
from .TraversalGenerator import TraversalGenerator

LARGE_GENERATION_THRESHOLD = 5000


class SyntaxErrorListener(ErrorListener):
    """私有错误监听器类，捕获语法错误。"""

    def __init__(self):
        super().__init__()
        self.has_error = False
        self.error_message = ""

    def syntaxError(self, recognizer, offendingSymbol, line, column, msg, e):
        """当语法错误发生时，此方法被调用。"""
        self.has_error = True
        self.error_message = f"Syntax Error at line {line}, column {column}: {msg}"


def check_gremlin_syntax(query_string: str) -> tuple[bool, str]:
    """
    检查给定的Gremlin查询语句的语法。

    Args:
        query_string: The Gremlin query to check.

    Returns:
        A tuple containing:
        - bool: True if syntax is correct, False otherwise.
        - str: An error message if syntax is incorrect, or "Syntax OK" if correct.
    """
    try:
        input_stream = InputStream(query_string)
        lexer = GremlinLexer(input_stream)
        token_stream = CommonTokenStream(lexer)
        parser = GremlinParser(token_stream)

        # 移除默认的控制台错误监听器
        lexer.removeErrorListeners()
        parser.removeErrorListeners()

        # 添加自定义的监听器
        error_listener = SyntaxErrorListener()
        lexer.addErrorListener(error_listener)
        parser.addErrorListener(error_listener)

        # 尝试解析查询
        parser.queryList()

        if error_listener.has_error:
            return (False, error_listener.error_message)
        else:
            return (True, "Syntax OK")

    except Exception as e:
        return (False, f"Parser Exception: {e!s}")


def generate_corpus_from_template(
    template_string: str, config: Config, schema: Schema, gremlin_base: GremlinBase, global_corpus_dict: dict
) -> tuple[int, dict]:
    """
    执行单个 Gremlin 模板字符串的完整 pipeline。

    Args:
        template_string: 用作模板的 Gremlin query。
        config: 加载的 Config 对象。
        schema: 加载的 Schema 对象。
        gremlin_base: 加载的 GremlinBase 对象。
        global_corpus_dict: 用于存储唯一 query-payload 对的全局字典。

    Returns:
        tuple: (添加到全局语料库的新的唯一对的数量, 处理统计信息)
    """
    # 初始化统计信息
    stats = {
        "success": False,
        "error_stage": "",
        "error_message": "",
        "generated_count": 0,
        "new_pairs_count": 0,
        "duplicate_count": 0,
        "syntax_error_count": 0,
    }

    try:
        # ANTLR 解析为 AST,并提取模版
        visitor = GremlinTransVisitor()
        recipe = visitor.parse_and_visit(template_string)

        if not recipe:
            stats["error_stage"] = "recipe_extraction"
            stats["error_message"] = "Recipe extraction failed"
            return 0, stats

        if not hasattr(recipe, "steps") or not recipe.steps:
            stats["error_stage"] = "recipe_validation"
            stats["error_message"] = "Recipe has no steps"
            return 0, stats

        # 泛化
        generator = TraversalGenerator(schema, recipe, gremlin_base)
        corpus = generator.generate()

        if not corpus:
            stats["error_stage"] = "generation"
            stats["error_message"] = "Generator returned empty corpus"
            return 0, stats

        sample_payloads = {sample["query"]: sample for sample in generator.generate_samples()}
        stats["generated_count"] = len(corpus)

        # 语法检查 & 全局去重
        new_pairs_count = 0
        duplicate_count = 0
        syntax_error_count = 0

        for query, description in corpus:
            try:
                # 先判重，避免对重复项做语法检查
                if query in global_corpus_dict:
                    duplicate_count += 1
                    continue

                # 再进行语法检查
                is_valid, _error_msg = check_gremlin_syntax(query)

                if not is_valid:
                    syntax_error_count += 1
                    continue

                # 新的查询且语法正确，添加到全局字典
                payload = sample_payloads.get(query, {"query": query, "description": description})
                if payload.get("description") != description:
                    payload = {**payload, "description": description}
                global_corpus_dict[query] = payload
                new_pairs_count += 1

            except Exception:
                syntax_error_count += 1
                continue

        # 更新统计信息
        stats["new_pairs_count"] = new_pairs_count
        stats["duplicate_count"] = duplicate_count
        stats["syntax_error_count"] = syntax_error_count
        stats["success"] = True

        # 添加生成数量的警告信息
        if stats["generated_count"] > LARGE_GENERATION_THRESHOLD:
            stats["warning"] = f"由于本条模版的Recipe复杂,生成了大量查询({stats['generated_count']}条)"
        elif new_pairs_count == 0 and stats["generated_count"] > 0:
            stats["warning"] = f"生成了{stats['generated_count']}条查询但全部重复"

        return new_pairs_count, stats

    except Exception as e:
        # 捕获所有其他异常
        stats["error_stage"] = "unknown"
        stats["error_message"] = str(e)
        return 0, stats


def generate_gremlin_corpus(
    templates: list[str], config_path: str, schema_path: str, data_path: str, output_file: str | None = None
) -> dict:
    """
    从Gremlin模板列表生成完整的语料库。

    查询数量由 combination_control_config.json 中的 max_total_combinations 控制。

    Args:
        templates: Gremlin查询模板列表或CSV文件路径
        config_path: 配置文件路径（必需）
        schema_path: Schema文件路径（必需）
        data_path: 数据文件路径（必需）
        output_file: 输出文件名（可选）

    Returns:
        包含生成统计信息的字典

    Raises:
        FileNotFoundError: 当必需的文件不存在时
        ValueError: 当参数无效时
    """
    # 验证必需参数
    if not config_path or not os.path.exists(config_path):
        raise FileNotFoundError(f"配置文件不存在: {config_path}")
    if not schema_path or not os.path.exists(schema_path):
        raise FileNotFoundError(f"模式文件不存在: {schema_path}")
    if not data_path or not os.path.exists(data_path):
        raise FileNotFoundError(f"数据目录不存在: {data_path}")

    # 处理模板输入
    if isinstance(templates, str) and templates.endswith(".csv"):
        if not os.path.exists(templates):
            raise FileNotFoundError(f"模板文件不存在: {templates}")
        # 从CSV文件读取模板
        import csv

        template_list = []
        with open(templates, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if "gremlin_query" in row:
                    template_list.append(row["gremlin_query"])
                elif "template" in row:
                    template_list.append(row["template"])
        templates = template_list

    if not templates:
        raise ValueError("没有找到有效的模板")

    # Load all necessary components once
    config = Config(file_path=config_path)
    schema = Schema(schema_path, data_path)
    gremlin_base = GremlinBase(config)

    # --- Run the generation process for each template with global deduplication ---
    global_corpus_dict = {}  # 使用字典进行去重，key是query，value是payload dict
    total_new_pairs = 0

    # 处理统计信息
    processing_stats = {
        "total_templates": len(templates),
        "successful_templates": 0,
        "failed_templates": 0,
        "failed_details": [],
        "total_generated": 0,
        "total_syntax_errors": 0,
        "total_duplicates": 0,
    }

    print(f"🚀 开始处理 {len(templates)} 个模板...")

    for i, template in enumerate(templates, 1):
        try:
            new_pairs_count, template_stats = generate_corpus_from_template(
                template_string=template,
                config=config,
                schema=schema,
                gremlin_base=gremlin_base,
                global_corpus_dict=global_corpus_dict,
            )

            total_new_pairs += new_pairs_count

            # 更新统计信息
            if template_stats["success"]:
                processing_stats["successful_templates"] += 1
                processing_stats["total_generated"] += template_stats["generated_count"]
                processing_stats["total_syntax_errors"] += template_stats["syntax_error_count"]
                processing_stats["total_duplicates"] += template_stats["duplicate_count"]

                # 根据情况显示不同的消息
                if new_pairs_count == 0 and template_stats["generated_count"] > 0:
                    print(f"[{i}/{len(templates)}] ⚠️  生成 {template_stats['generated_count']} 条查询但全部重复")
                elif template_stats["generated_count"] > LARGE_GENERATION_THRESHOLD:
                    print(
                        f"[{i}/{len(templates)}] ⚡ 大量生成 {new_pairs_count} 条新查询 (总生成{template_stats['generated_count']}条)"
                    )
                else:
                    print(f"[{i}/{len(templates)}] ✅ 成功生成 {new_pairs_count} 条新查询")
            else:
                processing_stats["failed_templates"] += 1
                processing_stats["failed_details"].append(
                    {
                        "template_index": i,
                        "template": template[:100] + "..." if len(template) > 100 else template,
                        "error_stage": template_stats["error_stage"],
                        "error_message": template_stats["error_message"],
                    }
                )
                print(f"[{i}/{len(templates)}] ❌ 处理失败: {template_stats['error_message']}")

        except Exception as e:
            # 处理单个模板时的意外错误
            processing_stats["failed_templates"] += 1
            processing_stats["failed_details"].append(
                {
                    "template_index": i,
                    "template": template[:100] + "..." if len(template) > 100 else template,
                    "error_stage": "unexpected_error",
                    "error_message": str(e),
                }
            )
            print(f"[{i}/{len(templates)}] ❌ 意外错误: {e!s}")
            continue  # 继续处理下一个模板

    # 转换为列表格式以便后续处理；返回值继续保持旧的 (query, description) tuple list
    full_corpus_payloads = list(global_corpus_dict.values())
    full_corpus = [(payload["query"], payload["description"]) for payload in full_corpus_payloads]

    # --- Save the full corpus to a local file (if output_file is provided) ---
    if output_file:
        # 确保输出目录存在
        out_dir = os.path.dirname(os.path.abspath(output_file))
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        # 确保只保存成功生成的查询-描述对
        corpus_data = {
            "metadata": {
                "total_templates": len(templates),
                "successful_templates": processing_stats["successful_templates"],
                "failed_templates": processing_stats["failed_templates"],
                "total_unique_queries": len(full_corpus),
                "generation_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
            "corpus": full_corpus_payloads,
        }

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(corpus_data, f, ensure_ascii=False, indent=2)

    # --- Generate statistics and display results ---
    stats = _generate_statistics(templates, full_corpus, output_file)
    stats.update(
        {
            "total_templates": len(templates),
            "successful_templates": processing_stats["successful_templates"],
            "failed_templates": processing_stats["failed_templates"],
        }
    )

    if output_file:
        stats["output_file"] = output_file

    _display_final_results(full_corpus, stats)

    result = {
        "total_templates": len(templates),
        "successful_templates": processing_stats["successful_templates"],
        "failed_templates": processing_stats["failed_templates"],
        "total_unique_queries": len(full_corpus),
        "statistics": stats,
        "queries": full_corpus,
    }

    if output_file:
        result["output_file"] = output_file

    return result


def _generate_statistics(templates: list, full_corpus: list, output_file: str) -> dict:
    """生成统计信息"""
    # 按查询长度分类统计
    length_stats = {}
    for query, _ in full_corpus:
        steps = query.count(".")
        length_stats[steps] = length_stats.get(steps, 0) + 1

    # 按操作类型分类统计
    operation_stats = {"查询(V/E)": 0, "创建(addV/addE)": 0, "更新(property)": 0, "删除(drop)": 0}

    for query, _ in full_corpus:
        if query.startswith("g.V(") or query.startswith("g.E("):
            if ".drop()" in query:
                operation_stats["删除(drop)"] += 1
            elif ".property(" in query:
                operation_stats["更新(property)"] += 1
            else:
                operation_stats["查询(V/E)"] += 1
        elif ".addV(" in query or ".addE(" in query:
            operation_stats["创建(addV/addE)"] += 1

    return {
        "length_stats": length_stats,
        "operation_stats": operation_stats,
        "avg_per_template": len(full_corpus) / len(templates) if templates else 0,
    }


def _display_final_results(full_corpus: list, stats: dict):
    """显示最终生成结果和统计信息"""
    print(f"\n{'=' * 50}")
    print("📊 生成完成统计")
    print(f"{'=' * 50}")
    print(f"处理的模板数量: {stats.get('total_templates', 0)}")
    print(f"成功处理: {stats.get('successful_templates', 0)}")
    print(f"处理失败: {stats.get('failed_templates', 0)}")
    print(f"生成的独特查询数量: {len(full_corpus)}")

    if "output_file" in stats:
        print(f"语料库已保存到: {stats['output_file']}")
    else:
        print("语料库未保存到文件（仅返回结果）")

    # 按查询长度分类统计
    print(f"\n{'=' * 50}")
    print("📈 查询复杂度分析:")
    print(f"{'=' * 50}")

    for steps in sorted(stats["length_stats"].keys()):
        print(f"  {steps}步查询: {stats['length_stats'][steps]} 个")

    # 按操作类型分类统计
    print(f"\n{'=' * 50}")
    print("🔍 操作类型分析:")
    print(f"{'=' * 50}")

    for op_type, count in stats["operation_stats"].items():
        percentage = (count / len(full_corpus)) * 100 if full_corpus else 0
        print(f"  {op_type}: {count} 个 ({percentage:.1f}%)")

    print(f"\n{'=' * 50}")
    print(f"✅ 生成完成！共生成 {len(full_corpus)} 个独特查询")
    print(f"{'=' * 50}")
