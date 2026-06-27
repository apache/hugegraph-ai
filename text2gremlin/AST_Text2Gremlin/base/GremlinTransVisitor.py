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
Gremlin查询AST访问器模块。

基于ANTLR访问器模式，将Gremlin查询字符串解析为结构化的配方对象。
"""

from antlr4 import *
from antlr4.CommonTokenStream import CommonTokenStream
from antlr4.InputStream import InputStream

from .gremlin.GremlinLexer import GremlinLexer
from .gremlin.GremlinParser import GremlinParser
from .gremlin.GremlinVisitor import GremlinVisitor
from .GremlinExpr import AnonymousTraversal, Predicate, RawGremlinToken, Terminal, TextPredicate
from .GremlinParse import Step, Traversal


class GremlinTransVisitor(GremlinVisitor):
    def __init__(self):
        super().__init__()
        self.traversal = Traversal()

    def parse_and_visit(self, query_string: str):
        """
        解析 Gremlin 查询字符串并遍历 AST 以生成 Traversal 对象。

        Args:
            query_string (str): 要解析的 Gremlin 查询字符串

        Returns:
            Traversal: 包含步骤的解析后遍历对象
        """
        try:
            # 重置traversal进行新的查询
            self.traversal = Traversal()

            input_stream = InputStream(query_string)
            lexer = GremlinLexer(input_stream)
            stream = CommonTokenStream(lexer)
            parser = GremlinParser(stream)
            tree = parser.queryList()

            # 访问第一个query
            result = self.visit(tree.query(0))

            return result if result else self.traversal

        except Exception as e:
            print(f"Error parsing query '{query_string}': {e}")
            return None

    # 核心结构访问器，控制流程
    def visitQueryList(self, ctx: GremlinParser.QueryListContext):
        """处理查询列表，通常包含一个查询"""
        if ctx.query(0):  # 访问第一个查询
            return self.visit(ctx.query(0))
        return self.traversal

    def visitQuery(self, ctx: GremlinParser.QueryContext):
        # 访问根遍历部分
        if ctx.rootTraversal():
            self.visit(ctx.rootTraversal())

        # 如果有终端方法，访问它
        if ctx.traversalTerminalMethod():
            self.visit(ctx.traversalTerminalMethod())

        # 如果有嵌套查询，递归访问
        if ctx.query():
            self.visit(ctx.query())
        return self.traversal

    def visitRootTraversal(self, ctx: GremlinParser.RootTraversalContext):
        # 首先访问traversalSource
        if ctx.traversalSource():
            self.visit(ctx.traversalSource())

        # 访问起始步骤，例如 g.V() 或 g.addV()
        if ctx.traversalSourceSpawnMethod():
            self.visit(ctx.traversalSourceSpawnMethod())

        # 如果后面跟着链式调用，访问它们
        if ctx.chainedTraversal():
            self.visit(ctx.chainedTraversal())

    def visitTraversalSource(self, ctx: GremlinParser.TraversalSourceContext):
        """访问traversalSource，处理配置方法如with"""
        # 递归访问嵌套的traversalSource
        if ctx.traversalSource():
            self.visit(ctx.traversalSource())

        # 访问selfMethod（如with）
        if ctx.traversalSourceSelfMethod():
            self.visit(ctx.traversalSourceSelfMethod())

    def visitChainedTraversal(self, ctx: GremlinParser.ChainedTraversalContext):
        # 对于 a.b.c 这样的链，递归访问 a，然后访问 b
        if ctx.chainedTraversal():
            self.visit(ctx.chainedTraversal())
        if ctx.traversalMethod():
            self.visit(ctx.traversalMethod())

    # 动作类访问器 (添加 Step)
    def visitTraversalSourceSpawnMethod_V(self, ctx: GremlinParser.TraversalSourceSpawnMethod_VContext):
        params = self.visit(ctx.genericArgumentVarargs()) if ctx.genericArgumentVarargs() else []
        self.traversal.add_step(Step("V", params))

    def visitTraversalSourceSpawnMethod_addV(self, ctx: GremlinParser.TraversalSourceSpawnMethod_addVContext):
        params = []
        if ctx.stringArgument():
            params.append(self.visit(ctx.stringArgument()))
        self.traversal.add_step(Step("addV", params))

    def visitTraversalMethod_out(self, ctx: GremlinParser.TraversalMethod_outContext):
        params = []
        varargs_ctx = ctx.stringNullableArgumentVarargs()
        if varargs_ctx:
            result = self.visit(varargs_ctx)
            if result is not None:
                params = result
        self.traversal.add_step(Step("out", params))

    def visitTraversalMethod_limit_long(self, ctx: GremlinParser.TraversalMethod_limit_longContext):
        limit_val = self.visit(ctx.integerArgument())
        self.traversal.add_step(Step("limit", [limit_val]))

    def visitTraversalMethod_has_String_Object(self, ctx):
        key = self.visit(ctx.stringNullableLiteral())
        value = self.visit(ctx.genericArgument())
        self.traversal.add_step(Step("has", [key, value]))

    def visitTraversalMethod_has_String_P(self, ctx):
        key = self.visit(ctx.stringNullableLiteral())
        predicate = self.visit(ctx.traversalPredicate())
        self.traversal.add_step(Step("has", [key, predicate]))

    def visitTraversalMethod_has_String_String_Object(self, ctx):
        label = self.visit(ctx.stringNullableArgument())
        key = self.visit(ctx.stringNullableLiteral())
        value = self.visit(ctx.genericArgument())
        self.traversal.add_step(Step("has", [label, key, value]))

    def visitTraversalMethod_has_String(self, ctx):
        key = self.visit(ctx.stringNullableLiteral())
        self.traversal.add_step(Step("has", [key]))

    def visitTraversalMethod_has_String_String_P(self, ctx):
        label = self.visit(ctx.stringNullableArgument())
        key = self.visit(ctx.stringNullableLiteral())
        predicate = self.visit(ctx.traversalPredicate())
        self.traversal.add_step(Step("has", [label, key, predicate]))

    def visitTraversalMethod_has_String_Traversal(self, ctx):
        key = self.visit(ctx.stringNullableLiteral())
        traversal = self.visit(ctx.nestedTraversal())
        self.traversal.add_step(Step("has", [key, traversal]))

    def visitTraversalMethod_has_T_Object(self, ctx):
        t_value = self.visit(ctx.traversalT())
        obj_value = self.visit(ctx.genericArgument())
        self.traversal.add_step(Step("has", [t_value, obj_value]))

    def visitTraversalMethod_has_T_P(self, ctx):
        t_value = self.visit(ctx.traversalT())
        predicate = self.visit(ctx.traversalPredicate())
        self.traversal.add_step(Step("has", [t_value, predicate]))

    def visitTraversalMethod_has_T_Traversal(self, ctx):
        t_value = self.visit(ctx.traversalT())
        traversal = self.visit(ctx.nestedTraversal())
        self.traversal.add_step(Step("has", [t_value, traversal]))

    def visitTraversalMethod_property_Object_Object_Object(self, ctx):
        """处理property(key, value, ...)方法"""
        params = []
        if ctx.genericArgument(0):
            params.append(self.visit(ctx.genericArgument(0)))
        if ctx.genericArgument(1):
            params.append(self.visit(ctx.genericArgument(1)))
        # 处理可选的额外参数
        if hasattr(ctx, "genericArgumentVarargs") and ctx.genericArgumentVarargs():
            varargs = self.visit(ctx.genericArgumentVarargs())
            if varargs:
                params.extend(varargs)
        self.traversal.add_step(Step("property", params))

    def visitTraversalMethod_property_Object(self, ctx):
        """处理property(map)方法"""
        params = []
        if hasattr(ctx, "genericMapNullableArgument") and ctx.genericMapNullableArgument():
            params.append(self.visit(ctx.genericMapNullableArgument()))
        self.traversal.add_step(Step("property", params))

    def visitTraversalMethod_property_Cardinality_Object_Object_Object(self, ctx):
        """处理property(cardinality, key, value, ...)方法"""
        params = []
        if hasattr(ctx, "traversalCardinality") and ctx.traversalCardinality():
            params.append(self.visit(ctx.traversalCardinality()))
        if ctx.genericArgument(0):
            params.append(self.visit(ctx.genericArgument(0)))
        if ctx.genericArgument(1):
            params.append(self.visit(ctx.genericArgument(1)))
        # 处理可选的额外参数
        if hasattr(ctx, "genericArgumentVarargs") and ctx.genericArgumentVarargs():
            varargs = self.visit(ctx.genericArgumentVarargs())
            if varargs:
                params.extend(varargs)
        self.traversal.add_step(Step("property", params))

    def visitTraversalMethod_property_Cardinality_Object(self, ctx):
        """处理property(cardinality, map)方法"""
        params = []
        if hasattr(ctx, "traversalCardinality") and ctx.traversalCardinality():
            params.append(self.visit(ctx.traversalCardinality()))
        if hasattr(ctx, "genericMapNullableArgument") and ctx.genericMapNullableArgument():
            params.append(self.visit(ctx.genericMapNullableArgument()))
        self.traversal.add_step(Step("property", params))

    def visitTraversalCardinality(self, ctx):
        """处理traversalCardinality"""
        # traversalCardinality包含类型和值，例如: Cardinality.list('multi')
        text = ctx.getText()
        # 提取cardinality类型
        if "list" in text.lower():
            card_type = "list"
        elif "set" in text.lower():
            card_type = "set"
        elif "single" in text.lower():
            card_type = "single"
        else:
            card_type = text

        # 提取值（如果有genericLiteral）
        if hasattr(ctx, "genericLiteral") and ctx.genericLiteral():
            value = self.visit(ctx.genericLiteral())
            return {"type": card_type, "value": value}
        else:
            return card_type

    def visitTraversalMethod_values(self, ctx: GremlinParser.TraversalMethod_valuesContext):
        params = self.visit(ctx.stringNullableLiteralVarargs()) if ctx.stringNullableLiteralVarargs() else []
        self.traversal.add_step(Step("values", params))

    # 值提取访问器
    def visitStringLiteral(self, ctx: GremlinParser.StringLiteralContext) -> str:
        return ctx.getText().strip("'\"")

    def visitIntegerLiteral(self, ctx: GremlinParser.IntegerLiteralContext) -> int:
        text = ctx.getText().lower().rstrip("l")
        return int(text)

    def visitGenericArgumentVarargs(self, ctx: GremlinParser.GenericArgumentVarargsContext) -> list:
        if ctx is None:
            return []
        args = []
        # 使用 genericArgument() 方法获取所有参数
        for i in range(len(ctx.genericArgument())):
            args.append(self.visit(ctx.genericArgument(i)))
        return args

    def visitStringNullableArgumentVarargs(self, ctx: GremlinParser.StringNullableArgumentVarargsContext) -> list:
        if ctx is None:
            return []
        args = []
        if ctx.children:
            for child in ctx.children:
                if isinstance(child, GremlinParser.StringNullableArgumentContext):
                    args.append(self.visit(child))
        return args

    def visitTraversalPredicate_gt(self, ctx: GremlinParser.TraversalPredicate_gtContext):
        value = self.visit(ctx.genericArgument())
        return Predicate("gt", value)

    def visitTraversalPredicate_within(self, ctx: GremlinParser.TraversalPredicate_withinContext):
        values = self.visit(ctx.genericArgumentVarargs())
        return Predicate("within", values)

    # 更多谓词的访问器
    def visitTraversalPredicate_lt(self, ctx):
        value = self.visit(ctx.genericArgument())
        return Predicate("lt", value)

    def visitTraversalPredicate_lte(self, ctx):
        value = self.visit(ctx.genericArgument())
        return Predicate("lte", value)

    def visitTraversalPredicate_gte(self, ctx):
        value = self.visit(ctx.genericArgument())
        return Predicate("gte", value)

    def visitTraversalPredicate_eq(self, ctx):
        value = self.visit(ctx.genericArgument())
        return Predicate("eq", value)

    def visitTraversalPredicate_neq(self, ctx):
        value = self.visit(ctx.genericArgument())
        return Predicate("neq", value)

    def visitTraversalPredicate_between(self, ctx):
        params = []
        if hasattr(ctx, "genericArgument"):
            if ctx.genericArgument(0):
                params.append(self.visit(ctx.genericArgument(0)))
            if ctx.genericArgument(1):
                params.append(self.visit(ctx.genericArgument(1)))
        return Predicate("between", params)

    def visitTraversalPredicate_inside(self, ctx):
        params = []
        if hasattr(ctx, "genericArgument"):
            if ctx.genericArgument(0):
                params.append(self.visit(ctx.genericArgument(0)))
            if ctx.genericArgument(1):
                params.append(self.visit(ctx.genericArgument(1)))
        return Predicate("inside", params)

    def visitTraversalPredicate_outside(self, ctx):
        params = []
        if hasattr(ctx, "genericArgument"):
            if ctx.genericArgument(0):
                params.append(self.visit(ctx.genericArgument(0)))
            if ctx.genericArgument(1):
                params.append(self.visit(ctx.genericArgument(1)))
        return Predicate("outside", params)

    def visitTraversalPredicate_without(self, ctx):
        values = self.visit(ctx.genericArgumentVarargs())
        return Predicate("without", values)

    # TextPredicate 访问器
    def visitTraversalPredicate_startingWith(self, ctx):
        value = self.visit(ctx.stringArgument())
        return TextPredicate("startingWith", value)

    def visitTraversalPredicate_endingWith(self, ctx):
        value = self.visit(ctx.stringArgument())
        return TextPredicate("endingWith", value)

    def visitTraversalPredicate_containing(self, ctx):
        value = self.visit(ctx.stringArgument())
        return TextPredicate("containing", value)

    def visitTraversalPredicate_notStartingWith(self, ctx):
        value = self.visit(ctx.stringArgument())
        return TextPredicate("notStartingWith", value)

    def visitTraversalPredicate_notEndingWith(self, ctx):
        value = self.visit(ctx.stringArgument())
        return TextPredicate("notEndingWith", value)

    def visitTraversalPredicate_notContaining(self, ctx):
        value = self.visit(ctx.stringArgument())
        return TextPredicate("notContaining", value)

    def visitTraversalPredicate_not(self, ctx):
        """处理 not() 谓词 - 否定另一个谓词"""
        # not() 接受另一个谓词作为参数
        if hasattr(ctx, "traversalPredicate") and ctx.traversalPredicate():
            inner_predicate = self.visit(ctx.traversalPredicate())
            # 返回一个否定的谓词
            # 注意：这里需要特殊处理，因为 not() 包装了另一个谓词
            return Predicate("not", inner_predicate)
        return None

    def visitTraversalPredicate_regex(self, ctx):
        """处理 regex() 谓词 - 正则表达式匹配"""
        value = self.visit(ctx.stringArgument())
        return TextPredicate("regex", value)

    def visitTraversalPredicate_notRegex(self, ctx):
        """处理 notRegex() 谓词 - 不匹配正则表达式"""
        value = self.visit(ctx.stringArgument())
        return TextPredicate("notRegex", value)

    # 匿名遍历和嵌套遍历访问器
    def visitNestedTraversal(self, ctx: GremlinParser.NestedTraversalContext):
        # 创建一个新的匿名遍历
        anonymous_traversal = AnonymousTraversal()

        # 保存当前遍历状态
        current_traversal = self.traversal

        # 创建临时遍历来收集匿名遍历的步骤
        temp_traversal = Traversal()
        self.traversal = temp_traversal

        # 访问嵌套遍历的内容
        if ctx.chainedTraversal():
            self.visit(ctx.chainedTraversal())

        # 将临时遍历的步骤添加到匿名遍历中
        for step in temp_traversal.steps:
            anonymous_traversal.add_step(step)

        # 恢复原始遍历状态
        self.traversal = current_traversal

        return anonymous_traversal

    def visitNestedTraversalVarargs(self, ctx):
        if ctx is None:
            return []

        traversals = []
        for child in ctx.children:
            if isinstance(child, GremlinParser.NestedTraversalContext):
                traversals.append(self.visit(child))
        return traversals

    # 连接器访问器 (and, or)
    def visitTraversalMethod_and(self, ctx):
        params = []
        if hasattr(ctx, "nestedTraversalList") and ctx.nestedTraversalList():
            traversals = self.visit(ctx.nestedTraversalList())
            if traversals:
                # and接受多个遍历作为参数
                params.extend(traversals)
        self.traversal.add_step(Step("and", params))

    def visitTraversalMethod_or(self, ctx):
        params = []
        if hasattr(ctx, "nestedTraversalList") and ctx.nestedTraversalList():
            traversals = self.visit(ctx.nestedTraversalList())
            if traversals:
                # or接受多个遍历作为参数
                params.extend(traversals)
        self.traversal.add_step(Step("or", params))

    # 分支和条件方法
    def visitTraversalMethod_choose_Traversal(self, ctx):
        """处理choose(traversal)方法"""
        params = []
        if hasattr(ctx, "nestedTraversal") and ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("choose", params))

    def visitTraversalMethod_coalesce(self, ctx):
        """处理coalesce()方法"""
        params = []
        if hasattr(ctx, "nestedTraversalList") and ctx.nestedTraversalList():
            params = self.visit(ctx.nestedTraversalList())
        elif hasattr(ctx, "nestedTraversalVarargs") and ctx.nestedTraversalVarargs():
            params = self.visit(ctx.nestedTraversalVarargs())
        self.traversal.add_step(Step("coalesce", params))

    def visitTraversalMethod_optional(self, ctx):
        """处理optional()方法"""
        params = []
        if hasattr(ctx, "nestedTraversal") and ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("optional", params))

    def visitTraversalMethod_union(self, ctx):
        """处理union()方法"""
        params = []
        if hasattr(ctx, "nestedTraversalList") and ctx.nestedTraversalList():
            params = self.visit(ctx.nestedTraversalList())
        elif hasattr(ctx, "nestedTraversalVarargs") and ctx.nestedTraversalVarargs():
            params = self.visit(ctx.nestedTraversalVarargs())
        self.traversal.add_step(Step("union", params))

    # 循环和重复方法
    def visitTraversalMethod_repeat_Traversal(self, ctx):
        """处理repeat(traversal)方法"""
        params = []
        if hasattr(ctx, "nestedTraversal") and ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("repeat", params))

    def visitTraversalMethod_repeat_String_Traversal(self, ctx):
        """处理repeat(string, traversal)方法"""
        params = []
        if hasattr(ctx, "stringLiteral") and ctx.stringLiteral():
            params.append(self.visit(ctx.stringLiteral()))
        if hasattr(ctx, "nestedTraversal") and ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("repeat", params))

    def visitTraversalMethod_times(self, ctx):
        """处理times()方法"""
        params = []
        if hasattr(ctx, "integerLiteral") and ctx.integerLiteral():
            params.append(self.visit(ctx.integerLiteral()))
        self.traversal.add_step(Step("times", params))

    def visitTraversalMethod_until_Traversal(self, ctx):
        """处理until(traversal)方法"""
        params = []
        if hasattr(ctx, "nestedTraversal") and ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("until", params))

    def visitTraversalMethod_until_Predicate(self, ctx):
        """处理until(predicate)方法"""
        params = []
        if hasattr(ctx, "traversalPredicate") and ctx.traversalPredicate():
            params.append(self.visit(ctx.traversalPredicate()))
        self.traversal.add_step(Step("until", params))

    def visitTraversalMethod_emit_Empty(self, ctx):
        """处理无参数的emit()方法"""
        self.traversal.add_step(Step("emit", []))

    def visitTraversalMethod_emit_Predicate(self, ctx):
        """处理emit(predicate)方法"""
        params = []
        if hasattr(ctx, "traversalPredicate") and ctx.traversalPredicate():
            params.append(self.visit(ctx.traversalPredicate()))
        self.traversal.add_step(Step("emit", params))

    def visitTraversalMethod_emit_Traversal(self, ctx):
        """处理emit(traversal)方法"""
        params = []
        if hasattr(ctx, "nestedTraversal") and ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("emit", params))

    # 终端方法访问器
    def visitTraversalTerminalMethod(self, ctx):
        """处理终端方法的通用分发器"""
        # 直接访问具体的终端方法子节点
        if ctx.traversalTerminalMethod_next():
            self.visit(ctx.traversalTerminalMethod_next())
        elif ctx.traversalTerminalMethod_hasNext():
            self.visit(ctx.traversalTerminalMethod_hasNext())
        elif ctx.traversalTerminalMethod_toList():
            self.visit(ctx.traversalTerminalMethod_toList())
        elif ctx.traversalTerminalMethod_toSet():
            self.visit(ctx.traversalTerminalMethod_toSet())
        elif ctx.traversalTerminalMethod_iterate():
            self.visit(ctx.traversalTerminalMethod_iterate())
        else:
            # 尝试默认的visitChildren
            return self.visitChildren(ctx)

    def visitTraversalTerminalMethod_next(self, ctx):
        """处理next()终端方法，支持 next() 和 next(n)"""
        params = []
        # 检查是否有整数参数
        if hasattr(ctx, "integerLiteral") and ctx.integerLiteral():
            params.append(self.visit(ctx.integerLiteral()))
        else:
            # 无参数版本，使用 Terminal 对象
            terminal = Terminal("next")
            params.append(terminal)
        self.traversal.add_step(Step("next", params))

    def visitTraversalTerminalMethod_hasNext(self, ctx):
        """处理hasNext()终端方法"""
        terminal = Terminal("hasNext")
        self.traversal.add_step(Step("hasNext", [terminal]))

    def visitTraversalTerminalMethod_toList(self, ctx):
        """处理toList()终端方法"""
        terminal = Terminal("toList")
        self.traversal.add_step(Step("toList", [terminal]))

    def visitTraversalTerminalMethod_toSet(self, ctx):
        """处理toSet()终端方法"""
        terminal = Terminal("toSet")
        self.traversal.add_step(Step("toSet", [terminal]))

    def visitTraversalTerminalMethod_iterate(self, ctx):
        """处理iterate()终端方法"""
        terminal = Terminal("iterate")
        self.traversal.add_step(Step("iterate", [terminal]))

    def visitTraversalTerminalMethod_tryNext(self, ctx):
        """处理tryNext()终端方法"""
        terminal = Terminal("tryNext")
        self.traversal.add_step(Step("tryNext", [terminal]))

    def visitTraversalTerminalMethod_explain(self, ctx):
        """处理explain()终端方法 - 显示执行计划"""
        terminal = Terminal("explain")
        self.traversal.add_step(Step("explain", [terminal]))

    # 去重和其他方法

    # Context方法 - 终端方法的Context版本
    def visitTraversalTerminalMethodContext(self, ctx):
        """处理终端方法Context - 委托给visitTraversalTerminalMethod"""
        return self.visitTraversalTerminalMethod(ctx)

    def visitTraversalTerminalMethod_nextContext(self, ctx):
        """处理next()终端方法Context"""
        return self.visitTraversalTerminalMethod_next(ctx)

    def visitTraversalTerminalMethod_hasNextContext(self, ctx):
        """处理hasNext()终端方法Context"""
        return self.visitTraversalTerminalMethod_hasNext(ctx)

    def visitTraversalTerminalMethod_toListContext(self, ctx):
        """处理toList()终端方法Context"""
        return self.visitTraversalTerminalMethod_toList(ctx)

    def visitTraversalTerminalMethod_toSetContext(self, ctx):
        """处理toSet()终端方法Context"""
        return self.visitTraversalTerminalMethod_toSet(ctx)

    def visitTraversalTerminalMethod_iterateContext(self, ctx):
        """处理iterate()终端方法Context"""
        return self.visitTraversalTerminalMethod_iterate(ctx)

    def visitTraversalTerminalMethod_tryNextContext(self, ctx):
        """处理tryNext()终端方法Context"""
        return self.visitTraversalTerminalMethod_tryNext(ctx)

    def visitTraversalMethod_valueMap_String(self, ctx):
        """处理valueMap(string)方法"""
        params = []
        if hasattr(ctx, "stringNullableLiteralVarargs") and ctx.stringNullableLiteralVarargs():
            params = self.visit(ctx.stringNullableLiteralVarargs())
        self.traversal.add_step(Step("valueMap", params))

    def visitTraversalMethod_valueMap_boolean_String(self, ctx):
        """处理valueMap(boolean, string)方法"""
        params = []
        if hasattr(ctx, "booleanLiteral") and ctx.booleanLiteral():
            params.append(self.visit(ctx.booleanLiteral()))
        if hasattr(ctx, "stringNullableLiteralVarargs") and ctx.stringNullableLiteralVarargs():
            string_params = self.visit(ctx.stringNullableLiteralVarargs())
            if string_params:
                params.extend(string_params)
        self.traversal.add_step(Step("valueMap", params))

    def visitTraversalMethod_valueMap_StringContext(self, ctx):
        """处理valueMap(string)方法Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_dedup_String(self, ctx):
        """处理dedup()方法"""
        params = []
        if hasattr(ctx, "stringNullableLiteralVarargs") and ctx.stringNullableLiteralVarargs():
            params = self.visit(ctx.stringNullableLiteralVarargs())
        self.traversal.add_step(Step("dedup", params))

    def visitTraversalMethod_path(self, ctx):
        """处理path()方法"""
        self.traversal.add_step(Step("path", []))

    def visitTraversalMethod_as(self, ctx):
        """处理as()方法"""
        params = []
        if hasattr(ctx, "stringArgument") and ctx.stringArgument():
            params.append(self.visit(ctx.stringArgument()))
        elif hasattr(ctx, "stringLiteral") and ctx.stringLiteral():
            params.append(self.visit(ctx.stringLiteral()))
        self.traversal.add_step(Step("as", params))

    def visitTraversalMethod_select_String(self, ctx):
        """处理select(string)方法"""
        params = []
        if hasattr(ctx, "stringArgument") and ctx.stringArgument():
            params.append(self.visit(ctx.stringArgument()))
        elif hasattr(ctx, "stringLiteral") and ctx.stringLiteral():
            params.append(self.visit(ctx.stringLiteral()))
        self.traversal.add_step(Step("select", params))

    # 基础Context方法 - 这些是ANTLR visitor模式必需的
    def visitQueryContext(self, ctx):
        """处理查询的根Context"""
        return self.visitChildren(ctx)

    def visitRootTraversalContext(self, ctx):
        """处理根遍历Context"""
        return self.visitChildren(ctx)

    def visitTraversalSourceContext(self, ctx):
        """处理遍历源Context"""
        return self.visitChildren(ctx)

    def visitTraversalSourceSpawnMethodContext(self, ctx):
        """处理遍历源生成方法Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethodContext(self, ctx):
        """处理遍历方法Context"""
        return self.visitChildren(ctx)

    def visitChainedTraversalContext(self, ctx):
        """处理链式遍历Context"""
        return self.visitChildren(ctx)

    # 参数和字面量Context方法
    def visitGenericArgumentVarargsContext(self, ctx):
        """处理通用参数变长列表"""
        return self.visitChildren(ctx)

    def visitStringLiteralContext(self, ctx):
        """处理字符串字面量"""
        return ctx.getText().strip("'\"")

    def visitIntegerLiteralContext(self, ctx):
        """处理整数字面量"""
        text = ctx.getText().lower().rstrip("l")
        return int(text)

    def visitFloatLiteralContext(self, ctx):
        """处理浮点数字面量"""
        return float(ctx.getText())

    def visitGenericLiteralContext(self, ctx):
        """处理通用字面量"""
        return self.visitChildren(ctx)

    def visitNumericLiteralContext(self, ctx):
        """处理数值字面量"""
        return self.visitChildren(ctx)

    def visitStringArgumentContext(self, ctx):
        """处理字符串参数"""
        return self.visitChildren(ctx)

    def visitIntegerArgumentContext(self, ctx):
        """处理整数参数"""
        return self.visitChildren(ctx)

    def visitFloatArgumentContext(self, ctx):
        """处理浮点数参数"""
        return self.visitChildren(ctx)

    def visitGenericArgumentContext(self, ctx):
        """处理通用参数"""
        return self.visitChildren(ctx)

    def visitStringNullableLiteralContext(self, ctx):
        """处理可空字符串字面量"""
        if ctx.getText() == "null":
            return None
        return ctx.getText().strip("'\"")

    def visitStringNullableLiteralVarargsContext(self, ctx):
        """处理可空字符串字面量变长列表"""
        return self.visitChildren(ctx)

    def visitStringNullableArgumentContext(self, ctx):
        """处理可空字符串参数"""
        return self.visitChildren(ctx)

    def visitStringNullableArgumentVarargsContext(self, ctx):
        """处理可空字符串参数变长列表"""
        return self.visitChildren(ctx)

    # 其他重要方法
    def visitTraversalMethod_identity(self, ctx):
        """处理identity()方法"""
        self.traversal.add_step(Step("identity", []))

    def visitTraversalMethod_barrier_Empty(self, ctx):
        """处理无参数的barrier()方法"""
        self.traversal.add_step(Step("barrier", []))

    def visitTraversalMethod_constant(self, ctx):
        """处理constant()方法"""
        params = []
        if hasattr(ctx, "genericArgument") and ctx.genericArgument():
            params.append(self.visit(ctx.genericArgument()))
        self.traversal.add_step(Step("constant", params))

    def visitTraversalMethod_math(self, ctx):
        """处理math()方法"""
        params = []
        if hasattr(ctx, "stringArgument") and ctx.stringArgument():
            params.append(self.visit(ctx.stringArgument()))
        elif hasattr(ctx, "stringLiteral") and ctx.stringLiteral():
            params.append(self.visit(ctx.stringLiteral()))
        self.traversal.add_step(Step("math", params))

    def visitTraversalMethod_timeLimit(self, ctx):
        """处理timeLimit()方法"""
        params = []
        if hasattr(ctx, "integerArgument") and ctx.integerArgument():
            params.append(self.visit(ctx.integerArgument()))
        self.traversal.add_step(Step("timeLimit", params))

    def visitTraversalMethod_subgraph(self, ctx):
        """处理subgraph()方法"""
        params = []
        if hasattr(ctx, "stringArgument") and ctx.stringArgument():
            params.append(self.visit(ctx.stringArgument()))
        elif hasattr(ctx, "stringLiteral") and ctx.stringLiteral():
            params.append(self.visit(ctx.stringLiteral()))
        self.traversal.add_step(Step("subgraph", params))

    def visitTraversalMethod_cyclicPath(self, ctx):
        """处理cyclicPath()方法"""
        self.traversal.add_step(Step("cyclicPath", []))

    def visitTraversalMethod_simplePath(self, ctx):
        """处理simplePath()方法"""
        self.traversal.add_step(Step("simplePath", []))

    def visitTraversalMethod_match(self, ctx):
        """处理match()方法"""
        params = []
        if hasattr(ctx, "nestedTraversalList") and ctx.nestedTraversalList():
            params = self.visit(ctx.nestedTraversalList())
        self.traversal.add_step(Step("match", params))

    # 高级转换和映射方法
    def visitTraversalMethod_map(self, ctx):
        """处理map()方法 - 将对象转换为另一个对象"""
        params = []
        if hasattr(ctx, "nestedTraversal") and ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("map", params))

    def visitTraversalMethod_local(self, ctx):
        """处理local()方法 - 将遍历应用于遍历器内部的对象"""
        params = []
        if hasattr(ctx, "nestedTraversal") and ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("local", params))

    # 副作用和聚合方法
    def visitTraversalMethod_aggregate_String(self, ctx):
        """处理aggregate(string)方法 - 收集结果到副作用集合"""
        params = []
        if hasattr(ctx, "stringArgument") and ctx.stringArgument():
            params.append(self.visit(ctx.stringArgument()))
        elif hasattr(ctx, "stringLiteral") and ctx.stringLiteral():
            params.append(self.visit(ctx.stringLiteral()))
        self.traversal.add_step(Step("aggregate", params))

    def visitTraversalMethod_aggregate_Scope_String(self, ctx):
        """处理aggregate(scope, string)方法"""
        params = []
        if hasattr(ctx, "traversalScope") and ctx.traversalScope():
            params.append(self.visit(ctx.traversalScope()))
        if hasattr(ctx, "stringArgument") and ctx.stringArgument():
            params.append(self.visit(ctx.stringArgument()))
        elif hasattr(ctx, "stringLiteral") and ctx.stringLiteral():
            params.append(self.visit(ctx.stringLiteral()))
        self.traversal.add_step(Step("aggregate", params))

    def visitTraversalMethod_store(self, ctx):
        """处理store()方法 - 惰性地收集遍历器到副作用集合"""
        params = []
        if hasattr(ctx, "stringArgument") and ctx.stringArgument():
            params.append(self.visit(ctx.stringArgument()))
        elif hasattr(ctx, "stringLiteral") and ctx.stringLiteral():
            params.append(self.visit(ctx.stringLiteral()))
        self.traversal.add_step(Step("store", params))

    def visitTraversalMethod_sideEffect(self, ctx):
        """处理sideEffect()方法 - 执行副作用操作"""
        params = []
        if hasattr(ctx, "nestedTraversal") and ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("sideEffect", params))

    def visitTraversalMethod_cap(self, ctx):
        """处理cap()方法 - 从副作用中发射内容"""
        params = []
        if hasattr(ctx, "stringLiteral") and ctx.stringLiteral():
            params.append(self.visit(ctx.stringLiteral()))
        if hasattr(ctx, "stringNullableLiteralVarargs") and ctx.stringNullableLiteralVarargs():
            varargs = self.visit(ctx.stringNullableLiteralVarargs())
            if varargs:
                params.extend(varargs)
        self.traversal.add_step(Step("cap", params))

    # Sack方法 - 管理遍历器私有值
    def visitTraversalMethod_sack_Empty(self, ctx):
        """处理无参数的sack()方法"""
        self.traversal.add_step(Step("sack", []))

    def visitTraversalMethod_sack_BiFunction(self, ctx):
        """处理sack(biFunction)方法"""
        params = []
        if hasattr(ctx, "traversalBiFunction") and ctx.traversalBiFunction():
            params.append(self.visit(ctx.traversalBiFunction()))
        self.traversal.add_step(Step("sack", params))

    # 图算法方法
    def visitTraversalMethod_pageRank_Empty(self, ctx):
        """处理无参数的pageRank()方法"""
        self.traversal.add_step(Step("pageRank", []))

    def visitTraversalMethod_pageRank_double(self, ctx):
        """处理pageRank(double)方法"""
        params = []
        if hasattr(ctx, "floatArgument") and ctx.floatArgument():
            params.append(self.visit(ctx.floatArgument()))
        self.traversal.add_step(Step("pageRank", params))

    def visitTraversalMethod_peerPressure(self, ctx):
        """处理peerPressure()方法 - 标签传播算法"""
        self.traversal.add_step(Step("peerPressure", []))

    def visitTraversalMethod_connectedComponent(self, ctx):
        """处理connectedComponent()方法 - 查找连通分量"""
        self.traversal.add_step(Step("connectedComponent", []))

    def visitTraversalMethod_shortestPath(self, ctx):
        """处理shortestPath()方法 - 计算最短路径"""
        self.traversal.add_step(Step("shortestPath", []))

    # 树和层级结构方法
    def visitTraversalMethod_tree_Empty(self, ctx):
        """处理无参数的tree()方法"""
        self.traversal.add_step(Step("tree", []))

    def visitTraversalMethod_tree_String(self, ctx):
        """处理tree(string)方法"""
        params = []
        if hasattr(ctx, "stringArgument") and ctx.stringArgument():
            params.append(self.visit(ctx.stringArgument()))
        elif hasattr(ctx, "stringLiteral") and ctx.stringLiteral():
            params.append(self.visit(ctx.stringLiteral()))
        self.traversal.add_step(Step("tree", params))

    # 调试和分析方法
    def visitTraversalMethod_profile_Empty(self, ctx):
        """处理无参数的profile()方法"""
        self.traversal.add_step(Step("profile", []))

    def visitTraversalMethod_profile_String(self, ctx):
        """处理profile(string)方法"""
        params = []
        if hasattr(ctx, "stringArgument") and ctx.stringArgument():
            params.append(self.visit(ctx.stringArgument()))
        elif hasattr(ctx, "stringLiteral") and ctx.stringLiteral():
            params.append(self.visit(ctx.stringLiteral()))
        self.traversal.add_step(Step("profile", params))

    # 循环控制方法
    def visitTraversalMethod_loops_Empty(self, ctx):
        """处理无参数的loops()方法"""
        self.traversal.add_step(Step("loops", []))

    def visitTraversalMethod_loops_String(self, ctx):
        """处理loops(string)方法"""
        params = []
        if hasattr(ctx, "stringArgument") and ctx.stringArgument():
            params.append(self.visit(ctx.stringArgument()))
        elif hasattr(ctx, "stringLiteral") and ctx.stringLiteral():
            params.append(self.visit(ctx.stringLiteral()))
        self.traversal.add_step(Step("loops", params))

    # 嵌套遍历Context方法 - 委托给原有的visitNestedTraversal实现
    def visitNestedTraversalContext(self, ctx):
        """处理嵌套遍历Context - 委托给visitNestedTraversal"""
        # 直接调用原有的visitNestedTraversal方法
        return self.visitNestedTraversal(ctx)

    def visitNestedTraversalExpr(self, ctx):
        """处理嵌套遍历表达式 - 返回多个嵌套遍历的列表"""
        result = []
        # nestedTraversalExpr包含多个nestedTraversal，用逗号分隔
        if hasattr(ctx, "nestedTraversal"):
            nested_traversals = ctx.nestedTraversal()
            if isinstance(nested_traversals, list):
                for nt in nested_traversals:
                    result.append(self.visit(nt))
            else:
                result.append(self.visit(nested_traversals))
        return result

    def visitNestedTraversalExprContext(self, ctx):
        """处理嵌套遍历表达式Context"""
        return self.visitNestedTraversalExpr(ctx)

    def visitNestedTraversalList(self, ctx):
        """处理嵌套遍历列表 - 可能包含0个或多个嵌套遍历"""
        # nestedTraversalList包含一个可选的nestedTraversalExpr
        if hasattr(ctx, "nestedTraversalExpr") and ctx.nestedTraversalExpr():
            return self.visit(ctx.nestedTraversalExpr())
        return []

    def visitNestedTraversalListContext(self, ctx):
        """处理嵌套遍历列表Context"""
        return self.visitNestedTraversalList(ctx)

    # 谓词和比较器Context方法
    def visitTraversalPredicateContext(self, ctx):
        """处理遍历谓词Context"""
        return self.visitChildren(ctx)

    def visitTraversalPredicate_gtContext(self, ctx):
        """处理gt谓词Context"""
        return self.visitChildren(ctx)

    def visitTraversalComparatorContext(self, ctx):
        """处理遍历比较器Context"""
        return self.visitChildren(ctx)

    def visitTraversalOrderContext(self, ctx):
        """处理遍历排序Context"""
        return self.visitChildren(ctx)

    # 更多具体方法的Context版本
    def visitTraversalMethod_count_EmptyContext(self, ctx):
        """处理count()空参数Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_sum_EmptyContext(self, ctx):
        """处理sum()空参数Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_mean_EmptyContext(self, ctx):
        """处理mean()空参数Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_max_EmptyContext(self, ctx):
        """处理max()空参数Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_min_EmptyContext(self, ctx):
        """处理min()空参数Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_fold_EmptyContext(self, ctx):
        """处理fold()空参数Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_order_EmptyContext(self, ctx):
        """处理order()空参数Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_group_EmptyContext(self, ctx):
        """处理group()空参数Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_group_StringContext(self, ctx):
        """处理group(string)带标签参数Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_groupCount_EmptyContext(self, ctx):
        """处理groupCount()空参数Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_groupCount_StringContext(self, ctx):
        """处理groupCount(string)带标签参数Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_by_StringContext(self, ctx):
        """处理by(string)Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_by_String_ComparatorContext(self, ctx):
        """处理by(string, comparator)Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_by_TraversalContext(self, ctx):
        """处理by(traversal)Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_dedup_StringContext(self, ctx):
        """处理dedup()Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_pathContext(self, ctx):
        """处理path()Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_asContext(self, ctx):
        """处理as()Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_select_StringContext(self, ctx):
        """处理select(string)Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_select_String_String_StringContext(self, ctx):
        """处理select(string, string, string)Context"""
        return self.visitChildren(ctx)

    # 剩余的缺失方法
    def visitTraversalMethod_barrier_EmptyContext(self, ctx):
        """处理barrier()空参数Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_choose_TraversalContext(self, ctx):
        """处理choose(traversal)Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_coalesceContext(self, ctx):
        """处理coalesce()Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_constantContext(self, ctx):
        """处理constant()Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_cyclicPathContext(self, ctx):
        """处理cyclicPath()Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_emit_EmptyContext(self, ctx):
        """处理emit()空参数Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_hasLabel_String_StringContext(self, ctx):
        """处理hasLabel(string, string)Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_has_String_ObjectContext(self, ctx):
        """处理has(string, object)Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_has_String_PContext(self, ctx):
        """处理has(string, predicate)Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_identityContext(self, ctx):
        """处理identity()Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_matchContext(self, ctx):
        """处理match()Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_mathContext(self, ctx):
        """处理math()Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_optionalContext(self, ctx):
        """处理optional()Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_range_long_longContext(self, ctx):
        """处理range(long, long)Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_repeat_TraversalContext(self, ctx):
        """处理repeat(traversal)Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_sample_intContext(self, ctx):
        """处理sample(int)Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_simplePathContext(self, ctx):
        """处理simplePath()Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_skip_longContext(self, ctx):
        """处理skip(long)Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_subgraphContext(self, ctx):
        """处理subgraph()Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_tail_longContext(self, ctx):
        """处理tail(long)Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_timeLimitContext(self, ctx):
        """处理timeLimit()Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_timesContext(self, ctx):
        """处理times()Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_unionContext(self, ctx):
        """处理union()Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_until_TraversalContext(self, ctx):
        """处理until(traversal)Context"""
        return self.visitChildren(ctx)

    # 更多具体的Context方法
    def visitTraversalSourceSpawnMethod_VContext(self, ctx):
        """处理V()生成方法Context"""
        return self.visitChildren(ctx)

    def visitTraversalSourceSpawnMethod_EContext(self, ctx):
        """处理E()生成方法Context"""
        return self.visitChildren(ctx)

    def visitTraversalSourceSpawnMethod_addVContext(self, ctx):
        """处理addV()生成方法Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_outContext(self, ctx):
        """处理out()方法Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_inEContext(self, ctx):
        """处理inE()方法Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_outEContext(self, ctx):
        """处理outE()方法Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_bothEContext(self, ctx):
        """处理bothE()方法Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_inVContext(self, ctx):
        """处理inV()方法Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_outVContext(self, ctx):
        """处理outV()方法Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_bothVContext(self, ctx):
        """处理bothV()方法Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_idContext(self, ctx):
        """处理id()方法Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_labelContext(self, ctx):
        """处理label()方法Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_keyContext(self, ctx):
        """处理key()方法Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_valueContext(self, ctx):
        """处理value()方法Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_valuesContext(self, ctx):
        """处理values()方法Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_propertiesContext(self, ctx):
        """处理properties()方法Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_elementMapContext(self, ctx):
        """处理elementMap()方法Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_dropContext(self, ctx):
        """处理drop()方法Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_addE_StringContext(self, ctx):
        """处理addE(string)方法Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_property_Object_Object_ObjectContext(self, ctx):
        """处理property()方法Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_limit_longContext(self, ctx):
        """处理limit()方法Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_coinContext(self, ctx):
        """处理coin()方法Context"""
        return self.visitChildren(ctx)

    def visitTraversalMethod_unfoldContext(self, ctx):
        """处理unfold()方法Context"""
        return self.visitChildren(ctx)

    def visitTraversalSourceSpawnMethod_E(self, ctx: GremlinParser.TraversalSourceSpawnMethod_EContext):
        params = self.visit(ctx.genericArgumentVarargs()) if ctx.genericArgumentVarargs() else []
        self.traversal.add_step(Step("E", params))

    def visitTraversalSourceSpawnMethod_addE(self, ctx: GremlinParser.TraversalSourceSpawnMethod_addEContext):
        params = []
        if ctx.stringArgument():
            params.append(self.visit(ctx.stringArgument()))
        elif ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("addE", params))

    def visitTraversalSourceSpawnMethod_inject(self, ctx: GremlinParser.TraversalSourceSpawnMethod_injectContext):
        params = self.visit(ctx.genericArgumentVarargs()) if ctx.genericArgumentVarargs() else []
        self.traversal.add_step(Step("inject", params))

    # Call方法的各种变体支持
    def visitTraversalSourceSpawnMethod_call_empty(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_call_emptyContext
    ):
        """处理 g.call() 空参数调用"""
        self.traversal.add_step(Step("call", []))

    def visitTraversalSourceSpawnMethod_call_string(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_call_stringContext
    ):
        """处理 g.call('methodName') 单字符串参数调用"""
        params = []
        # 查找StringLiteralContext子节点
        for child in ctx.children:
            if hasattr(child, "getRuleIndex") and "StringLiteral" in type(child).__name__:
                string_val = child.getText()
                # 移除引号
                if (string_val.startswith('"') and string_val.endswith('"')) or (
                    string_val.startswith("'") and string_val.endswith("'")
                ):
                    string_val = string_val[1:-1]
                params.append(string_val)
                break
        self.traversal.add_step(Step("call", params))

    def visitTraversalSourceSpawnMethod_call_string_map(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_call_string_mapContext
    ):
        """处理 g.call('methodName', map) 字符串+映射参数调用"""
        params = []
        if ctx.stringArgument():
            params.append(self.visit(ctx.stringArgument()))
        if ctx.genericLiteralMap():
            params.append(self.visit(ctx.genericLiteralMap()))
        self.traversal.add_step(Step("call", params))

    def visitTraversalSourceSpawnMethod_call_string_traversal(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_call_string_traversalContext
    ):
        """处理 g.call('methodName', traversal) 字符串+遍历参数调用"""
        params = []
        if ctx.stringArgument():
            params.append(self.visit(ctx.stringArgument()))
        if ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("call", params))

    def visitTraversalSourceSpawnMethod_call_string_map_traversal(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_call_string_map_traversalContext
    ):
        """处理 g.call('methodName', map, traversal) 字符串+映射+遍历参数调用"""
        params = []
        if ctx.stringArgument():
            params.append(self.visit(ctx.stringArgument()))
        if ctx.genericLiteralMap():
            params.append(self.visit(ctx.genericLiteralMap()))
        if ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("call", params))

    def visitTraversalSourceSpawnMethod_io(self, ctx: GremlinParser.TraversalSourceSpawnMethod_ioContext):
        params = []
        if ctx.stringLiteral():
            params.append(self.visit(ctx.stringLiteral()))
        self.traversal.add_step(Step("io", params))

    # 辅助方法访问器
    def visitStringArgument(self, ctx: GremlinParser.StringArgumentContext):
        if ctx.stringLiteral():
            return self.visit(ctx.stringLiteral())
        elif ctx.stringNullableLiteral():
            return self.visit(ctx.stringNullableLiteral())
        return None

    def visitStringNullableLiteral(self, ctx: GremlinParser.StringNullableLiteralContext):
        if ctx.EmptyStringLiteral():
            return ""
        elif ctx.NonEmptyStringLiteral():
            text = ctx.NonEmptyStringLiteral().getText()
            return text.strip("'\"")
        elif ctx.K_NULL():
            return None
        return None

    def visitStringNullableArgument(self, ctx: GremlinParser.StringNullableArgumentContext):
        if ctx.stringNullableLiteral():
            return self.visit(ctx.stringNullableLiteral())
        elif ctx.variable():
            return self.visit(ctx.variable())
        return None

    def visitGenericArgument(self, ctx: GremlinParser.GenericArgumentContext):
        if ctx.genericLiteral():
            return self.visit(ctx.genericLiteral())
        elif ctx.variable():
            return self.visit(ctx.variable())
        return None

    def visitIntegerArgument(self, ctx: GremlinParser.IntegerArgumentContext):
        if ctx.integerLiteral():
            return self.visit(ctx.integerLiteral())
        return 0

    def visitFloatLiteral(self, ctx: GremlinParser.FloatLiteralContext) -> float:
        text = ctx.getText().lower().rstrip("f").rstrip("d")
        return float(text)

    def visitBooleanLiteral(self, ctx: GremlinParser.BooleanLiteralContext) -> bool:
        text = ctx.getText().lower()
        return text == "true"

    def visitNullLiteral(self, ctx: GremlinParser.NullLiteralContext):
        return None

    def visitGenericLiteral(self, ctx: GremlinParser.GenericLiteralContext):
        # 处理通用字面量，可能是字符串、数字等
        text = ctx.getText()
        lowered = text.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if lowered == "null":
            return None
        # 尝试解析为不同类型
        if text.startswith('"') or text.startswith("'"):
            return text.strip("'\"")
        try:
            if "." in text:
                return float(text)
            else:
                return int(text)
        except ValueError:
            return text

    def visitVariable(self, ctx: GremlinParser.VariableContext):
        # 变量通常以 $ 开头，返回变量名
        return ctx.getText()

    def visitTraversalT(self, ctx):
        # T 枚举值，如 T.id, T.label, T.key, T.value
        return ctx.getText()

    def visitStringNullableLiteralVarargs(self, ctx: GremlinParser.StringNullableLiteralVarargsContext) -> list:
        if ctx is None:
            return []
        args = []
        # 使用 stringNullableLiteral() 方法获取所有参数
        for i in range(len(ctx.stringNullableLiteral())):
            args.append(self.visit(ctx.stringNullableLiteral(i)))
        return args

    def visitFloatArgument(self, ctx):
        if hasattr(ctx, "floatLiteral") and ctx.floatLiteral():
            return self.visit(ctx.floatLiteral())
        return 0.0

    def visitBooleanArgument(self, ctx):
        if hasattr(ctx, "booleanLiteral") and ctx.booleanLiteral():
            return self.visit(ctx.booleanLiteral())
        return False

    def visitTraversalPredicate(self, ctx):
        # 通用的谓词访问器，根据具体类型调用相应的方法
        # 避免无限递归，直接调用默认的 visitChildren
        return self.visitChildren(ctx)

    # 导航方法访问器
    def visitTraversalMethod_in(self, ctx: GremlinParser.TraversalMethod_inContext):
        params = []
        if ctx.stringNullableArgumentVarargs():
            result = self.visit(ctx.stringNullableArgumentVarargs())
            if result is not None:
                params = result
        self.traversal.add_step(Step("in", params))

    def visitTraversalMethod_both(self, ctx: GremlinParser.TraversalMethod_bothContext):
        params = []
        if ctx.stringNullableArgumentVarargs():
            result = self.visit(ctx.stringNullableArgumentVarargs())
            if result is not None:
                params = result
        self.traversal.add_step(Step("both", params))

    def visitTraversalMethod_bothE(self, ctx: GremlinParser.TraversalMethod_bothEContext):
        params = []
        if ctx.stringNullableArgumentVarargs():
            result = self.visit(ctx.stringNullableArgumentVarargs())
            if result is not None:
                params = result
        self.traversal.add_step(Step("bothE", params))

    def visitTraversalMethod_bothV(self, ctx: GremlinParser.TraversalMethod_bothVContext):
        self.traversal.add_step(Step("bothV", []))

    def visitTraversalMethod_inE(self, ctx: GremlinParser.TraversalMethod_inEContext):
        params = []
        if ctx.stringNullableArgumentVarargs():
            result = self.visit(ctx.stringNullableArgumentVarargs())
            if result is not None:
                params = result
        self.traversal.add_step(Step("inE", params))

    def visitTraversalMethod_outE(self, ctx: GremlinParser.TraversalMethod_outEContext):
        params = []
        if ctx.stringNullableArgumentVarargs():
            result = self.visit(ctx.stringNullableArgumentVarargs())
            if result is not None:
                params = result
        self.traversal.add_step(Step("outE", params))

    def visitTraversalMethod_inV(self, ctx: GremlinParser.TraversalMethod_inVContext):
        self.traversal.add_step(Step("inV", []))

    def visitTraversalMethod_outV(self, ctx: GremlinParser.TraversalMethod_outVContext):
        self.traversal.add_step(Step("outV", []))

    def visitTraversalMethod_otherV(self, ctx: GremlinParser.TraversalMethod_otherVContext):
        self.traversal.add_step(Step("otherV", []))

    # 更多过滤方法访问器
    # where的特定变体（删除了冗余的通用方法）
    def visitTraversalMethod_where_P(self, ctx):
        """where(Predicate)变体"""
        params = []
        if hasattr(ctx, "traversalPredicate") and ctx.traversalPredicate():
            params.append(self.visit(ctx.traversalPredicate()))
        self.traversal.add_step(Step("where", params))

    def visitTraversalMethod_where_String_P(self, ctx):
        """where(String, Predicate)变体"""
        params = []
        if hasattr(ctx, "stringLiteral") and ctx.stringLiteral():
            params.append(self.visit(ctx.stringLiteral()))
        if hasattr(ctx, "traversalPredicate") and ctx.traversalPredicate():
            params.append(self.visit(ctx.traversalPredicate()))
        self.traversal.add_step(Step("where", params))

    def visitTraversalMethod_where_Traversal(self, ctx):
        """where(Traversal)变体 - 接受嵌套遍历"""
        params = []
        if hasattr(ctx, "nestedTraversal") and ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("where", params))

    # filter的特定变体（删除了冗余的通用方法）
    def visitTraversalMethod_filter_Predicate(self, ctx):
        """filter(Predicate)变体"""
        params = []
        if hasattr(ctx, "traversalPredicate") and ctx.traversalPredicate():
            params.append(self.visit(ctx.traversalPredicate()))
        self.traversal.add_step(Step("filter", params))

    def visitTraversalMethod_filter_Traversal(self, ctx):
        """filter(Traversal)变体 - 接受嵌套遍历"""
        params = []
        if hasattr(ctx, "nestedTraversal") and ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("filter", params))

    def visitTraversalMethod_is(self, ctx):
        params = []
        if hasattr(ctx, "genericArgument") and ctx.genericArgument():
            params.append(self.visit(ctx.genericArgument()))
        elif hasattr(ctx, "traversalPredicate") and ctx.traversalPredicate():
            params.append(self.visit(ctx.traversalPredicate()))
        self.traversal.add_step(Step("is", params))

    def visitTraversalMethod_not(self, ctx):
        params = []
        if hasattr(ctx, "nestedTraversal") and ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("not", params))

    # ========== 高优先级缺失方法 - 2024修复 ==========

    # select的特定变体
    def visitTraversalMethod_select_Traversal(self, ctx):
        """select(Traversal)变体"""
        params = []
        if hasattr(ctx, "nestedTraversal") and ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("select", params))

    def visitTraversalMethod_select_Pop_String(self, ctx):
        """select(Pop, String)变体"""
        params = []
        if hasattr(ctx, "traversalPop") and ctx.traversalPop():
            params.append(self.visit(ctx.traversalPop()))
        if hasattr(ctx, "stringLiteral") and ctx.stringLiteral():
            params.append(self.visit(ctx.stringLiteral()))
        self.traversal.add_step(Step("select", params))

    def visitTraversalMethod_select_Pop_Traversal(self, ctx):
        """select(Pop, Traversal)变体"""
        params = []
        if hasattr(ctx, "traversalPop") and ctx.traversalPop():
            params.append(self.visit(ctx.traversalPop()))
        if hasattr(ctx, "nestedTraversal") and ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("select", params))

    # from的特定变体
    def visitTraversalMethod_from_String(self, ctx):
        """from(String)变体"""
        params = []
        if hasattr(ctx, "stringLiteral") and ctx.stringLiteral():
            params.append(self.visit(ctx.stringLiteral()))
        self.traversal.add_step(Step("from", params))

    def visitTraversalMethod_from_Vertex(self, ctx):
        """from(Vertex)变体"""
        params = []
        if hasattr(ctx, "structureVertex") and ctx.structureVertex():
            params.append(self.visit(ctx.structureVertex()))
        self.traversal.add_step(Step("from", params))

    def visitTraversalMethod_from_Traversal(self, ctx):
        """from(Traversal)变体"""
        params = []
        if hasattr(ctx, "nestedTraversal") and ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("from", params))

    # to的特定变体
    def visitTraversalMethod_to_String(self, ctx):
        """to(String)变体"""
        params = []
        if hasattr(ctx, "stringLiteral") and ctx.stringLiteral():
            params.append(self.visit(ctx.stringLiteral()))
        self.traversal.add_step(Step("to", params))

    def visitTraversalMethod_to_Vertex(self, ctx):
        """to(Vertex)变体"""
        params = []
        if hasattr(ctx, "structureVertex") and ctx.structureVertex():
            params.append(self.visit(ctx.structureVertex()))
        self.traversal.add_step(Step("to", params))

    def visitTraversalMethod_to_Traversal(self, ctx):
        """to(Traversal)变体"""
        params = []
        if hasattr(ctx, "nestedTraversal") and ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("to", params))

    # emit的特定变体
    def visitTraversalMethod_emit_Predicate(self, ctx):
        """emit(Predicate)变体"""
        params = []
        if hasattr(ctx, "traversalPredicate") and ctx.traversalPredicate():
            params.append(self.visit(ctx.traversalPredicate()))
        self.traversal.add_step(Step("emit", params))

    def visitTraversalMethod_emit_Traversal(self, ctx):
        """emit(Traversal)变体"""
        params = []
        if hasattr(ctx, "nestedTraversal") and ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("emit", params))

    # by的特定变体
    def visitTraversalMethod_by_Empty(self, ctx):
        """by()变体 - 无参数"""
        self.traversal.add_step(Step("by", []))

    def visitTraversalMethod_by_Function(self, ctx):
        """by(Function)变体"""
        params = []
        if hasattr(ctx, "traversalFunction") and ctx.traversalFunction():
            params.append(self.visit(ctx.traversalFunction()))
        self.traversal.add_step(Step("by", params))

    def visitTraversalMethod_by_Order(self, ctx):
        """by(Order)变体"""
        params = []
        if hasattr(ctx, "traversalOrder") and ctx.traversalOrder():
            params.append(self.visit(ctx.traversalOrder()))
        self.traversal.add_step(Step("by", params))

    def visitTraversalMethod_by_T(self, ctx):
        """by(T)变体"""
        params = []
        if hasattr(ctx, "traversalT") and ctx.traversalT():
            params.append(self.visit(ctx.traversalT()))
        self.traversal.add_step(Step("by", params))

    # tail的特定变体
    def visitTraversalMethod_tail_Scope(self, ctx):
        """tail(Scope)变体"""
        params = []
        if hasattr(ctx, "traversalScope") and ctx.traversalScope():
            params.append(self.visit(ctx.traversalScope()))
        self.traversal.add_step(Step("tail", params))

    # barrier的特定变体
    def visitTraversalMethod_barrier_int(self, ctx):
        """barrier(int)变体"""
        params = []
        if hasattr(ctx, "integerLiteral") and ctx.integerLiteral():
            params.append(self.visit(ctx.integerLiteral()))
        self.traversal.add_step(Step("barrier", params))

    # V和E的实现
    def visitTraversalMethod_V(self, ctx):
        """V()方法 - 获取顶点"""
        params = []
        if hasattr(ctx, "genericArgumentVarargs") and ctx.genericArgumentVarargs():
            args = self.visit(ctx.genericArgumentVarargs())
            if args:
                params.extend(args if isinstance(args, list) else [args])
        self.traversal.add_step(Step("V", params))

    def visitTraversalMethod_E(self, ctx):
        """E()方法 - 获取边"""
        params = []
        if hasattr(ctx, "genericArgumentVarargs") and ctx.genericArgumentVarargs():
            args = self.visit(ctx.genericArgumentVarargs())
            if args:
                params.extend(args if isinstance(args, list) else [args])
        self.traversal.add_step(Step("E", params))

    # choose的所有变体
    def visitTraversalMethod_choose_Function(self, ctx):
        """choose(Function)变体"""
        params = []
        if hasattr(ctx, "traversalFunction") and ctx.traversalFunction():
            params.append(RawGremlinToken(ctx.traversalFunction().getText()))
        self.traversal.add_step(Step("choose", params))

    def visitTraversalMethod_choose_Traversal_Traversal(self, ctx):
        """choose(Traversal, Traversal)变体"""
        params = []
        # 获取所有nestedTraversal
        if hasattr(ctx, "nestedTraversal"):
            traversals = ctx.nestedTraversal()
            if traversals:
                if isinstance(traversals, list):
                    for t in traversals:
                        params.append(self.visit(t))
                else:
                    params.append(self.visit(traversals))
        self.traversal.add_step(Step("choose", params))

    def visitTraversalMethod_choose_Predicate_Traversal(self, ctx):
        """choose(Predicate, Traversal)变体"""
        params = []
        if hasattr(ctx, "traversalPredicate") and ctx.traversalPredicate():
            params.append(self.visit(ctx.traversalPredicate()))
        if hasattr(ctx, "nestedTraversal") and ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("choose", params))

    def visitTraversalMethod_choose_Predicate_Traversal_Traversal(self, ctx):
        """choose(Predicate, Traversal, Traversal)变体 - 三参数版本"""
        params = []
        if hasattr(ctx, "traversalPredicate") and ctx.traversalPredicate():
            params.append(self.visit(ctx.traversalPredicate()))
        # 获取两个nestedTraversal参数
        if hasattr(ctx, "nestedTraversal"):
            traversals = ctx.nestedTraversal()
            if traversals:
                if isinstance(traversals, list):
                    for t in traversals:
                        params.append(self.visit(t))
                else:
                    params.append(self.visit(traversals))
        self.traversal.add_step(Step("choose", params))

    def visitTraversalMethod_choose_Traversal_Traversal_Traversal(self, ctx):
        """choose(Traversal, Traversal, Traversal)变体 - 三遍历版本"""
        params = []
        if hasattr(ctx, "nestedTraversal"):
            traversals = ctx.nestedTraversal()
            if traversals:
                if isinstance(traversals, list):
                    for t in traversals:
                        params.append(self.visit(t))
                else:
                    params.append(self.visit(traversals))
        self.traversal.add_step(Step("choose", params))

    # flatMap方法
    def visitTraversalMethod_flatMap(self, ctx):
        """flatMap(Traversal)方法"""
        params = []
        if hasattr(ctx, "nestedTraversal") and ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("flatMap", params))

    # is的特定变体
    def visitTraversalMethod_is_Object(self, ctx):
        """is(Object)变体"""
        params = []
        if hasattr(ctx, "genericArgument") and ctx.genericArgument():
            params.append(self.visit(ctx.genericArgument()))
        self.traversal.add_step(Step("is", params))

    def visitTraversalMethod_is_P(self, ctx):
        """is(Predicate)变体"""
        params = []
        if hasattr(ctx, "traversalPredicate") and ctx.traversalPredicate():
            params.append(self.visit(ctx.traversalPredicate()))
        self.traversal.add_step(Step("is", params))

    # ========== 高优先级缺失方法结束 ==========

    def visitTraversalMethod_hasLabel(self, ctx):
        params = (
            self.visit(ctx.stringNullableArgumentVarargs())
            if hasattr(ctx, "stringNullableArgumentVarargs") and ctx.stringNullableArgumentVarargs()
            else []
        )
        self.traversal.add_step(Step("hasLabel", params))

    def visitTraversalMethod_hasLabel_P(self, ctx):
        predicate = self.visit(ctx.traversalPredicate())
        self.traversal.add_step(Step("hasLabel", [predicate]))

    def visitTraversalMethod_hasLabel_String_String(self, ctx):
        params = []
        if ctx.stringNullableArgument():
            params.append(self.visit(ctx.stringNullableArgument()))
        if ctx.stringNullableArgumentVarargs():
            params.extend(self.visit(ctx.stringNullableArgumentVarargs()))
        self.traversal.add_step(Step("hasLabel", params))

    def visitTraversalMethod_hasId(self, ctx):
        params = (
            self.visit(ctx.genericArgumentVarargs())
            if hasattr(ctx, "genericArgumentVarargs") and ctx.genericArgumentVarargs()
            else []
        )
        self.traversal.add_step(Step("hasId", params))

    def visitTraversalMethod_hasId_Object_Object(self, ctx):
        params = []
        if ctx.genericArgument():
            params.append(self.visit(ctx.genericArgument()))
        if ctx.genericArgumentVarargs():
            params.extend(self.visit(ctx.genericArgumentVarargs()))
        self.traversal.add_step(Step("hasId", params))

    def visitTraversalMethod_hasId_P(self, ctx):
        predicate = self.visit(ctx.traversalPredicate())
        self.traversal.add_step(Step("hasId", [predicate]))

    def visitTraversalMethod_hasKey(self, ctx):
        params = (
            self.visit(ctx.stringNullableArgumentVarargs())
            if hasattr(ctx, "stringNullableArgumentVarargs") and ctx.stringNullableArgumentVarargs()
            else []
        )
        self.traversal.add_step(Step("hasKey", params))

    def visitTraversalMethod_hasKey_P(self, ctx):
        predicate = self.visit(ctx.traversalPredicate())
        self.traversal.add_step(Step("hasKey", [predicate]))

    def visitTraversalMethod_hasKey_String_String(self, ctx):
        params = []
        if ctx.stringNullableLiteral():
            params.append(self.visit(ctx.stringNullableLiteral()))
        if ctx.stringNullableLiteralVarargs():
            params.extend(self.visit(ctx.stringNullableLiteralVarargs()))
        self.traversal.add_step(Step("hasKey", params))

    def visitTraversalMethod_hasValue(self, ctx):
        params = (
            self.visit(ctx.genericArgumentVarargs())
            if hasattr(ctx, "genericArgumentVarargs") and ctx.genericArgumentVarargs()
            else []
        )
        self.traversal.add_step(Step("hasValue", params))

    def visitTraversalMethod_hasValue_Object_Object(self, ctx):
        params = []
        if ctx.genericArgument():
            params.append(self.visit(ctx.genericArgument()))
        if ctx.genericArgumentVarargs():
            params.extend(self.visit(ctx.genericArgumentVarargs()))
        self.traversal.add_step(Step("hasValue", params))

    def visitTraversalMethod_hasValue_P(self, ctx):
        predicate = self.visit(ctx.traversalPredicate())
        self.traversal.add_step(Step("hasValue", [predicate]))

    # 删除操作访问器
    def visitTraversalMethod_drop(self, ctx):
        self.traversal.add_step(Step("drop", []))

    # Call方法的各种变体支持 (traversalMethod版本)
    def visitTraversalMethod_call_string(self, ctx: GremlinParser.TraversalMethod_call_stringContext):
        """处理 .call('methodName') 单字符串参数调用"""
        params = []
        if ctx.stringArgument():
            params.append(self.visit(ctx.stringArgument()))
        self.traversal.add_step(Step("call", params))

    def visitTraversalMethod_call_string_map(self, ctx: GremlinParser.TraversalMethod_call_string_mapContext):
        """处理 .call('methodName', map) 字符串+映射参数调用"""
        params = []
        if ctx.stringArgument():
            params.append(self.visit(ctx.stringArgument()))
        if ctx.genericLiteralMap():
            params.append(self.visit(ctx.genericLiteralMap()))
        self.traversal.add_step(Step("call", params))

    def visitTraversalMethod_call_string_traversal(
        self, ctx: GremlinParser.TraversalMethod_call_string_traversalContext
    ):
        """处理 .call('methodName', traversal) 字符串+遍历参数调用"""
        params = []
        if ctx.stringArgument():
            params.append(self.visit(ctx.stringArgument()))
        if ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("call", params))

    def visitTraversalMethod_call_string_map_traversal(
        self, ctx: GremlinParser.TraversalMethod_call_string_map_traversalContext
    ):
        """处理 .call('methodName', map, traversal) 字符串+映射+遍历参数调用"""
        params = []
        if ctx.stringArgument():
            params.append(self.visit(ctx.stringArgument()))
        if ctx.genericLiteralMap():
            params.append(self.visit(ctx.genericLiteralMap()))
        if ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("call", params))

    # 更多修改操作访问器
    def visitTraversalMethod_addE_String(self, ctx):
        params = []
        if ctx.stringArgument():
            params.append(self.visit(ctx.stringArgument()))
        self.traversal.add_step(Step("addE", params))

    def visitTraversalMethod_addE_Traversal(self, ctx):
        params = []
        if ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("addE", params))

    def visitTraversalMethod_addV_Empty(self, ctx):
        self.traversal.add_step(Step("addV", []))

    def visitTraversalMethod_addV_String(self, ctx):
        params = []
        if ctx.stringArgument():
            params.append(self.visit(ctx.stringArgument()))
        self.traversal.add_step(Step("addV", params))

    def visitTraversalMethod_addV_Traversal(self, ctx):
        params = []
        if ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("addV", params))

    def visitTraversalMethod_from(self, ctx):
        params = []
        if hasattr(ctx, "stringArgument") and ctx.stringArgument():
            params.append(self.visit(ctx.stringArgument()))
        elif hasattr(ctx, "nestedTraversal") and ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("from", params))

    def visitTraversalMethod_to(self, ctx):
        params = []
        if hasattr(ctx, "stringArgument") and ctx.stringArgument():
            params.append(self.visit(ctx.stringArgument()))
        elif hasattr(ctx, "nestedTraversal") and ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("to", params))

    # With方法的各种变体支持
    def visitTraversalMethod_with_String(self, ctx: GremlinParser.TraversalMethod_with_StringContext):
        """处理 .with('key') 单字符串参数调用"""
        params = []
        # 查找StringLiteralContext子节点
        for child in ctx.children:
            if hasattr(child, "getRuleIndex") and "StringLiteral" in type(child).__name__:
                string_val = child.getText()
                # 移除引号
                if (string_val.startswith('"') and string_val.endswith('"')) or (
                    string_val.startswith("'") and string_val.endswith("'")
                ):
                    string_val = string_val[1:-1]
                params.append(string_val)
                break
        self.traversal.add_step(Step("with", params))

    def visitTraversalMethod_with_String_Object(self, ctx: GremlinParser.TraversalMethod_with_String_ObjectContext):
        """处理 .with('key', value) 字符串+对象参数调用"""
        params = []
        # 查找StringLiteralContext和GenericArgumentContext子节点
        for child in ctx.children:
            if hasattr(child, "getRuleIndex"):
                if "StringLiteral" in type(child).__name__:
                    string_val = child.getText()
                    # 移除引号
                    if (string_val.startswith('"') and string_val.endswith('"')) or (
                        string_val.startswith("'") and string_val.endswith("'")
                    ):
                        string_val = string_val[1:-1]
                    params.append(string_val)
                elif "GenericArgument" in type(child).__name__:
                    # 处理GenericArgument，可能包含字符串或数字
                    arg_text = child.getText()
                    # 如果是字符串，移除引号
                    if (arg_text.startswith('"') and arg_text.endswith('"')) or (
                        arg_text.startswith("'") and arg_text.endswith("'")
                    ):
                        arg_text = arg_text[1:-1]
                    params.append(arg_text)
        self.traversal.add_step(Step("with", params))

    # TraversalSourceSelfMethod的with方法支持
    def visitTraversalSourceSelfMethod_with(self, ctx: GremlinParser.TraversalSourceSelfMethod_withContext):
        """处理 g.with() 方法"""
        params = []
        if hasattr(ctx, "stringLiteral") and ctx.stringLiteral():
            params.append(self.visit(ctx.stringLiteral()))
        if hasattr(ctx, "genericArgument") and ctx.genericArgument():
            params.append(self.visit(ctx.genericArgument()))
        self.traversal.add_step(Step("with", params))

    def visitTraversalSourceSelfMethod_withSideEffect(
        self, ctx: GremlinParser.TraversalSourceSelfMethod_withSideEffectContext
    ):
        """处理 g.withSideEffect() 方法"""
        params = []
        if hasattr(ctx, "stringLiteral") and ctx.stringLiteral():
            params.append(self.visit(ctx.stringLiteral()))
        if hasattr(ctx, "genericArgument") and ctx.genericArgument():
            params.append(self.visit(ctx.genericArgument()))
        self.traversal.add_step(Step("withSideEffect", params))

    def visitTraversalSourceSelfMethod_withBulk(self, ctx: GremlinParser.TraversalSourceSelfMethod_withBulkContext):
        """处理 g.withBulk() 方法"""
        params = []
        if hasattr(ctx, "booleanArgument") and ctx.booleanArgument():
            params.append(self.visit(ctx.booleanArgument()))
        self.traversal.add_step(Step("withBulk", params))

    def visitTraversalSourceSelfMethod_withPath(self, ctx: GremlinParser.TraversalSourceSelfMethod_withPathContext):
        """处理 g.withPath() 方法"""
        self.traversal.add_step(Step("withPath", []))

    def visitTraversalSourceSelfMethod_withSack(self, ctx: GremlinParser.TraversalSourceSelfMethod_withSackContext):
        """处理 g.withSack() 方法"""
        params = []
        if hasattr(ctx, "genericArgument") and ctx.genericArgument():
            params.append(self.visit(ctx.genericArgument()))
        if hasattr(ctx, "traversalBiFunction") and ctx.traversalBiFunction():
            params.append(self.visit(ctx.traversalBiFunction()))
        self.traversal.add_step(Step("withSack", params))

    def visitTraversalSourceSelfMethod_withStrategies(
        self, ctx: GremlinParser.TraversalSourceSelfMethod_withStrategiesContext
    ):
        """处理 g.withStrategies() 方法"""
        params = []
        if hasattr(ctx, "traversalStrategy") and ctx.traversalStrategy():
            params.append(self.visit(ctx.traversalStrategy()))
        self.traversal.add_step(Step("withStrategies", params))

    def visitTraversalSourceSelfMethod_withoutStrategies(
        self, ctx: GremlinParser.TraversalSourceSelfMethod_withoutStrategiesContext
    ):
        """处理 g.withoutStrategies() 方法"""
        params = []
        if hasattr(ctx, "classType") and ctx.classType():
            params.append(self.visit(ctx.classType()))
        self.traversal.add_step(Step("withoutStrategies", params))

    # SpawnMethod缺失方法
    def visitTraversalSourceSpawnMethod_mergeE_Map(self, ctx):
        """处理 g.mergeE(map) 方法

        TODO: 完整实现 Map 参数解析
        当前实现：忽略 Map 参数内容，只记录步骤名称
        完整实现需要：
        1. 解析 genericMapNullableArgument (如 [:] 或 [(T.id): 1])
        2. 提取 Map 中的键值对
        3. 将 Map 对象作为参数传递给 Step
        4. 在 TraversalGenerator 中支持 Map 参数的泛化

        参考：base_v2/MAP_PARAMETER_FIX_PLAN.md
        """
        params = []
        # Map参数暂时简化处理 - 见上方 TODO
        self.traversal.add_step(Step("mergeE", params))

    def visitTraversalSourceSpawnMethod_mergeE_Traversal(self, ctx):
        """处理 g.mergeE(traversal) 方法"""
        params = []
        if hasattr(ctx, "nestedTraversal") and ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("mergeE", params))

    def visitTraversalSourceSpawnMethod_mergeV_Map(self, ctx):
        """处理 g.mergeV(map) 方法

        TODO: 完整实现 Map 参数解析
        当前实现：忽略 Map 参数内容，只记录步骤名称
        完整实现需要：
        1. 解析 genericMapNullableArgument (如 [:] 或 [(T.id): 1])
        2. 提取 Map 中的键值对
        3. 将 Map 对象作为参数传递给 Step
        4. 在 TraversalGenerator 中支持 Map 参数的泛化

        参考：base_v2/MAP_PARAMETER_FIX_PLAN.md
        """
        params = []
        # Map参数暂时简化处理 - 见上方 TODO
        self.traversal.add_step(Step("mergeV", params))

    def visitTraversalSourceSpawnMethod_mergeV_Traversal(self, ctx):
        """处理 g.mergeV(traversal) 方法"""
        params = []
        if hasattr(ctx, "nestedTraversal") and ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("mergeV", params))

    def visitTraversalMethod_mergeE_empty(self, ctx):
        """处理 .mergeE() 无参数方法"""
        self.traversal.add_step(Step("mergeE", []))

    def visitTraversalMethod_mergeE_Map(self, ctx):
        """处理 .mergeE(map) 方法

        TODO: 完整实现 Map 参数解析
        当前实现：忽略 Map 参数内容，只记录步骤名称
        完整实现需要：
        1. 解析 genericMapNullableArgument (如 [:] 或 [(T.id): 1])
        2. 提取 Map 中的键值对
        3. 将 Map 对象作为参数传递给 Step
        4. 在 TraversalGenerator 中支持 Map 参数的泛化

        参考：base_v2/MAP_PARAMETER_FIX_PLAN.md
        """
        params = []
        # Map参数暂时简化处理 - 见上方 TODO
        self.traversal.add_step(Step("mergeE", params))

    def visitTraversalMethod_mergeE_Traversal(self, ctx):
        """处理 .mergeE(traversal) 方法"""
        params = []
        if hasattr(ctx, "nestedTraversal") and ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("mergeE", params))

    def visitTraversalMethod_mergeV_empty(self, ctx):
        """处理 .mergeV() 无参数方法"""
        self.traversal.add_step(Step("mergeV", []))

    def visitTraversalMethod_mergeV_Map(self, ctx):
        """处理 .mergeV(map) 方法

        TODO: 完整实现 Map 参数解析
        当前实现：忽略 Map 参数内容，只记录步骤名称
        完整实现需要：
        1. 解析 genericMapNullableArgument (如 [:] 或 [(T.id): 1])
        2. 提取 Map 中的键值对
        3. 将 Map 对象作为参数传递给 Step
        4. 在 TraversalGenerator 中支持 Map 参数的泛化

        参考：base_v2/MAP_PARAMETER_FIX_PLAN.md
        """
        params = []
        # Map参数暂时简化处理 - 见上方 TODO
        self.traversal.add_step(Step("mergeV", params))

    def visitTraversalMethod_mergeV_Traversal(self, ctx):
        """处理 .mergeV(traversal) 方法"""
        params = []
        if hasattr(ctx, "nestedTraversal") and ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("mergeV", params))

    def visitTraversalSourceSpawnMethod_union(self, ctx: GremlinParser.TraversalSourceSpawnMethod_unionContext):
        """处理 g.union() 方法"""
        params = []
        if hasattr(ctx, "nestedTraversalVarargs") and ctx.nestedTraversalVarargs():
            params = self.visit(ctx.nestedTraversalVarargs())
        self.traversal.add_step(Step("union", params))

    # 转换方法访问器
    def visitTraversalMethod_properties(self, ctx):
        params = (
            self.visit(ctx.stringNullableLiteralVarargs())
            if hasattr(ctx, "stringNullableLiteralVarargs") and ctx.stringNullableLiteralVarargs()
            else []
        )
        self.traversal.add_step(Step("properties", params))

    def visitTraversalMethod_select(self, ctx):
        params = []
        if hasattr(ctx, "stringNullableArgumentVarargs") and ctx.stringNullableArgumentVarargs():
            params = self.visit(ctx.stringNullableArgumentVarargs())
        elif hasattr(ctx, "stringArgument") and ctx.stringArgument():
            params.append(self.visit(ctx.stringArgument()))
        self.traversal.add_step(Step("select", params))

    def visitTraversalMethod_select_String_String_String(
        self, ctx: GremlinParser.TraversalMethod_select_String_String_StringContext
    ):
        """处理 .select('key1', 'key2', 'key3') 多字符串参数调用"""
        params = []
        # 获取前两个 stringLiteral
        if hasattr(ctx, "stringLiteral") and ctx.stringLiteral():
            literals = ctx.stringLiteral()
            if isinstance(literals, list):
                for lit in literals:
                    params.append(self.visit(lit))
            else:
                params.append(self.visit(literals))
        # 获取额外的参数（第三个及以后）
        if hasattr(ctx, "stringNullableLiteralVarargs") and ctx.stringNullableLiteralVarargs():
            extra_params = self.visit(ctx.stringNullableLiteralVarargs())
            if extra_params:
                params.extend(extra_params if isinstance(extra_params, list) else [extra_params])
        self.traversal.add_step(Step("select", params))

    def visitTraversalMethod_project(self, ctx):
        """处理project()方法"""
        params = []
        # 第一个参数是必需的stringLiteral
        if hasattr(ctx, "stringLiteral") and ctx.stringLiteral():
            params.append(self.visit(ctx.stringLiteral()))
        # 后面可选的stringNullableLiteralVarargs
        if hasattr(ctx, "stringNullableLiteralVarargs") and ctx.stringNullableLiteralVarargs():
            varargs = self.visit(ctx.stringNullableLiteralVarargs())
            if varargs:
                params.extend(varargs)
        self.traversal.add_step(Step("project", params))

    def visitTraversalMethod_valueMap(self, ctx):
        params = []
        if hasattr(ctx, "stringNullableLiteralVarargs") and ctx.stringNullableLiteralVarargs():
            params = self.visit(ctx.stringNullableLiteralVarargs())
        elif hasattr(ctx, "booleanArgument") and ctx.booleanArgument():
            params.append(self.visit(ctx.booleanArgument()))
        self.traversal.add_step(Step("valueMap", params))

    def visitTraversalMethod_elementMap(self, ctx):
        params = (
            self.visit(ctx.stringNullableLiteralVarargs())
            if hasattr(ctx, "stringNullableLiteralVarargs") and ctx.stringNullableLiteralVarargs()
            else []
        )
        self.traversal.add_step(Step("elementMap", params))

    def visitTraversalMethod_label(self, ctx):
        self.traversal.add_step(Step("label", []))

    def visitTraversalMethod_id(self, ctx):
        self.traversal.add_step(Step("id", []))

    def visitTraversalMethod_key(self, ctx):
        self.traversal.add_step(Step("key", []))

    def visitTraversalMethod_value(self, ctx):
        self.traversal.add_step(Step("value", []))

    # 聚合方法访问器
    # 聚合方法的正确实现 - 使用正确的Context类型
    def visitTraversalMethod_count_Empty(self, ctx):
        """处理无参数的count()方法"""
        self.traversal.add_step(Step("count", []))

    def visitTraversalMethod_count_Scope(self, ctx):
        """处理有参数的count()方法"""
        # 处理scope参数
        params = []
        if hasattr(ctx, "traversalScope") and ctx.traversalScope():
            params.append(self.visit(ctx.traversalScope()))
        self.traversal.add_step(Step("count", params))

    def visitTraversalMethod_sum_Empty(self, ctx):
        """处理无参数的sum()方法"""
        self.traversal.add_step(Step("sum", []))

    def visitTraversalMethod_sum_Scope(self, ctx):
        """处理有参数的sum()方法"""
        params = []
        if hasattr(ctx, "traversalScope") and ctx.traversalScope():
            params.append(self.visit(ctx.traversalScope()))
        self.traversal.add_step(Step("sum", params))

    def visitTraversalMethod_mean_Empty(self, ctx):
        """处理无参数的mean()方法"""
        self.traversal.add_step(Step("mean", []))

    def visitTraversalMethod_mean_Scope(self, ctx):
        """处理有参数的mean()方法"""
        params = []
        if hasattr(ctx, "traversalScope") and ctx.traversalScope():
            params.append(self.visit(ctx.traversalScope()))
        self.traversal.add_step(Step("mean", params))

    def visitTraversalMethod_max_Empty(self, ctx):
        """处理无参数的max()方法"""
        self.traversal.add_step(Step("max", []))

    def visitTraversalMethod_max_Scope(self, ctx):
        """处理有参数的max()方法"""
        params = []
        if hasattr(ctx, "traversalScope") and ctx.traversalScope():
            params.append(self.visit(ctx.traversalScope()))
        self.traversal.add_step(Step("max", params))

    def visitTraversalMethod_min_Empty(self, ctx):
        """处理无参数的min()方法"""
        self.traversal.add_step(Step("min", []))

    def visitTraversalMethod_min_Scope(self, ctx):
        """处理有参数的min()方法"""
        params = []
        if hasattr(ctx, "traversalScope") and ctx.traversalScope():
            params.append(self.visit(ctx.traversalScope()))
        self.traversal.add_step(Step("min", params))

    def visitTraversalMethod_fold_Empty(self, ctx):
        """处理无参数的fold()方法"""
        self.traversal.add_step(Step("fold", []))

    def visitTraversalMethod_unfold(self, ctx):
        self.traversal.add_step(Step("unfold", []))

    # 分组方法
    def visitTraversalMethod_group_Empty(self, ctx):
        """处理无参数的group()方法"""
        self.traversal.add_step(Step("group", []))

    def visitTraversalMethod_group_String(self, ctx):
        """处理带标签参数的group(string)方法"""
        params = []
        if hasattr(ctx, "stringLiteral") and ctx.stringLiteral():
            params.append(self.visit(ctx.stringLiteral()))
        self.traversal.add_step(Step("group", params))

    def visitTraversalMethod_groupCount_Empty(self, ctx):
        """处理无参数的groupCount()方法"""
        self.traversal.add_step(Step("groupCount", []))

    def visitTraversalMethod_groupCount_String(self, ctx):
        """处理带标签参数的groupCount(string)方法"""
        params = []
        if hasattr(ctx, "stringLiteral") and ctx.stringLiteral():
            params.append(self.visit(ctx.stringLiteral()))
        self.traversal.add_step(Step("groupCount", params))

    # 排序和限制方法访问器
    # 排序和限制方法的正确实现
    def visitTraversalMethod_order_Empty(self, ctx):
        """处理无参数的order()方法"""
        self.traversal.add_step(Step("order", []))

    def visitTraversalMethod_order_Scope(self, ctx):
        """处理有参数的order()方法"""
        params = []
        if hasattr(ctx, "traversalScope") and ctx.traversalScope():
            params.append(self.visit(ctx.traversalScope()))
        self.traversal.add_step(Step("order", params))

    def visitTraversalMethod_by_String(self, ctx):
        """处理by(string)方法"""
        params = []
        if hasattr(ctx, "stringArgument") and ctx.stringArgument():
            params.append(self.visit(ctx.stringArgument()))
        elif hasattr(ctx, "stringLiteral") and ctx.stringLiteral():
            params.append(self.visit(ctx.stringLiteral()))
        self.traversal.add_step(Step("by", params))

    def visitTraversalMethod_by_String_Comparator(self, ctx):
        """处理by(string, comparator)方法"""
        params = []
        if hasattr(ctx, "stringArgument") and ctx.stringArgument():
            params.append(self.visit(ctx.stringArgument()))
        elif hasattr(ctx, "stringLiteral") and ctx.stringLiteral():
            params.append(self.visit(ctx.stringLiteral()))
        if hasattr(ctx, "traversalComparator") and ctx.traversalComparator():
            params.append(self.visit(ctx.traversalComparator()))
        self.traversal.add_step(Step("by", params))

    def visitTraversalMethod_by_Traversal(self, ctx):
        """处理by(traversal)方法"""
        params = []
        if hasattr(ctx, "nestedTraversal") and ctx.nestedTraversal():
            params.append(self.visit(ctx.nestedTraversal()))
        self.traversal.add_step(Step("by", params))

    def visitTraversalMethod_range_long_long(self, ctx):
        """处理range(long, long)方法"""
        params = []
        if hasattr(ctx, "integerArgument"):
            for arg in ctx.integerArgument():
                params.append(self.visit(arg))
        self.traversal.add_step(Step("range", params))

    def visitTraversalMethod_skip_long(self, ctx):
        """处理skip(long)方法"""
        params = []
        if hasattr(ctx, "integerArgument") and ctx.integerArgument():
            params.append(self.visit(ctx.integerArgument()))
        self.traversal.add_step(Step("skip", params))

    def visitTraversalMethod_tail_long(self, ctx):
        """处理tail(long)方法"""
        params = []
        if hasattr(ctx, "integerArgument") and ctx.integerArgument():
            params.append(self.visit(ctx.integerArgument()))
        self.traversal.add_step(Step("tail", params))

    def visitTraversalMethod_sample_int(self, ctx):
        """处理sample(int)方法"""
        params = []
        if hasattr(ctx, "integerLiteral") and ctx.integerLiteral():
            params.append(self.visit(ctx.integerLiteral()))
        self.traversal.add_step(Step("sample", params))

    def visitTraversalMethod_coin(self, ctx):
        params = []
        if hasattr(ctx, "floatArgument") and ctx.floatArgument():
            params.append(self.visit(ctx.floatArgument()))
        self.traversal.add_step(Step("coin", params))

    # 分支和条件方法访问器


# 测试入口函数
def parse_gremlin_query(query_string: str) -> Traversal:
    """
    便捷的模块级函数，用于解析Gremlin查询字符串。

    Args:
        query_string (str): 要解析的 Gremlin 查询字符串

    Returns:
        Traversal: 包含步骤的解析后遍历对象
    """
    visitor = GremlinTransVisitor()
    return visitor.parse_and_visit(query_string)
