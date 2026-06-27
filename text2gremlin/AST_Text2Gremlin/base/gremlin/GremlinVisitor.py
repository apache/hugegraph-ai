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


# Generated from ./Gremlin.g4 by ANTLR 4.13.1
from antlr4 import *

if "." in __name__:
    from .GremlinParser import GremlinParser
else:
    from GremlinParser import GremlinParser

# This class defines a complete generic visitor for a parse tree produced by GremlinParser.


class GremlinVisitor(ParseTreeVisitor):
    # Visit a parse tree produced by GremlinParser#queryList.
    def visitQueryList(self, ctx: GremlinParser.QueryListContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#query.
    def visitQuery(self, ctx: GremlinParser.QueryContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#emptyQuery.
    def visitEmptyQuery(self, ctx: GremlinParser.EmptyQueryContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalSource.
    def visitTraversalSource(self, ctx: GremlinParser.TraversalSourceContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#transactionPart.
    def visitTransactionPart(self, ctx: GremlinParser.TransactionPartContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#rootTraversal.
    def visitRootTraversal(self, ctx: GremlinParser.RootTraversalContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalSourceSelfMethod.
    def visitTraversalSourceSelfMethod(self, ctx: GremlinParser.TraversalSourceSelfMethodContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalSourceSelfMethod_withBulk.
    def visitTraversalSourceSelfMethod_withBulk(self, ctx: GremlinParser.TraversalSourceSelfMethod_withBulkContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalSourceSelfMethod_withPath.
    def visitTraversalSourceSelfMethod_withPath(self, ctx: GremlinParser.TraversalSourceSelfMethod_withPathContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalSourceSelfMethod_withSack.
    def visitTraversalSourceSelfMethod_withSack(self, ctx: GremlinParser.TraversalSourceSelfMethod_withSackContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalSourceSelfMethod_withSideEffect.
    def visitTraversalSourceSelfMethod_withSideEffect(
        self, ctx: GremlinParser.TraversalSourceSelfMethod_withSideEffectContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalSourceSelfMethod_withStrategies.
    def visitTraversalSourceSelfMethod_withStrategies(
        self, ctx: GremlinParser.TraversalSourceSelfMethod_withStrategiesContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalSourceSelfMethod_withoutStrategies.
    def visitTraversalSourceSelfMethod_withoutStrategies(
        self, ctx: GremlinParser.TraversalSourceSelfMethod_withoutStrategiesContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalSourceSelfMethod_with.
    def visitTraversalSourceSelfMethod_with(self, ctx: GremlinParser.TraversalSourceSelfMethod_withContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalSourceSpawnMethod.
    def visitTraversalSourceSpawnMethod(self, ctx: GremlinParser.TraversalSourceSpawnMethodContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_addE.
    def visitTraversalSourceSpawnMethod_addE(self, ctx: GremlinParser.TraversalSourceSpawnMethod_addEContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_addV.
    def visitTraversalSourceSpawnMethod_addV(self, ctx: GremlinParser.TraversalSourceSpawnMethod_addVContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_E.
    def visitTraversalSourceSpawnMethod_E(self, ctx: GremlinParser.TraversalSourceSpawnMethod_EContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_V.
    def visitTraversalSourceSpawnMethod_V(self, ctx: GremlinParser.TraversalSourceSpawnMethod_VContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_inject.
    def visitTraversalSourceSpawnMethod_inject(self, ctx: GremlinParser.TraversalSourceSpawnMethod_injectContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_io.
    def visitTraversalSourceSpawnMethod_io(self, ctx: GremlinParser.TraversalSourceSpawnMethod_ioContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_mergeV_Map.
    def visitTraversalSourceSpawnMethod_mergeV_Map(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_mergeV_MapContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_mergeV_Traversal.
    def visitTraversalSourceSpawnMethod_mergeV_Traversal(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_mergeV_TraversalContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_mergeE_Map.
    def visitTraversalSourceSpawnMethod_mergeE_Map(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_mergeE_MapContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_mergeE_Traversal.
    def visitTraversalSourceSpawnMethod_mergeE_Traversal(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_mergeE_TraversalContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_call_empty.
    def visitTraversalSourceSpawnMethod_call_empty(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_call_emptyContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_call_string.
    def visitTraversalSourceSpawnMethod_call_string(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_call_stringContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_call_string_map.
    def visitTraversalSourceSpawnMethod_call_string_map(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_call_string_mapContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_call_string_traversal.
    def visitTraversalSourceSpawnMethod_call_string_traversal(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_call_string_traversalContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_call_string_map_traversal.
    def visitTraversalSourceSpawnMethod_call_string_map_traversal(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_call_string_map_traversalContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_union.
    def visitTraversalSourceSpawnMethod_union(self, ctx: GremlinParser.TraversalSourceSpawnMethod_unionContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#chainedTraversal.
    def visitChainedTraversal(self, ctx: GremlinParser.ChainedTraversalContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#nestedTraversal.
    def visitNestedTraversal(self, ctx: GremlinParser.NestedTraversalContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#terminatedTraversal.
    def visitTerminatedTraversal(self, ctx: GremlinParser.TerminatedTraversalContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod.
    def visitTraversalMethod(self, ctx: GremlinParser.TraversalMethodContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_V.
    def visitTraversalMethod_V(self, ctx: GremlinParser.TraversalMethod_VContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_E.
    def visitTraversalMethod_E(self, ctx: GremlinParser.TraversalMethod_EContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_addE_String.
    def visitTraversalMethod_addE_String(self, ctx: GremlinParser.TraversalMethod_addE_StringContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_addE_Traversal.
    def visitTraversalMethod_addE_Traversal(self, ctx: GremlinParser.TraversalMethod_addE_TraversalContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_addV_Empty.
    def visitTraversalMethod_addV_Empty(self, ctx: GremlinParser.TraversalMethod_addV_EmptyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_addV_String.
    def visitTraversalMethod_addV_String(self, ctx: GremlinParser.TraversalMethod_addV_StringContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_addV_Traversal.
    def visitTraversalMethod_addV_Traversal(self, ctx: GremlinParser.TraversalMethod_addV_TraversalContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_aggregate_Scope_String.
    def visitTraversalMethod_aggregate_Scope_String(
        self, ctx: GremlinParser.TraversalMethod_aggregate_Scope_StringContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_aggregate_String.
    def visitTraversalMethod_aggregate_String(self, ctx: GremlinParser.TraversalMethod_aggregate_StringContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_all_P.
    def visitTraversalMethod_all_P(self, ctx: GremlinParser.TraversalMethod_all_PContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_and.
    def visitTraversalMethod_and(self, ctx: GremlinParser.TraversalMethod_andContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_any_P.
    def visitTraversalMethod_any_P(self, ctx: GremlinParser.TraversalMethod_any_PContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_as.
    def visitTraversalMethod_as(self, ctx: GremlinParser.TraversalMethod_asContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_asDate.
    def visitTraversalMethod_asDate(self, ctx: GremlinParser.TraversalMethod_asDateContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_asString_Empty.
    def visitTraversalMethod_asString_Empty(self, ctx: GremlinParser.TraversalMethod_asString_EmptyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_asString_Scope.
    def visitTraversalMethod_asString_Scope(self, ctx: GremlinParser.TraversalMethod_asString_ScopeContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_barrier_Consumer.
    def visitTraversalMethod_barrier_Consumer(self, ctx: GremlinParser.TraversalMethod_barrier_ConsumerContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_barrier_Empty.
    def visitTraversalMethod_barrier_Empty(self, ctx: GremlinParser.TraversalMethod_barrier_EmptyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_barrier_int.
    def visitTraversalMethod_barrier_int(self, ctx: GremlinParser.TraversalMethod_barrier_intContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_both.
    def visitTraversalMethod_both(self, ctx: GremlinParser.TraversalMethod_bothContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_bothE.
    def visitTraversalMethod_bothE(self, ctx: GremlinParser.TraversalMethod_bothEContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_bothV.
    def visitTraversalMethod_bothV(self, ctx: GremlinParser.TraversalMethod_bothVContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_branch.
    def visitTraversalMethod_branch(self, ctx: GremlinParser.TraversalMethod_branchContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_by_Comparator.
    def visitTraversalMethod_by_Comparator(self, ctx: GremlinParser.TraversalMethod_by_ComparatorContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_by_Empty.
    def visitTraversalMethod_by_Empty(self, ctx: GremlinParser.TraversalMethod_by_EmptyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_by_Function.
    def visitTraversalMethod_by_Function(self, ctx: GremlinParser.TraversalMethod_by_FunctionContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_by_Function_Comparator.
    def visitTraversalMethod_by_Function_Comparator(
        self, ctx: GremlinParser.TraversalMethod_by_Function_ComparatorContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_by_Order.
    def visitTraversalMethod_by_Order(self, ctx: GremlinParser.TraversalMethod_by_OrderContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_by_String.
    def visitTraversalMethod_by_String(self, ctx: GremlinParser.TraversalMethod_by_StringContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_by_String_Comparator.
    def visitTraversalMethod_by_String_Comparator(self, ctx: GremlinParser.TraversalMethod_by_String_ComparatorContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_by_T.
    def visitTraversalMethod_by_T(self, ctx: GremlinParser.TraversalMethod_by_TContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_by_Traversal.
    def visitTraversalMethod_by_Traversal(self, ctx: GremlinParser.TraversalMethod_by_TraversalContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_by_Traversal_Comparator.
    def visitTraversalMethod_by_Traversal_Comparator(
        self, ctx: GremlinParser.TraversalMethod_by_Traversal_ComparatorContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_call_string.
    def visitTraversalMethod_call_string(self, ctx: GremlinParser.TraversalMethod_call_stringContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_call_string_map.
    def visitTraversalMethod_call_string_map(self, ctx: GremlinParser.TraversalMethod_call_string_mapContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_call_string_traversal.
    def visitTraversalMethod_call_string_traversal(
        self, ctx: GremlinParser.TraversalMethod_call_string_traversalContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_call_string_map_traversal.
    def visitTraversalMethod_call_string_map_traversal(
        self, ctx: GremlinParser.TraversalMethod_call_string_map_traversalContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_cap.
    def visitTraversalMethod_cap(self, ctx: GremlinParser.TraversalMethod_capContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_choose_Function.
    def visitTraversalMethod_choose_Function(self, ctx: GremlinParser.TraversalMethod_choose_FunctionContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_choose_Predicate_Traversal.
    def visitTraversalMethod_choose_Predicate_Traversal(
        self, ctx: GremlinParser.TraversalMethod_choose_Predicate_TraversalContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_choose_Predicate_Traversal_Traversal.
    def visitTraversalMethod_choose_Predicate_Traversal_Traversal(
        self, ctx: GremlinParser.TraversalMethod_choose_Predicate_Traversal_TraversalContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_choose_Traversal.
    def visitTraversalMethod_choose_Traversal(self, ctx: GremlinParser.TraversalMethod_choose_TraversalContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_choose_Traversal_Traversal.
    def visitTraversalMethod_choose_Traversal_Traversal(
        self, ctx: GremlinParser.TraversalMethod_choose_Traversal_TraversalContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_choose_Traversal_Traversal_Traversal.
    def visitTraversalMethod_choose_Traversal_Traversal_Traversal(
        self, ctx: GremlinParser.TraversalMethod_choose_Traversal_Traversal_TraversalContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_coalesce.
    def visitTraversalMethod_coalesce(self, ctx: GremlinParser.TraversalMethod_coalesceContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_coin.
    def visitTraversalMethod_coin(self, ctx: GremlinParser.TraversalMethod_coinContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_combine_Object.
    def visitTraversalMethod_combine_Object(self, ctx: GremlinParser.TraversalMethod_combine_ObjectContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_concat_Traversal_Traversal.
    def visitTraversalMethod_concat_Traversal_Traversal(
        self, ctx: GremlinParser.TraversalMethod_concat_Traversal_TraversalContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_concat_String.
    def visitTraversalMethod_concat_String(self, ctx: GremlinParser.TraversalMethod_concat_StringContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_conjoin_String.
    def visitTraversalMethod_conjoin_String(self, ctx: GremlinParser.TraversalMethod_conjoin_StringContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_connectedComponent.
    def visitTraversalMethod_connectedComponent(self, ctx: GremlinParser.TraversalMethod_connectedComponentContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_constant.
    def visitTraversalMethod_constant(self, ctx: GremlinParser.TraversalMethod_constantContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_count_Empty.
    def visitTraversalMethod_count_Empty(self, ctx: GremlinParser.TraversalMethod_count_EmptyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_count_Scope.
    def visitTraversalMethod_count_Scope(self, ctx: GremlinParser.TraversalMethod_count_ScopeContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_cyclicPath.
    def visitTraversalMethod_cyclicPath(self, ctx: GremlinParser.TraversalMethod_cyclicPathContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_dateAdd.
    def visitTraversalMethod_dateAdd(self, ctx: GremlinParser.TraversalMethod_dateAddContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_dateDiff_Traversal.
    def visitTraversalMethod_dateDiff_Traversal(self, ctx: GremlinParser.TraversalMethod_dateDiff_TraversalContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_dateDiff_Date.
    def visitTraversalMethod_dateDiff_Date(self, ctx: GremlinParser.TraversalMethod_dateDiff_DateContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_dedup_Scope_String.
    def visitTraversalMethod_dedup_Scope_String(self, ctx: GremlinParser.TraversalMethod_dedup_Scope_StringContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_dedup_String.
    def visitTraversalMethod_dedup_String(self, ctx: GremlinParser.TraversalMethod_dedup_StringContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_difference_Object.
    def visitTraversalMethod_difference_Object(self, ctx: GremlinParser.TraversalMethod_difference_ObjectContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_discard.
    def visitTraversalMethod_discard(self, ctx: GremlinParser.TraversalMethod_discardContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_disjunct_Object.
    def visitTraversalMethod_disjunct_Object(self, ctx: GremlinParser.TraversalMethod_disjunct_ObjectContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_drop.
    def visitTraversalMethod_drop(self, ctx: GremlinParser.TraversalMethod_dropContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_element.
    def visitTraversalMethod_element(self, ctx: GremlinParser.TraversalMethod_elementContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_elementMap.
    def visitTraversalMethod_elementMap(self, ctx: GremlinParser.TraversalMethod_elementMapContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_emit_Empty.
    def visitTraversalMethod_emit_Empty(self, ctx: GremlinParser.TraversalMethod_emit_EmptyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_emit_Predicate.
    def visitTraversalMethod_emit_Predicate(self, ctx: GremlinParser.TraversalMethod_emit_PredicateContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_emit_Traversal.
    def visitTraversalMethod_emit_Traversal(self, ctx: GremlinParser.TraversalMethod_emit_TraversalContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_fail_Empty.
    def visitTraversalMethod_fail_Empty(self, ctx: GremlinParser.TraversalMethod_fail_EmptyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_fail_String.
    def visitTraversalMethod_fail_String(self, ctx: GremlinParser.TraversalMethod_fail_StringContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_filter_Predicate.
    def visitTraversalMethod_filter_Predicate(self, ctx: GremlinParser.TraversalMethod_filter_PredicateContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_filter_Traversal.
    def visitTraversalMethod_filter_Traversal(self, ctx: GremlinParser.TraversalMethod_filter_TraversalContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_flatMap.
    def visitTraversalMethod_flatMap(self, ctx: GremlinParser.TraversalMethod_flatMapContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_fold_Empty.
    def visitTraversalMethod_fold_Empty(self, ctx: GremlinParser.TraversalMethod_fold_EmptyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_fold_Object_BiFunction.
    def visitTraversalMethod_fold_Object_BiFunction(
        self, ctx: GremlinParser.TraversalMethod_fold_Object_BiFunctionContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_format_String.
    def visitTraversalMethod_format_String(self, ctx: GremlinParser.TraversalMethod_format_StringContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_from_String.
    def visitTraversalMethod_from_String(self, ctx: GremlinParser.TraversalMethod_from_StringContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_from_Vertex.
    def visitTraversalMethod_from_Vertex(self, ctx: GremlinParser.TraversalMethod_from_VertexContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_from_Traversal.
    def visitTraversalMethod_from_Traversal(self, ctx: GremlinParser.TraversalMethod_from_TraversalContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_group_Empty.
    def visitTraversalMethod_group_Empty(self, ctx: GremlinParser.TraversalMethod_group_EmptyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_group_String.
    def visitTraversalMethod_group_String(self, ctx: GremlinParser.TraversalMethod_group_StringContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_groupCount_Empty.
    def visitTraversalMethod_groupCount_Empty(self, ctx: GremlinParser.TraversalMethod_groupCount_EmptyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_groupCount_String.
    def visitTraversalMethod_groupCount_String(self, ctx: GremlinParser.TraversalMethod_groupCount_StringContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_has_String.
    def visitTraversalMethod_has_String(self, ctx: GremlinParser.TraversalMethod_has_StringContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_has_String_Object.
    def visitTraversalMethod_has_String_Object(self, ctx: GremlinParser.TraversalMethod_has_String_ObjectContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_has_String_P.
    def visitTraversalMethod_has_String_P(self, ctx: GremlinParser.TraversalMethod_has_String_PContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_has_String_String_Object.
    def visitTraversalMethod_has_String_String_Object(
        self, ctx: GremlinParser.TraversalMethod_has_String_String_ObjectContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_has_String_String_P.
    def visitTraversalMethod_has_String_String_P(self, ctx: GremlinParser.TraversalMethod_has_String_String_PContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_has_String_Traversal.
    def visitTraversalMethod_has_String_Traversal(self, ctx: GremlinParser.TraversalMethod_has_String_TraversalContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_has_T_Object.
    def visitTraversalMethod_has_T_Object(self, ctx: GremlinParser.TraversalMethod_has_T_ObjectContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_has_T_P.
    def visitTraversalMethod_has_T_P(self, ctx: GremlinParser.TraversalMethod_has_T_PContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_has_T_Traversal.
    def visitTraversalMethod_has_T_Traversal(self, ctx: GremlinParser.TraversalMethod_has_T_TraversalContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_hasId_Object_Object.
    def visitTraversalMethod_hasId_Object_Object(self, ctx: GremlinParser.TraversalMethod_hasId_Object_ObjectContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_hasId_P.
    def visitTraversalMethod_hasId_P(self, ctx: GremlinParser.TraversalMethod_hasId_PContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_hasKey_P.
    def visitTraversalMethod_hasKey_P(self, ctx: GremlinParser.TraversalMethod_hasKey_PContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_hasKey_String_String.
    def visitTraversalMethod_hasKey_String_String(self, ctx: GremlinParser.TraversalMethod_hasKey_String_StringContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_hasLabel_P.
    def visitTraversalMethod_hasLabel_P(self, ctx: GremlinParser.TraversalMethod_hasLabel_PContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_hasLabel_String_String.
    def visitTraversalMethod_hasLabel_String_String(
        self, ctx: GremlinParser.TraversalMethod_hasLabel_String_StringContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_hasNot.
    def visitTraversalMethod_hasNot(self, ctx: GremlinParser.TraversalMethod_hasNotContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_hasValue_Object_Object.
    def visitTraversalMethod_hasValue_Object_Object(
        self, ctx: GremlinParser.TraversalMethod_hasValue_Object_ObjectContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_hasValue_P.
    def visitTraversalMethod_hasValue_P(self, ctx: GremlinParser.TraversalMethod_hasValue_PContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_id.
    def visitTraversalMethod_id(self, ctx: GremlinParser.TraversalMethod_idContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_identity.
    def visitTraversalMethod_identity(self, ctx: GremlinParser.TraversalMethod_identityContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_in.
    def visitTraversalMethod_in(self, ctx: GremlinParser.TraversalMethod_inContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_inE.
    def visitTraversalMethod_inE(self, ctx: GremlinParser.TraversalMethod_inEContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_intersect_Object.
    def visitTraversalMethod_intersect_Object(self, ctx: GremlinParser.TraversalMethod_intersect_ObjectContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_inV.
    def visitTraversalMethod_inV(self, ctx: GremlinParser.TraversalMethod_inVContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_index.
    def visitTraversalMethod_index(self, ctx: GremlinParser.TraversalMethod_indexContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_inject.
    def visitTraversalMethod_inject(self, ctx: GremlinParser.TraversalMethod_injectContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_is_Object.
    def visitTraversalMethod_is_Object(self, ctx: GremlinParser.TraversalMethod_is_ObjectContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_is_P.
    def visitTraversalMethod_is_P(self, ctx: GremlinParser.TraversalMethod_is_PContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_key.
    def visitTraversalMethod_key(self, ctx: GremlinParser.TraversalMethod_keyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_label.
    def visitTraversalMethod_label(self, ctx: GremlinParser.TraversalMethod_labelContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_length_Empty.
    def visitTraversalMethod_length_Empty(self, ctx: GremlinParser.TraversalMethod_length_EmptyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_length_Scope.
    def visitTraversalMethod_length_Scope(self, ctx: GremlinParser.TraversalMethod_length_ScopeContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_limit_Scope_long.
    def visitTraversalMethod_limit_Scope_long(self, ctx: GremlinParser.TraversalMethod_limit_Scope_longContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_limit_long.
    def visitTraversalMethod_limit_long(self, ctx: GremlinParser.TraversalMethod_limit_longContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_local.
    def visitTraversalMethod_local(self, ctx: GremlinParser.TraversalMethod_localContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_loops_Empty.
    def visitTraversalMethod_loops_Empty(self, ctx: GremlinParser.TraversalMethod_loops_EmptyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_loops_String.
    def visitTraversalMethod_loops_String(self, ctx: GremlinParser.TraversalMethod_loops_StringContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_lTrim_Empty.
    def visitTraversalMethod_lTrim_Empty(self, ctx: GremlinParser.TraversalMethod_lTrim_EmptyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_lTrim_Scope.
    def visitTraversalMethod_lTrim_Scope(self, ctx: GremlinParser.TraversalMethod_lTrim_ScopeContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_map.
    def visitTraversalMethod_map(self, ctx: GremlinParser.TraversalMethod_mapContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_match.
    def visitTraversalMethod_match(self, ctx: GremlinParser.TraversalMethod_matchContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_math.
    def visitTraversalMethod_math(self, ctx: GremlinParser.TraversalMethod_mathContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_max_Empty.
    def visitTraversalMethod_max_Empty(self, ctx: GremlinParser.TraversalMethod_max_EmptyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_max_Scope.
    def visitTraversalMethod_max_Scope(self, ctx: GremlinParser.TraversalMethod_max_ScopeContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_mean_Empty.
    def visitTraversalMethod_mean_Empty(self, ctx: GremlinParser.TraversalMethod_mean_EmptyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_mean_Scope.
    def visitTraversalMethod_mean_Scope(self, ctx: GremlinParser.TraversalMethod_mean_ScopeContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_merge_Object.
    def visitTraversalMethod_merge_Object(self, ctx: GremlinParser.TraversalMethod_merge_ObjectContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_mergeV_empty.
    def visitTraversalMethod_mergeV_empty(self, ctx: GremlinParser.TraversalMethod_mergeV_emptyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_mergeV_Map.
    def visitTraversalMethod_mergeV_Map(self, ctx: GremlinParser.TraversalMethod_mergeV_MapContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_mergeV_Traversal.
    def visitTraversalMethod_mergeV_Traversal(self, ctx: GremlinParser.TraversalMethod_mergeV_TraversalContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_mergeE_empty.
    def visitTraversalMethod_mergeE_empty(self, ctx: GremlinParser.TraversalMethod_mergeE_emptyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_mergeE_Map.
    def visitTraversalMethod_mergeE_Map(self, ctx: GremlinParser.TraversalMethod_mergeE_MapContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_mergeE_Traversal.
    def visitTraversalMethod_mergeE_Traversal(self, ctx: GremlinParser.TraversalMethod_mergeE_TraversalContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_min_Empty.
    def visitTraversalMethod_min_Empty(self, ctx: GremlinParser.TraversalMethod_min_EmptyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_min_Scope.
    def visitTraversalMethod_min_Scope(self, ctx: GremlinParser.TraversalMethod_min_ScopeContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_none_P.
    def visitTraversalMethod_none_P(self, ctx: GremlinParser.TraversalMethod_none_PContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_not.
    def visitTraversalMethod_not(self, ctx: GremlinParser.TraversalMethod_notContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_option_Predicate_Traversal.
    def visitTraversalMethod_option_Predicate_Traversal(
        self, ctx: GremlinParser.TraversalMethod_option_Predicate_TraversalContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_option_Merge_Map.
    def visitTraversalMethod_option_Merge_Map(self, ctx: GremlinParser.TraversalMethod_option_Merge_MapContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_option_Merge_Map_Cardinality.
    def visitTraversalMethod_option_Merge_Map_Cardinality(
        self, ctx: GremlinParser.TraversalMethod_option_Merge_Map_CardinalityContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_option_Merge_Traversal.
    def visitTraversalMethod_option_Merge_Traversal(
        self, ctx: GremlinParser.TraversalMethod_option_Merge_TraversalContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_option_Object_Traversal.
    def visitTraversalMethod_option_Object_Traversal(
        self, ctx: GremlinParser.TraversalMethod_option_Object_TraversalContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_option_Traversal.
    def visitTraversalMethod_option_Traversal(self, ctx: GremlinParser.TraversalMethod_option_TraversalContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_optional.
    def visitTraversalMethod_optional(self, ctx: GremlinParser.TraversalMethod_optionalContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_or.
    def visitTraversalMethod_or(self, ctx: GremlinParser.TraversalMethod_orContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_order_Empty.
    def visitTraversalMethod_order_Empty(self, ctx: GremlinParser.TraversalMethod_order_EmptyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_order_Scope.
    def visitTraversalMethod_order_Scope(self, ctx: GremlinParser.TraversalMethod_order_ScopeContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_otherV.
    def visitTraversalMethod_otherV(self, ctx: GremlinParser.TraversalMethod_otherVContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_out.
    def visitTraversalMethod_out(self, ctx: GremlinParser.TraversalMethod_outContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_outE.
    def visitTraversalMethod_outE(self, ctx: GremlinParser.TraversalMethod_outEContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_outV.
    def visitTraversalMethod_outV(self, ctx: GremlinParser.TraversalMethod_outVContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_pageRank_Empty.
    def visitTraversalMethod_pageRank_Empty(self, ctx: GremlinParser.TraversalMethod_pageRank_EmptyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_pageRank_double.
    def visitTraversalMethod_pageRank_double(self, ctx: GremlinParser.TraversalMethod_pageRank_doubleContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_path.
    def visitTraversalMethod_path(self, ctx: GremlinParser.TraversalMethod_pathContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_peerPressure.
    def visitTraversalMethod_peerPressure(self, ctx: GremlinParser.TraversalMethod_peerPressureContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_product_Object.
    def visitTraversalMethod_product_Object(self, ctx: GremlinParser.TraversalMethod_product_ObjectContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_profile_Empty.
    def visitTraversalMethod_profile_Empty(self, ctx: GremlinParser.TraversalMethod_profile_EmptyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_profile_String.
    def visitTraversalMethod_profile_String(self, ctx: GremlinParser.TraversalMethod_profile_StringContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_project.
    def visitTraversalMethod_project(self, ctx: GremlinParser.TraversalMethod_projectContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_properties.
    def visitTraversalMethod_properties(self, ctx: GremlinParser.TraversalMethod_propertiesContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_property_Cardinality_Object_Object_Object.
    def visitTraversalMethod_property_Cardinality_Object_Object_Object(
        self, ctx: GremlinParser.TraversalMethod_property_Cardinality_Object_Object_ObjectContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_property_Cardinality_Object.
    def visitTraversalMethod_property_Cardinality_Object(
        self, ctx: GremlinParser.TraversalMethod_property_Cardinality_ObjectContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_property_Object_Object_Object.
    def visitTraversalMethod_property_Object_Object_Object(
        self, ctx: GremlinParser.TraversalMethod_property_Object_Object_ObjectContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_property_Object.
    def visitTraversalMethod_property_Object(self, ctx: GremlinParser.TraversalMethod_property_ObjectContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_propertyMap.
    def visitTraversalMethod_propertyMap(self, ctx: GremlinParser.TraversalMethod_propertyMapContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_range_Scope_long_long.
    def visitTraversalMethod_range_Scope_long_long(
        self, ctx: GremlinParser.TraversalMethod_range_Scope_long_longContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_range_long_long.
    def visitTraversalMethod_range_long_long(self, ctx: GremlinParser.TraversalMethod_range_long_longContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_read.
    def visitTraversalMethod_read(self, ctx: GremlinParser.TraversalMethod_readContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_repeat_String_Traversal.
    def visitTraversalMethod_repeat_String_Traversal(
        self, ctx: GremlinParser.TraversalMethod_repeat_String_TraversalContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_repeat_Traversal.
    def visitTraversalMethod_repeat_Traversal(self, ctx: GremlinParser.TraversalMethod_repeat_TraversalContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_replace_String_String.
    def visitTraversalMethod_replace_String_String(
        self, ctx: GremlinParser.TraversalMethod_replace_String_StringContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_replace_Scope_String_String.
    def visitTraversalMethod_replace_Scope_String_String(
        self, ctx: GremlinParser.TraversalMethod_replace_Scope_String_StringContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_reverse_Empty.
    def visitTraversalMethod_reverse_Empty(self, ctx: GremlinParser.TraversalMethod_reverse_EmptyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_rTrim_Empty.
    def visitTraversalMethod_rTrim_Empty(self, ctx: GremlinParser.TraversalMethod_rTrim_EmptyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_rTrim_Scope.
    def visitTraversalMethod_rTrim_Scope(self, ctx: GremlinParser.TraversalMethod_rTrim_ScopeContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_sack_BiFunction.
    def visitTraversalMethod_sack_BiFunction(self, ctx: GremlinParser.TraversalMethod_sack_BiFunctionContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_sack_Empty.
    def visitTraversalMethod_sack_Empty(self, ctx: GremlinParser.TraversalMethod_sack_EmptyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_sample_Scope_int.
    def visitTraversalMethod_sample_Scope_int(self, ctx: GremlinParser.TraversalMethod_sample_Scope_intContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_sample_int.
    def visitTraversalMethod_sample_int(self, ctx: GremlinParser.TraversalMethod_sample_intContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_select_Column.
    def visitTraversalMethod_select_Column(self, ctx: GremlinParser.TraversalMethod_select_ColumnContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_select_Pop_String.
    def visitTraversalMethod_select_Pop_String(self, ctx: GremlinParser.TraversalMethod_select_Pop_StringContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_select_Pop_String_String_String.
    def visitTraversalMethod_select_Pop_String_String_String(
        self, ctx: GremlinParser.TraversalMethod_select_Pop_String_String_StringContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_select_Pop_Traversal.
    def visitTraversalMethod_select_Pop_Traversal(self, ctx: GremlinParser.TraversalMethod_select_Pop_TraversalContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_select_String.
    def visitTraversalMethod_select_String(self, ctx: GremlinParser.TraversalMethod_select_StringContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_select_String_String_String.
    def visitTraversalMethod_select_String_String_String(
        self, ctx: GremlinParser.TraversalMethod_select_String_String_StringContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_select_Traversal.
    def visitTraversalMethod_select_Traversal(self, ctx: GremlinParser.TraversalMethod_select_TraversalContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_shortestPath.
    def visitTraversalMethod_shortestPath(self, ctx: GremlinParser.TraversalMethod_shortestPathContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_sideEffect.
    def visitTraversalMethod_sideEffect(self, ctx: GremlinParser.TraversalMethod_sideEffectContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_simplePath.
    def visitTraversalMethod_simplePath(self, ctx: GremlinParser.TraversalMethod_simplePathContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_skip_Scope_long.
    def visitTraversalMethod_skip_Scope_long(self, ctx: GremlinParser.TraversalMethod_skip_Scope_longContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_skip_long.
    def visitTraversalMethod_skip_long(self, ctx: GremlinParser.TraversalMethod_skip_longContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_split_String.
    def visitTraversalMethod_split_String(self, ctx: GremlinParser.TraversalMethod_split_StringContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_split_Scope_String.
    def visitTraversalMethod_split_Scope_String(self, ctx: GremlinParser.TraversalMethod_split_Scope_StringContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_store.
    def visitTraversalMethod_store(self, ctx: GremlinParser.TraversalMethod_storeContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_subgraph.
    def visitTraversalMethod_subgraph(self, ctx: GremlinParser.TraversalMethod_subgraphContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_substring_int.
    def visitTraversalMethod_substring_int(self, ctx: GremlinParser.TraversalMethod_substring_intContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_substring_Scope_int.
    def visitTraversalMethod_substring_Scope_int(self, ctx: GremlinParser.TraversalMethod_substring_Scope_intContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_substring_int_int.
    def visitTraversalMethod_substring_int_int(self, ctx: GremlinParser.TraversalMethod_substring_int_intContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_substring_Scope_int_int.
    def visitTraversalMethod_substring_Scope_int_int(
        self, ctx: GremlinParser.TraversalMethod_substring_Scope_int_intContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_sum_Empty.
    def visitTraversalMethod_sum_Empty(self, ctx: GremlinParser.TraversalMethod_sum_EmptyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_sum_Scope.
    def visitTraversalMethod_sum_Scope(self, ctx: GremlinParser.TraversalMethod_sum_ScopeContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_tail_Empty.
    def visitTraversalMethod_tail_Empty(self, ctx: GremlinParser.TraversalMethod_tail_EmptyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_tail_Scope.
    def visitTraversalMethod_tail_Scope(self, ctx: GremlinParser.TraversalMethod_tail_ScopeContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_tail_Scope_long.
    def visitTraversalMethod_tail_Scope_long(self, ctx: GremlinParser.TraversalMethod_tail_Scope_longContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_tail_long.
    def visitTraversalMethod_tail_long(self, ctx: GremlinParser.TraversalMethod_tail_longContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_timeLimit.
    def visitTraversalMethod_timeLimit(self, ctx: GremlinParser.TraversalMethod_timeLimitContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_times.
    def visitTraversalMethod_times(self, ctx: GremlinParser.TraversalMethod_timesContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_to_Direction_String.
    def visitTraversalMethod_to_Direction_String(self, ctx: GremlinParser.TraversalMethod_to_Direction_StringContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_to_String.
    def visitTraversalMethod_to_String(self, ctx: GremlinParser.TraversalMethod_to_StringContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_to_Vertex.
    def visitTraversalMethod_to_Vertex(self, ctx: GremlinParser.TraversalMethod_to_VertexContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_to_Traversal.
    def visitTraversalMethod_to_Traversal(self, ctx: GremlinParser.TraversalMethod_to_TraversalContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_toE.
    def visitTraversalMethod_toE(self, ctx: GremlinParser.TraversalMethod_toEContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_toLower_Empty.
    def visitTraversalMethod_toLower_Empty(self, ctx: GremlinParser.TraversalMethod_toLower_EmptyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_toLower_Scope.
    def visitTraversalMethod_toLower_Scope(self, ctx: GremlinParser.TraversalMethod_toLower_ScopeContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_toUpper_Empty.
    def visitTraversalMethod_toUpper_Empty(self, ctx: GremlinParser.TraversalMethod_toUpper_EmptyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_toUpper_Scope.
    def visitTraversalMethod_toUpper_Scope(self, ctx: GremlinParser.TraversalMethod_toUpper_ScopeContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_toV.
    def visitTraversalMethod_toV(self, ctx: GremlinParser.TraversalMethod_toVContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_tree_Empty.
    def visitTraversalMethod_tree_Empty(self, ctx: GremlinParser.TraversalMethod_tree_EmptyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_tree_String.
    def visitTraversalMethod_tree_String(self, ctx: GremlinParser.TraversalMethod_tree_StringContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_trim_Empty.
    def visitTraversalMethod_trim_Empty(self, ctx: GremlinParser.TraversalMethod_trim_EmptyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_trim_Scope.
    def visitTraversalMethod_trim_Scope(self, ctx: GremlinParser.TraversalMethod_trim_ScopeContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_unfold.
    def visitTraversalMethod_unfold(self, ctx: GremlinParser.TraversalMethod_unfoldContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_union.
    def visitTraversalMethod_union(self, ctx: GremlinParser.TraversalMethod_unionContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_until_Predicate.
    def visitTraversalMethod_until_Predicate(self, ctx: GremlinParser.TraversalMethod_until_PredicateContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_until_Traversal.
    def visitTraversalMethod_until_Traversal(self, ctx: GremlinParser.TraversalMethod_until_TraversalContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_value.
    def visitTraversalMethod_value(self, ctx: GremlinParser.TraversalMethod_valueContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_valueMap_String.
    def visitTraversalMethod_valueMap_String(self, ctx: GremlinParser.TraversalMethod_valueMap_StringContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_valueMap_boolean_String.
    def visitTraversalMethod_valueMap_boolean_String(
        self, ctx: GremlinParser.TraversalMethod_valueMap_boolean_StringContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_values.
    def visitTraversalMethod_values(self, ctx: GremlinParser.TraversalMethod_valuesContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_where_P.
    def visitTraversalMethod_where_P(self, ctx: GremlinParser.TraversalMethod_where_PContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_where_String_P.
    def visitTraversalMethod_where_String_P(self, ctx: GremlinParser.TraversalMethod_where_String_PContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_where_Traversal.
    def visitTraversalMethod_where_Traversal(self, ctx: GremlinParser.TraversalMethod_where_TraversalContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_with_String.
    def visitTraversalMethod_with_String(self, ctx: GremlinParser.TraversalMethod_with_StringContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_with_String_Object.
    def visitTraversalMethod_with_String_Object(self, ctx: GremlinParser.TraversalMethod_with_String_ObjectContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMethod_write.
    def visitTraversalMethod_write(self, ctx: GremlinParser.TraversalMethod_writeContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#structureVertexLiteral.
    def visitStructureVertexLiteral(self, ctx: GremlinParser.StructureVertexLiteralContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalStrategy.
    def visitTraversalStrategy(self, ctx: GremlinParser.TraversalStrategyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#configuration.
    def visitConfiguration(self, ctx: GremlinParser.ConfigurationContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalScope.
    def visitTraversalScope(self, ctx: GremlinParser.TraversalScopeContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalBarrier.
    def visitTraversalBarrier(self, ctx: GremlinParser.TraversalBarrierContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalT.
    def visitTraversalT(self, ctx: GremlinParser.TraversalTContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalTShort.
    def visitTraversalTShort(self, ctx: GremlinParser.TraversalTShortContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalTLong.
    def visitTraversalTLong(self, ctx: GremlinParser.TraversalTLongContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalMerge.
    def visitTraversalMerge(self, ctx: GremlinParser.TraversalMergeContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalOrder.
    def visitTraversalOrder(self, ctx: GremlinParser.TraversalOrderContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalDirection.
    def visitTraversalDirection(self, ctx: GremlinParser.TraversalDirectionContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalDirectionShort.
    def visitTraversalDirectionShort(self, ctx: GremlinParser.TraversalDirectionShortContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalDirectionLong.
    def visitTraversalDirectionLong(self, ctx: GremlinParser.TraversalDirectionLongContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalCardinality.
    def visitTraversalCardinality(self, ctx: GremlinParser.TraversalCardinalityContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalColumn.
    def visitTraversalColumn(self, ctx: GremlinParser.TraversalColumnContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalPop.
    def visitTraversalPop(self, ctx: GremlinParser.TraversalPopContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalOperator.
    def visitTraversalOperator(self, ctx: GremlinParser.TraversalOperatorContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalPick.
    def visitTraversalPick(self, ctx: GremlinParser.TraversalPickContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalDT.
    def visitTraversalDT(self, ctx: GremlinParser.TraversalDTContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalPredicate.
    def visitTraversalPredicate(self, ctx: GremlinParser.TraversalPredicateContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalTerminalMethod.
    def visitTraversalTerminalMethod(self, ctx: GremlinParser.TraversalTerminalMethodContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalSackMethod.
    def visitTraversalSackMethod(self, ctx: GremlinParser.TraversalSackMethodContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalComparator.
    def visitTraversalComparator(self, ctx: GremlinParser.TraversalComparatorContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalFunction.
    def visitTraversalFunction(self, ctx: GremlinParser.TraversalFunctionContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalBiFunction.
    def visitTraversalBiFunction(self, ctx: GremlinParser.TraversalBiFunctionContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalPredicate_eq.
    def visitTraversalPredicate_eq(self, ctx: GremlinParser.TraversalPredicate_eqContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalPredicate_neq.
    def visitTraversalPredicate_neq(self, ctx: GremlinParser.TraversalPredicate_neqContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalPredicate_lt.
    def visitTraversalPredicate_lt(self, ctx: GremlinParser.TraversalPredicate_ltContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalPredicate_lte.
    def visitTraversalPredicate_lte(self, ctx: GremlinParser.TraversalPredicate_lteContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalPredicate_gt.
    def visitTraversalPredicate_gt(self, ctx: GremlinParser.TraversalPredicate_gtContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalPredicate_gte.
    def visitTraversalPredicate_gte(self, ctx: GremlinParser.TraversalPredicate_gteContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalPredicate_inside.
    def visitTraversalPredicate_inside(self, ctx: GremlinParser.TraversalPredicate_insideContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalPredicate_outside.
    def visitTraversalPredicate_outside(self, ctx: GremlinParser.TraversalPredicate_outsideContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalPredicate_between.
    def visitTraversalPredicate_between(self, ctx: GremlinParser.TraversalPredicate_betweenContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalPredicate_within.
    def visitTraversalPredicate_within(self, ctx: GremlinParser.TraversalPredicate_withinContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalPredicate_without.
    def visitTraversalPredicate_without(self, ctx: GremlinParser.TraversalPredicate_withoutContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalPredicate_not.
    def visitTraversalPredicate_not(self, ctx: GremlinParser.TraversalPredicate_notContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalPredicate_containing.
    def visitTraversalPredicate_containing(self, ctx: GremlinParser.TraversalPredicate_containingContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalPredicate_notContaining.
    def visitTraversalPredicate_notContaining(self, ctx: GremlinParser.TraversalPredicate_notContainingContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalPredicate_startingWith.
    def visitTraversalPredicate_startingWith(self, ctx: GremlinParser.TraversalPredicate_startingWithContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalPredicate_notStartingWith.
    def visitTraversalPredicate_notStartingWith(self, ctx: GremlinParser.TraversalPredicate_notStartingWithContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalPredicate_endingWith.
    def visitTraversalPredicate_endingWith(self, ctx: GremlinParser.TraversalPredicate_endingWithContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalPredicate_notEndingWith.
    def visitTraversalPredicate_notEndingWith(self, ctx: GremlinParser.TraversalPredicate_notEndingWithContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalPredicate_regex.
    def visitTraversalPredicate_regex(self, ctx: GremlinParser.TraversalPredicate_regexContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalPredicate_notRegex.
    def visitTraversalPredicate_notRegex(self, ctx: GremlinParser.TraversalPredicate_notRegexContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalTerminalMethod_explain.
    def visitTraversalTerminalMethod_explain(self, ctx: GremlinParser.TraversalTerminalMethod_explainContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalTerminalMethod_hasNext.
    def visitTraversalTerminalMethod_hasNext(self, ctx: GremlinParser.TraversalTerminalMethod_hasNextContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalTerminalMethod_iterate.
    def visitTraversalTerminalMethod_iterate(self, ctx: GremlinParser.TraversalTerminalMethod_iterateContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalTerminalMethod_tryNext.
    def visitTraversalTerminalMethod_tryNext(self, ctx: GremlinParser.TraversalTerminalMethod_tryNextContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalTerminalMethod_next.
    def visitTraversalTerminalMethod_next(self, ctx: GremlinParser.TraversalTerminalMethod_nextContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalTerminalMethod_toList.
    def visitTraversalTerminalMethod_toList(self, ctx: GremlinParser.TraversalTerminalMethod_toListContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalTerminalMethod_toSet.
    def visitTraversalTerminalMethod_toSet(self, ctx: GremlinParser.TraversalTerminalMethod_toSetContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalTerminalMethod_toBulkSet.
    def visitTraversalTerminalMethod_toBulkSet(self, ctx: GremlinParser.TraversalTerminalMethod_toBulkSetContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#withOptionKeys.
    def visitWithOptionKeys(self, ctx: GremlinParser.WithOptionKeysContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#connectedComponentConstants.
    def visitConnectedComponentConstants(self, ctx: GremlinParser.ConnectedComponentConstantsContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#pageRankConstants.
    def visitPageRankConstants(self, ctx: GremlinParser.PageRankConstantsContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#peerPressureConstants.
    def visitPeerPressureConstants(self, ctx: GremlinParser.PeerPressureConstantsContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#shortestPathConstants.
    def visitShortestPathConstants(self, ctx: GremlinParser.ShortestPathConstantsContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#withOptionsValues.
    def visitWithOptionsValues(self, ctx: GremlinParser.WithOptionsValuesContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#ioOptionsKeys.
    def visitIoOptionsKeys(self, ctx: GremlinParser.IoOptionsKeysContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#ioOptionsValues.
    def visitIoOptionsValues(self, ctx: GremlinParser.IoOptionsValuesContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#connectedComponentConstants_component.
    def visitConnectedComponentConstants_component(
        self, ctx: GremlinParser.ConnectedComponentConstants_componentContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#connectedComponentConstants_edges.
    def visitConnectedComponentConstants_edges(self, ctx: GremlinParser.ConnectedComponentConstants_edgesContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#connectedComponentConstants_propertyName.
    def visitConnectedComponentConstants_propertyName(
        self, ctx: GremlinParser.ConnectedComponentConstants_propertyNameContext
    ):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#pageRankConstants_edges.
    def visitPageRankConstants_edges(self, ctx: GremlinParser.PageRankConstants_edgesContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#pageRankConstants_times.
    def visitPageRankConstants_times(self, ctx: GremlinParser.PageRankConstants_timesContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#pageRankConstants_propertyName.
    def visitPageRankConstants_propertyName(self, ctx: GremlinParser.PageRankConstants_propertyNameContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#peerPressureConstants_edges.
    def visitPeerPressureConstants_edges(self, ctx: GremlinParser.PeerPressureConstants_edgesContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#peerPressureConstants_times.
    def visitPeerPressureConstants_times(self, ctx: GremlinParser.PeerPressureConstants_timesContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#peerPressureConstants_propertyName.
    def visitPeerPressureConstants_propertyName(self, ctx: GremlinParser.PeerPressureConstants_propertyNameContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#shortestPathConstants_target.
    def visitShortestPathConstants_target(self, ctx: GremlinParser.ShortestPathConstants_targetContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#shortestPathConstants_edges.
    def visitShortestPathConstants_edges(self, ctx: GremlinParser.ShortestPathConstants_edgesContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#shortestPathConstants_distance.
    def visitShortestPathConstants_distance(self, ctx: GremlinParser.ShortestPathConstants_distanceContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#shortestPathConstants_maxDistance.
    def visitShortestPathConstants_maxDistance(self, ctx: GremlinParser.ShortestPathConstants_maxDistanceContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#shortestPathConstants_includeEdges.
    def visitShortestPathConstants_includeEdges(self, ctx: GremlinParser.ShortestPathConstants_includeEdgesContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#withOptionsConstants_tokens.
    def visitWithOptionsConstants_tokens(self, ctx: GremlinParser.WithOptionsConstants_tokensContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#withOptionsConstants_none.
    def visitWithOptionsConstants_none(self, ctx: GremlinParser.WithOptionsConstants_noneContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#withOptionsConstants_ids.
    def visitWithOptionsConstants_ids(self, ctx: GremlinParser.WithOptionsConstants_idsContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#withOptionsConstants_labels.
    def visitWithOptionsConstants_labels(self, ctx: GremlinParser.WithOptionsConstants_labelsContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#withOptionsConstants_keys.
    def visitWithOptionsConstants_keys(self, ctx: GremlinParser.WithOptionsConstants_keysContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#withOptionsConstants_values.
    def visitWithOptionsConstants_values(self, ctx: GremlinParser.WithOptionsConstants_valuesContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#withOptionsConstants_all.
    def visitWithOptionsConstants_all(self, ctx: GremlinParser.WithOptionsConstants_allContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#withOptionsConstants_indexer.
    def visitWithOptionsConstants_indexer(self, ctx: GremlinParser.WithOptionsConstants_indexerContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#withOptionsConstants_list.
    def visitWithOptionsConstants_list(self, ctx: GremlinParser.WithOptionsConstants_listContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#withOptionsConstants_map.
    def visitWithOptionsConstants_map(self, ctx: GremlinParser.WithOptionsConstants_mapContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#ioOptionsConstants_reader.
    def visitIoOptionsConstants_reader(self, ctx: GremlinParser.IoOptionsConstants_readerContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#ioOptionsConstants_writer.
    def visitIoOptionsConstants_writer(self, ctx: GremlinParser.IoOptionsConstants_writerContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#ioOptionsConstants_gryo.
    def visitIoOptionsConstants_gryo(self, ctx: GremlinParser.IoOptionsConstants_gryoContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#ioOptionsConstants_graphson.
    def visitIoOptionsConstants_graphson(self, ctx: GremlinParser.IoOptionsConstants_graphsonContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#ioOptionsConstants_graphml.
    def visitIoOptionsConstants_graphml(self, ctx: GremlinParser.IoOptionsConstants_graphmlContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#connectedComponentStringConstant.
    def visitConnectedComponentStringConstant(self, ctx: GremlinParser.ConnectedComponentStringConstantContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#pageRankStringConstant.
    def visitPageRankStringConstant(self, ctx: GremlinParser.PageRankStringConstantContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#peerPressureStringConstant.
    def visitPeerPressureStringConstant(self, ctx: GremlinParser.PeerPressureStringConstantContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#shortestPathStringConstant.
    def visitShortestPathStringConstant(self, ctx: GremlinParser.ShortestPathStringConstantContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#withOptionsStringConstant.
    def visitWithOptionsStringConstant(self, ctx: GremlinParser.WithOptionsStringConstantContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#ioOptionsStringConstant.
    def visitIoOptionsStringConstant(self, ctx: GremlinParser.IoOptionsStringConstantContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#booleanArgument.
    def visitBooleanArgument(self, ctx: GremlinParser.BooleanArgumentContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#integerArgument.
    def visitIntegerArgument(self, ctx: GremlinParser.IntegerArgumentContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#floatArgument.
    def visitFloatArgument(self, ctx: GremlinParser.FloatArgumentContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#stringArgument.
    def visitStringArgument(self, ctx: GremlinParser.StringArgumentContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#stringNullableArgument.
    def visitStringNullableArgument(self, ctx: GremlinParser.StringNullableArgumentContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#stringNullableArgumentVarargs.
    def visitStringNullableArgumentVarargs(self, ctx: GremlinParser.StringNullableArgumentVarargsContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#dateArgument.
    def visitDateArgument(self, ctx: GremlinParser.DateArgumentContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#genericArgument.
    def visitGenericArgument(self, ctx: GremlinParser.GenericArgumentContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#genericArgumentVarargs.
    def visitGenericArgumentVarargs(self, ctx: GremlinParser.GenericArgumentVarargsContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#genericMapArgument.
    def visitGenericMapArgument(self, ctx: GremlinParser.GenericMapArgumentContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#genericMapNullableArgument.
    def visitGenericMapNullableArgument(self, ctx: GremlinParser.GenericMapNullableArgumentContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#nullableGenericLiteralMap.
    def visitNullableGenericLiteralMap(self, ctx: GremlinParser.NullableGenericLiteralMapContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#structureVertexArgument.
    def visitStructureVertexArgument(self, ctx: GremlinParser.StructureVertexArgumentContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalStrategyVarargs.
    def visitTraversalStrategyVarargs(self, ctx: GremlinParser.TraversalStrategyVarargsContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#traversalStrategyExpr.
    def visitTraversalStrategyExpr(self, ctx: GremlinParser.TraversalStrategyExprContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#classTypeList.
    def visitClassTypeList(self, ctx: GremlinParser.ClassTypeListContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#classTypeExpr.
    def visitClassTypeExpr(self, ctx: GremlinParser.ClassTypeExprContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#nestedTraversalList.
    def visitNestedTraversalList(self, ctx: GremlinParser.NestedTraversalListContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#nestedTraversalExpr.
    def visitNestedTraversalExpr(self, ctx: GremlinParser.NestedTraversalExprContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#genericCollectionLiteral.
    def visitGenericCollectionLiteral(self, ctx: GremlinParser.GenericCollectionLiteralContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#genericLiteralVarargs.
    def visitGenericLiteralVarargs(self, ctx: GremlinParser.GenericLiteralVarargsContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#genericLiteralExpr.
    def visitGenericLiteralExpr(self, ctx: GremlinParser.GenericLiteralExprContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#genericMapNullableLiteral.
    def visitGenericMapNullableLiteral(self, ctx: GremlinParser.GenericMapNullableLiteralContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#genericRangeLiteral.
    def visitGenericRangeLiteral(self, ctx: GremlinParser.GenericRangeLiteralContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#genericSetLiteral.
    def visitGenericSetLiteral(self, ctx: GremlinParser.GenericSetLiteralContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#stringNullableLiteralVarargs.
    def visitStringNullableLiteralVarargs(self, ctx: GremlinParser.StringNullableLiteralVarargsContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#genericLiteral.
    def visitGenericLiteral(self, ctx: GremlinParser.GenericLiteralContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#genericMapLiteral.
    def visitGenericMapLiteral(self, ctx: GremlinParser.GenericMapLiteralContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#mapKey.
    def visitMapKey(self, ctx: GremlinParser.MapKeyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#mapEntry.
    def visitMapEntry(self, ctx: GremlinParser.MapEntryContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#stringLiteral.
    def visitStringLiteral(self, ctx: GremlinParser.StringLiteralContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#stringNullableLiteral.
    def visitStringNullableLiteral(self, ctx: GremlinParser.StringNullableLiteralContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#integerLiteral.
    def visitIntegerLiteral(self, ctx: GremlinParser.IntegerLiteralContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#floatLiteral.
    def visitFloatLiteral(self, ctx: GremlinParser.FloatLiteralContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#numericLiteral.
    def visitNumericLiteral(self, ctx: GremlinParser.NumericLiteralContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#booleanLiteral.
    def visitBooleanLiteral(self, ctx: GremlinParser.BooleanLiteralContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#dateLiteral.
    def visitDateLiteral(self, ctx: GremlinParser.DateLiteralContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#nullLiteral.
    def visitNullLiteral(self, ctx: GremlinParser.NullLiteralContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#nanLiteral.
    def visitNanLiteral(self, ctx: GremlinParser.NanLiteralContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#infLiteral.
    def visitInfLiteral(self, ctx: GremlinParser.InfLiteralContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#uuidLiteral.
    def visitUuidLiteral(self, ctx: GremlinParser.UuidLiteralContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#nakedKey.
    def visitNakedKey(self, ctx: GremlinParser.NakedKeyContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#classType.
    def visitClassType(self, ctx: GremlinParser.ClassTypeContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#variable.
    def visitVariable(self, ctx: GremlinParser.VariableContext):
        return self.visitChildren(ctx)

    # Visit a parse tree produced by GremlinParser#keyword.
    def visitKeyword(self, ctx: GremlinParser.KeywordContext):
        return self.visitChildren(ctx)


del GremlinParser
