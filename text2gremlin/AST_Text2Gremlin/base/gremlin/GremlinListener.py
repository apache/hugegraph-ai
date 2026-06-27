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


# This class defines a complete listener for a parse tree produced by GremlinParser.
class GremlinListener(ParseTreeListener):
    # Enter a parse tree produced by GremlinParser#queryList.
    def enterQueryList(self, ctx: GremlinParser.QueryListContext):
        pass

    # Exit a parse tree produced by GremlinParser#queryList.
    def exitQueryList(self, ctx: GremlinParser.QueryListContext):
        pass

    # Enter a parse tree produced by GremlinParser#query.
    def enterQuery(self, ctx: GremlinParser.QueryContext):
        pass

    # Exit a parse tree produced by GremlinParser#query.
    def exitQuery(self, ctx: GremlinParser.QueryContext):
        pass

    # Enter a parse tree produced by GremlinParser#emptyQuery.
    def enterEmptyQuery(self, ctx: GremlinParser.EmptyQueryContext):
        pass

    # Exit a parse tree produced by GremlinParser#emptyQuery.
    def exitEmptyQuery(self, ctx: GremlinParser.EmptyQueryContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalSource.
    def enterTraversalSource(self, ctx: GremlinParser.TraversalSourceContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalSource.
    def exitTraversalSource(self, ctx: GremlinParser.TraversalSourceContext):
        pass

    # Enter a parse tree produced by GremlinParser#transactionPart.
    def enterTransactionPart(self, ctx: GremlinParser.TransactionPartContext):
        pass

    # Exit a parse tree produced by GremlinParser#transactionPart.
    def exitTransactionPart(self, ctx: GremlinParser.TransactionPartContext):
        pass

    # Enter a parse tree produced by GremlinParser#rootTraversal.
    def enterRootTraversal(self, ctx: GremlinParser.RootTraversalContext):
        pass

    # Exit a parse tree produced by GremlinParser#rootTraversal.
    def exitRootTraversal(self, ctx: GremlinParser.RootTraversalContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalSourceSelfMethod.
    def enterTraversalSourceSelfMethod(self, ctx: GremlinParser.TraversalSourceSelfMethodContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalSourceSelfMethod.
    def exitTraversalSourceSelfMethod(self, ctx: GremlinParser.TraversalSourceSelfMethodContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalSourceSelfMethod_withBulk.
    def enterTraversalSourceSelfMethod_withBulk(self, ctx: GremlinParser.TraversalSourceSelfMethod_withBulkContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalSourceSelfMethod_withBulk.
    def exitTraversalSourceSelfMethod_withBulk(self, ctx: GremlinParser.TraversalSourceSelfMethod_withBulkContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalSourceSelfMethod_withPath.
    def enterTraversalSourceSelfMethod_withPath(self, ctx: GremlinParser.TraversalSourceSelfMethod_withPathContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalSourceSelfMethod_withPath.
    def exitTraversalSourceSelfMethod_withPath(self, ctx: GremlinParser.TraversalSourceSelfMethod_withPathContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalSourceSelfMethod_withSack.
    def enterTraversalSourceSelfMethod_withSack(self, ctx: GremlinParser.TraversalSourceSelfMethod_withSackContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalSourceSelfMethod_withSack.
    def exitTraversalSourceSelfMethod_withSack(self, ctx: GremlinParser.TraversalSourceSelfMethod_withSackContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalSourceSelfMethod_withSideEffect.
    def enterTraversalSourceSelfMethod_withSideEffect(
        self, ctx: GremlinParser.TraversalSourceSelfMethod_withSideEffectContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalSourceSelfMethod_withSideEffect.
    def exitTraversalSourceSelfMethod_withSideEffect(
        self, ctx: GremlinParser.TraversalSourceSelfMethod_withSideEffectContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalSourceSelfMethod_withStrategies.
    def enterTraversalSourceSelfMethod_withStrategies(
        self, ctx: GremlinParser.TraversalSourceSelfMethod_withStrategiesContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalSourceSelfMethod_withStrategies.
    def exitTraversalSourceSelfMethod_withStrategies(
        self, ctx: GremlinParser.TraversalSourceSelfMethod_withStrategiesContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalSourceSelfMethod_withoutStrategies.
    def enterTraversalSourceSelfMethod_withoutStrategies(
        self, ctx: GremlinParser.TraversalSourceSelfMethod_withoutStrategiesContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalSourceSelfMethod_withoutStrategies.
    def exitTraversalSourceSelfMethod_withoutStrategies(
        self, ctx: GremlinParser.TraversalSourceSelfMethod_withoutStrategiesContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalSourceSelfMethod_with.
    def enterTraversalSourceSelfMethod_with(self, ctx: GremlinParser.TraversalSourceSelfMethod_withContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalSourceSelfMethod_with.
    def exitTraversalSourceSelfMethod_with(self, ctx: GremlinParser.TraversalSourceSelfMethod_withContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalSourceSpawnMethod.
    def enterTraversalSourceSpawnMethod(self, ctx: GremlinParser.TraversalSourceSpawnMethodContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalSourceSpawnMethod.
    def exitTraversalSourceSpawnMethod(self, ctx: GremlinParser.TraversalSourceSpawnMethodContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalSourceSpawnMethod_addE.
    def enterTraversalSourceSpawnMethod_addE(self, ctx: GremlinParser.TraversalSourceSpawnMethod_addEContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_addE.
    def exitTraversalSourceSpawnMethod_addE(self, ctx: GremlinParser.TraversalSourceSpawnMethod_addEContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalSourceSpawnMethod_addV.
    def enterTraversalSourceSpawnMethod_addV(self, ctx: GremlinParser.TraversalSourceSpawnMethod_addVContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_addV.
    def exitTraversalSourceSpawnMethod_addV(self, ctx: GremlinParser.TraversalSourceSpawnMethod_addVContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalSourceSpawnMethod_E.
    def enterTraversalSourceSpawnMethod_E(self, ctx: GremlinParser.TraversalSourceSpawnMethod_EContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_E.
    def exitTraversalSourceSpawnMethod_E(self, ctx: GremlinParser.TraversalSourceSpawnMethod_EContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalSourceSpawnMethod_V.
    def enterTraversalSourceSpawnMethod_V(self, ctx: GremlinParser.TraversalSourceSpawnMethod_VContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_V.
    def exitTraversalSourceSpawnMethod_V(self, ctx: GremlinParser.TraversalSourceSpawnMethod_VContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalSourceSpawnMethod_inject.
    def enterTraversalSourceSpawnMethod_inject(self, ctx: GremlinParser.TraversalSourceSpawnMethod_injectContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_inject.
    def exitTraversalSourceSpawnMethod_inject(self, ctx: GremlinParser.TraversalSourceSpawnMethod_injectContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalSourceSpawnMethod_io.
    def enterTraversalSourceSpawnMethod_io(self, ctx: GremlinParser.TraversalSourceSpawnMethod_ioContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_io.
    def exitTraversalSourceSpawnMethod_io(self, ctx: GremlinParser.TraversalSourceSpawnMethod_ioContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalSourceSpawnMethod_mergeV_Map.
    def enterTraversalSourceSpawnMethod_mergeV_Map(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_mergeV_MapContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_mergeV_Map.
    def exitTraversalSourceSpawnMethod_mergeV_Map(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_mergeV_MapContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalSourceSpawnMethod_mergeV_Traversal.
    def enterTraversalSourceSpawnMethod_mergeV_Traversal(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_mergeV_TraversalContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_mergeV_Traversal.
    def exitTraversalSourceSpawnMethod_mergeV_Traversal(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_mergeV_TraversalContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalSourceSpawnMethod_mergeE_Map.
    def enterTraversalSourceSpawnMethod_mergeE_Map(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_mergeE_MapContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_mergeE_Map.
    def exitTraversalSourceSpawnMethod_mergeE_Map(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_mergeE_MapContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalSourceSpawnMethod_mergeE_Traversal.
    def enterTraversalSourceSpawnMethod_mergeE_Traversal(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_mergeE_TraversalContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_mergeE_Traversal.
    def exitTraversalSourceSpawnMethod_mergeE_Traversal(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_mergeE_TraversalContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalSourceSpawnMethod_call_empty.
    def enterTraversalSourceSpawnMethod_call_empty(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_call_emptyContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_call_empty.
    def exitTraversalSourceSpawnMethod_call_empty(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_call_emptyContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalSourceSpawnMethod_call_string.
    def enterTraversalSourceSpawnMethod_call_string(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_call_stringContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_call_string.
    def exitTraversalSourceSpawnMethod_call_string(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_call_stringContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalSourceSpawnMethod_call_string_map.
    def enterTraversalSourceSpawnMethod_call_string_map(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_call_string_mapContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_call_string_map.
    def exitTraversalSourceSpawnMethod_call_string_map(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_call_string_mapContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalSourceSpawnMethod_call_string_traversal.
    def enterTraversalSourceSpawnMethod_call_string_traversal(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_call_string_traversalContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_call_string_traversal.
    def exitTraversalSourceSpawnMethod_call_string_traversal(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_call_string_traversalContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalSourceSpawnMethod_call_string_map_traversal.
    def enterTraversalSourceSpawnMethod_call_string_map_traversal(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_call_string_map_traversalContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_call_string_map_traversal.
    def exitTraversalSourceSpawnMethod_call_string_map_traversal(
        self, ctx: GremlinParser.TraversalSourceSpawnMethod_call_string_map_traversalContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalSourceSpawnMethod_union.
    def enterTraversalSourceSpawnMethod_union(self, ctx: GremlinParser.TraversalSourceSpawnMethod_unionContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalSourceSpawnMethod_union.
    def exitTraversalSourceSpawnMethod_union(self, ctx: GremlinParser.TraversalSourceSpawnMethod_unionContext):
        pass

    # Enter a parse tree produced by GremlinParser#chainedTraversal.
    def enterChainedTraversal(self, ctx: GremlinParser.ChainedTraversalContext):
        pass

    # Exit a parse tree produced by GremlinParser#chainedTraversal.
    def exitChainedTraversal(self, ctx: GremlinParser.ChainedTraversalContext):
        pass

    # Enter a parse tree produced by GremlinParser#nestedTraversal.
    def enterNestedTraversal(self, ctx: GremlinParser.NestedTraversalContext):
        pass

    # Exit a parse tree produced by GremlinParser#nestedTraversal.
    def exitNestedTraversal(self, ctx: GremlinParser.NestedTraversalContext):
        pass

    # Enter a parse tree produced by GremlinParser#terminatedTraversal.
    def enterTerminatedTraversal(self, ctx: GremlinParser.TerminatedTraversalContext):
        pass

    # Exit a parse tree produced by GremlinParser#terminatedTraversal.
    def exitTerminatedTraversal(self, ctx: GremlinParser.TerminatedTraversalContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod.
    def enterTraversalMethod(self, ctx: GremlinParser.TraversalMethodContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod.
    def exitTraversalMethod(self, ctx: GremlinParser.TraversalMethodContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_V.
    def enterTraversalMethod_V(self, ctx: GremlinParser.TraversalMethod_VContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_V.
    def exitTraversalMethod_V(self, ctx: GremlinParser.TraversalMethod_VContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_E.
    def enterTraversalMethod_E(self, ctx: GremlinParser.TraversalMethod_EContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_E.
    def exitTraversalMethod_E(self, ctx: GremlinParser.TraversalMethod_EContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_addE_String.
    def enterTraversalMethod_addE_String(self, ctx: GremlinParser.TraversalMethod_addE_StringContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_addE_String.
    def exitTraversalMethod_addE_String(self, ctx: GremlinParser.TraversalMethod_addE_StringContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_addE_Traversal.
    def enterTraversalMethod_addE_Traversal(self, ctx: GremlinParser.TraversalMethod_addE_TraversalContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_addE_Traversal.
    def exitTraversalMethod_addE_Traversal(self, ctx: GremlinParser.TraversalMethod_addE_TraversalContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_addV_Empty.
    def enterTraversalMethod_addV_Empty(self, ctx: GremlinParser.TraversalMethod_addV_EmptyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_addV_Empty.
    def exitTraversalMethod_addV_Empty(self, ctx: GremlinParser.TraversalMethod_addV_EmptyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_addV_String.
    def enterTraversalMethod_addV_String(self, ctx: GremlinParser.TraversalMethod_addV_StringContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_addV_String.
    def exitTraversalMethod_addV_String(self, ctx: GremlinParser.TraversalMethod_addV_StringContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_addV_Traversal.
    def enterTraversalMethod_addV_Traversal(self, ctx: GremlinParser.TraversalMethod_addV_TraversalContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_addV_Traversal.
    def exitTraversalMethod_addV_Traversal(self, ctx: GremlinParser.TraversalMethod_addV_TraversalContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_aggregate_Scope_String.
    def enterTraversalMethod_aggregate_Scope_String(
        self, ctx: GremlinParser.TraversalMethod_aggregate_Scope_StringContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_aggregate_Scope_String.
    def exitTraversalMethod_aggregate_Scope_String(
        self, ctx: GremlinParser.TraversalMethod_aggregate_Scope_StringContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_aggregate_String.
    def enterTraversalMethod_aggregate_String(self, ctx: GremlinParser.TraversalMethod_aggregate_StringContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_aggregate_String.
    def exitTraversalMethod_aggregate_String(self, ctx: GremlinParser.TraversalMethod_aggregate_StringContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_all_P.
    def enterTraversalMethod_all_P(self, ctx: GremlinParser.TraversalMethod_all_PContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_all_P.
    def exitTraversalMethod_all_P(self, ctx: GremlinParser.TraversalMethod_all_PContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_and.
    def enterTraversalMethod_and(self, ctx: GremlinParser.TraversalMethod_andContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_and.
    def exitTraversalMethod_and(self, ctx: GremlinParser.TraversalMethod_andContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_any_P.
    def enterTraversalMethod_any_P(self, ctx: GremlinParser.TraversalMethod_any_PContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_any_P.
    def exitTraversalMethod_any_P(self, ctx: GremlinParser.TraversalMethod_any_PContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_as.
    def enterTraversalMethod_as(self, ctx: GremlinParser.TraversalMethod_asContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_as.
    def exitTraversalMethod_as(self, ctx: GremlinParser.TraversalMethod_asContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_asDate.
    def enterTraversalMethod_asDate(self, ctx: GremlinParser.TraversalMethod_asDateContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_asDate.
    def exitTraversalMethod_asDate(self, ctx: GremlinParser.TraversalMethod_asDateContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_asString_Empty.
    def enterTraversalMethod_asString_Empty(self, ctx: GremlinParser.TraversalMethod_asString_EmptyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_asString_Empty.
    def exitTraversalMethod_asString_Empty(self, ctx: GremlinParser.TraversalMethod_asString_EmptyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_asString_Scope.
    def enterTraversalMethod_asString_Scope(self, ctx: GremlinParser.TraversalMethod_asString_ScopeContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_asString_Scope.
    def exitTraversalMethod_asString_Scope(self, ctx: GremlinParser.TraversalMethod_asString_ScopeContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_barrier_Consumer.
    def enterTraversalMethod_barrier_Consumer(self, ctx: GremlinParser.TraversalMethod_barrier_ConsumerContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_barrier_Consumer.
    def exitTraversalMethod_barrier_Consumer(self, ctx: GremlinParser.TraversalMethod_barrier_ConsumerContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_barrier_Empty.
    def enterTraversalMethod_barrier_Empty(self, ctx: GremlinParser.TraversalMethod_barrier_EmptyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_barrier_Empty.
    def exitTraversalMethod_barrier_Empty(self, ctx: GremlinParser.TraversalMethod_barrier_EmptyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_barrier_int.
    def enterTraversalMethod_barrier_int(self, ctx: GremlinParser.TraversalMethod_barrier_intContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_barrier_int.
    def exitTraversalMethod_barrier_int(self, ctx: GremlinParser.TraversalMethod_barrier_intContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_both.
    def enterTraversalMethod_both(self, ctx: GremlinParser.TraversalMethod_bothContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_both.
    def exitTraversalMethod_both(self, ctx: GremlinParser.TraversalMethod_bothContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_bothE.
    def enterTraversalMethod_bothE(self, ctx: GremlinParser.TraversalMethod_bothEContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_bothE.
    def exitTraversalMethod_bothE(self, ctx: GremlinParser.TraversalMethod_bothEContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_bothV.
    def enterTraversalMethod_bothV(self, ctx: GremlinParser.TraversalMethod_bothVContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_bothV.
    def exitTraversalMethod_bothV(self, ctx: GremlinParser.TraversalMethod_bothVContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_branch.
    def enterTraversalMethod_branch(self, ctx: GremlinParser.TraversalMethod_branchContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_branch.
    def exitTraversalMethod_branch(self, ctx: GremlinParser.TraversalMethod_branchContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_by_Comparator.
    def enterTraversalMethod_by_Comparator(self, ctx: GremlinParser.TraversalMethod_by_ComparatorContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_by_Comparator.
    def exitTraversalMethod_by_Comparator(self, ctx: GremlinParser.TraversalMethod_by_ComparatorContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_by_Empty.
    def enterTraversalMethod_by_Empty(self, ctx: GremlinParser.TraversalMethod_by_EmptyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_by_Empty.
    def exitTraversalMethod_by_Empty(self, ctx: GremlinParser.TraversalMethod_by_EmptyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_by_Function.
    def enterTraversalMethod_by_Function(self, ctx: GremlinParser.TraversalMethod_by_FunctionContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_by_Function.
    def exitTraversalMethod_by_Function(self, ctx: GremlinParser.TraversalMethod_by_FunctionContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_by_Function_Comparator.
    def enterTraversalMethod_by_Function_Comparator(
        self, ctx: GremlinParser.TraversalMethod_by_Function_ComparatorContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_by_Function_Comparator.
    def exitTraversalMethod_by_Function_Comparator(
        self, ctx: GremlinParser.TraversalMethod_by_Function_ComparatorContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_by_Order.
    def enterTraversalMethod_by_Order(self, ctx: GremlinParser.TraversalMethod_by_OrderContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_by_Order.
    def exitTraversalMethod_by_Order(self, ctx: GremlinParser.TraversalMethod_by_OrderContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_by_String.
    def enterTraversalMethod_by_String(self, ctx: GremlinParser.TraversalMethod_by_StringContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_by_String.
    def exitTraversalMethod_by_String(self, ctx: GremlinParser.TraversalMethod_by_StringContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_by_String_Comparator.
    def enterTraversalMethod_by_String_Comparator(self, ctx: GremlinParser.TraversalMethod_by_String_ComparatorContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_by_String_Comparator.
    def exitTraversalMethod_by_String_Comparator(self, ctx: GremlinParser.TraversalMethod_by_String_ComparatorContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_by_T.
    def enterTraversalMethod_by_T(self, ctx: GremlinParser.TraversalMethod_by_TContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_by_T.
    def exitTraversalMethod_by_T(self, ctx: GremlinParser.TraversalMethod_by_TContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_by_Traversal.
    def enterTraversalMethod_by_Traversal(self, ctx: GremlinParser.TraversalMethod_by_TraversalContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_by_Traversal.
    def exitTraversalMethod_by_Traversal(self, ctx: GremlinParser.TraversalMethod_by_TraversalContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_by_Traversal_Comparator.
    def enterTraversalMethod_by_Traversal_Comparator(
        self, ctx: GremlinParser.TraversalMethod_by_Traversal_ComparatorContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_by_Traversal_Comparator.
    def exitTraversalMethod_by_Traversal_Comparator(
        self, ctx: GremlinParser.TraversalMethod_by_Traversal_ComparatorContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_call_string.
    def enterTraversalMethod_call_string(self, ctx: GremlinParser.TraversalMethod_call_stringContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_call_string.
    def exitTraversalMethod_call_string(self, ctx: GremlinParser.TraversalMethod_call_stringContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_call_string_map.
    def enterTraversalMethod_call_string_map(self, ctx: GremlinParser.TraversalMethod_call_string_mapContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_call_string_map.
    def exitTraversalMethod_call_string_map(self, ctx: GremlinParser.TraversalMethod_call_string_mapContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_call_string_traversal.
    def enterTraversalMethod_call_string_traversal(
        self, ctx: GremlinParser.TraversalMethod_call_string_traversalContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_call_string_traversal.
    def exitTraversalMethod_call_string_traversal(
        self, ctx: GremlinParser.TraversalMethod_call_string_traversalContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_call_string_map_traversal.
    def enterTraversalMethod_call_string_map_traversal(
        self, ctx: GremlinParser.TraversalMethod_call_string_map_traversalContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_call_string_map_traversal.
    def exitTraversalMethod_call_string_map_traversal(
        self, ctx: GremlinParser.TraversalMethod_call_string_map_traversalContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_cap.
    def enterTraversalMethod_cap(self, ctx: GremlinParser.TraversalMethod_capContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_cap.
    def exitTraversalMethod_cap(self, ctx: GremlinParser.TraversalMethod_capContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_choose_Function.
    def enterTraversalMethod_choose_Function(self, ctx: GremlinParser.TraversalMethod_choose_FunctionContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_choose_Function.
    def exitTraversalMethod_choose_Function(self, ctx: GremlinParser.TraversalMethod_choose_FunctionContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_choose_Predicate_Traversal.
    def enterTraversalMethod_choose_Predicate_Traversal(
        self, ctx: GremlinParser.TraversalMethod_choose_Predicate_TraversalContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_choose_Predicate_Traversal.
    def exitTraversalMethod_choose_Predicate_Traversal(
        self, ctx: GremlinParser.TraversalMethod_choose_Predicate_TraversalContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_choose_Predicate_Traversal_Traversal.
    def enterTraversalMethod_choose_Predicate_Traversal_Traversal(
        self, ctx: GremlinParser.TraversalMethod_choose_Predicate_Traversal_TraversalContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_choose_Predicate_Traversal_Traversal.
    def exitTraversalMethod_choose_Predicate_Traversal_Traversal(
        self, ctx: GremlinParser.TraversalMethod_choose_Predicate_Traversal_TraversalContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_choose_Traversal.
    def enterTraversalMethod_choose_Traversal(self, ctx: GremlinParser.TraversalMethod_choose_TraversalContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_choose_Traversal.
    def exitTraversalMethod_choose_Traversal(self, ctx: GremlinParser.TraversalMethod_choose_TraversalContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_choose_Traversal_Traversal.
    def enterTraversalMethod_choose_Traversal_Traversal(
        self, ctx: GremlinParser.TraversalMethod_choose_Traversal_TraversalContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_choose_Traversal_Traversal.
    def exitTraversalMethod_choose_Traversal_Traversal(
        self, ctx: GremlinParser.TraversalMethod_choose_Traversal_TraversalContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_choose_Traversal_Traversal_Traversal.
    def enterTraversalMethod_choose_Traversal_Traversal_Traversal(
        self, ctx: GremlinParser.TraversalMethod_choose_Traversal_Traversal_TraversalContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_choose_Traversal_Traversal_Traversal.
    def exitTraversalMethod_choose_Traversal_Traversal_Traversal(
        self, ctx: GremlinParser.TraversalMethod_choose_Traversal_Traversal_TraversalContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_coalesce.
    def enterTraversalMethod_coalesce(self, ctx: GremlinParser.TraversalMethod_coalesceContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_coalesce.
    def exitTraversalMethod_coalesce(self, ctx: GremlinParser.TraversalMethod_coalesceContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_coin.
    def enterTraversalMethod_coin(self, ctx: GremlinParser.TraversalMethod_coinContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_coin.
    def exitTraversalMethod_coin(self, ctx: GremlinParser.TraversalMethod_coinContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_combine_Object.
    def enterTraversalMethod_combine_Object(self, ctx: GremlinParser.TraversalMethod_combine_ObjectContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_combine_Object.
    def exitTraversalMethod_combine_Object(self, ctx: GremlinParser.TraversalMethod_combine_ObjectContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_concat_Traversal_Traversal.
    def enterTraversalMethod_concat_Traversal_Traversal(
        self, ctx: GremlinParser.TraversalMethod_concat_Traversal_TraversalContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_concat_Traversal_Traversal.
    def exitTraversalMethod_concat_Traversal_Traversal(
        self, ctx: GremlinParser.TraversalMethod_concat_Traversal_TraversalContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_concat_String.
    def enterTraversalMethod_concat_String(self, ctx: GremlinParser.TraversalMethod_concat_StringContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_concat_String.
    def exitTraversalMethod_concat_String(self, ctx: GremlinParser.TraversalMethod_concat_StringContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_conjoin_String.
    def enterTraversalMethod_conjoin_String(self, ctx: GremlinParser.TraversalMethod_conjoin_StringContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_conjoin_String.
    def exitTraversalMethod_conjoin_String(self, ctx: GremlinParser.TraversalMethod_conjoin_StringContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_connectedComponent.
    def enterTraversalMethod_connectedComponent(self, ctx: GremlinParser.TraversalMethod_connectedComponentContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_connectedComponent.
    def exitTraversalMethod_connectedComponent(self, ctx: GremlinParser.TraversalMethod_connectedComponentContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_constant.
    def enterTraversalMethod_constant(self, ctx: GremlinParser.TraversalMethod_constantContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_constant.
    def exitTraversalMethod_constant(self, ctx: GremlinParser.TraversalMethod_constantContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_count_Empty.
    def enterTraversalMethod_count_Empty(self, ctx: GremlinParser.TraversalMethod_count_EmptyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_count_Empty.
    def exitTraversalMethod_count_Empty(self, ctx: GremlinParser.TraversalMethod_count_EmptyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_count_Scope.
    def enterTraversalMethod_count_Scope(self, ctx: GremlinParser.TraversalMethod_count_ScopeContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_count_Scope.
    def exitTraversalMethod_count_Scope(self, ctx: GremlinParser.TraversalMethod_count_ScopeContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_cyclicPath.
    def enterTraversalMethod_cyclicPath(self, ctx: GremlinParser.TraversalMethod_cyclicPathContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_cyclicPath.
    def exitTraversalMethod_cyclicPath(self, ctx: GremlinParser.TraversalMethod_cyclicPathContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_dateAdd.
    def enterTraversalMethod_dateAdd(self, ctx: GremlinParser.TraversalMethod_dateAddContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_dateAdd.
    def exitTraversalMethod_dateAdd(self, ctx: GremlinParser.TraversalMethod_dateAddContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_dateDiff_Traversal.
    def enterTraversalMethod_dateDiff_Traversal(self, ctx: GremlinParser.TraversalMethod_dateDiff_TraversalContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_dateDiff_Traversal.
    def exitTraversalMethod_dateDiff_Traversal(self, ctx: GremlinParser.TraversalMethod_dateDiff_TraversalContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_dateDiff_Date.
    def enterTraversalMethod_dateDiff_Date(self, ctx: GremlinParser.TraversalMethod_dateDiff_DateContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_dateDiff_Date.
    def exitTraversalMethod_dateDiff_Date(self, ctx: GremlinParser.TraversalMethod_dateDiff_DateContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_dedup_Scope_String.
    def enterTraversalMethod_dedup_Scope_String(self, ctx: GremlinParser.TraversalMethod_dedup_Scope_StringContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_dedup_Scope_String.
    def exitTraversalMethod_dedup_Scope_String(self, ctx: GremlinParser.TraversalMethod_dedup_Scope_StringContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_dedup_String.
    def enterTraversalMethod_dedup_String(self, ctx: GremlinParser.TraversalMethod_dedup_StringContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_dedup_String.
    def exitTraversalMethod_dedup_String(self, ctx: GremlinParser.TraversalMethod_dedup_StringContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_difference_Object.
    def enterTraversalMethod_difference_Object(self, ctx: GremlinParser.TraversalMethod_difference_ObjectContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_difference_Object.
    def exitTraversalMethod_difference_Object(self, ctx: GremlinParser.TraversalMethod_difference_ObjectContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_discard.
    def enterTraversalMethod_discard(self, ctx: GremlinParser.TraversalMethod_discardContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_discard.
    def exitTraversalMethod_discard(self, ctx: GremlinParser.TraversalMethod_discardContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_disjunct_Object.
    def enterTraversalMethod_disjunct_Object(self, ctx: GremlinParser.TraversalMethod_disjunct_ObjectContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_disjunct_Object.
    def exitTraversalMethod_disjunct_Object(self, ctx: GremlinParser.TraversalMethod_disjunct_ObjectContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_drop.
    def enterTraversalMethod_drop(self, ctx: GremlinParser.TraversalMethod_dropContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_drop.
    def exitTraversalMethod_drop(self, ctx: GremlinParser.TraversalMethod_dropContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_element.
    def enterTraversalMethod_element(self, ctx: GremlinParser.TraversalMethod_elementContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_element.
    def exitTraversalMethod_element(self, ctx: GremlinParser.TraversalMethod_elementContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_elementMap.
    def enterTraversalMethod_elementMap(self, ctx: GremlinParser.TraversalMethod_elementMapContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_elementMap.
    def exitTraversalMethod_elementMap(self, ctx: GremlinParser.TraversalMethod_elementMapContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_emit_Empty.
    def enterTraversalMethod_emit_Empty(self, ctx: GremlinParser.TraversalMethod_emit_EmptyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_emit_Empty.
    def exitTraversalMethod_emit_Empty(self, ctx: GremlinParser.TraversalMethod_emit_EmptyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_emit_Predicate.
    def enterTraversalMethod_emit_Predicate(self, ctx: GremlinParser.TraversalMethod_emit_PredicateContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_emit_Predicate.
    def exitTraversalMethod_emit_Predicate(self, ctx: GremlinParser.TraversalMethod_emit_PredicateContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_emit_Traversal.
    def enterTraversalMethod_emit_Traversal(self, ctx: GremlinParser.TraversalMethod_emit_TraversalContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_emit_Traversal.
    def exitTraversalMethod_emit_Traversal(self, ctx: GremlinParser.TraversalMethod_emit_TraversalContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_fail_Empty.
    def enterTraversalMethod_fail_Empty(self, ctx: GremlinParser.TraversalMethod_fail_EmptyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_fail_Empty.
    def exitTraversalMethod_fail_Empty(self, ctx: GremlinParser.TraversalMethod_fail_EmptyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_fail_String.
    def enterTraversalMethod_fail_String(self, ctx: GremlinParser.TraversalMethod_fail_StringContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_fail_String.
    def exitTraversalMethod_fail_String(self, ctx: GremlinParser.TraversalMethod_fail_StringContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_filter_Predicate.
    def enterTraversalMethod_filter_Predicate(self, ctx: GremlinParser.TraversalMethod_filter_PredicateContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_filter_Predicate.
    def exitTraversalMethod_filter_Predicate(self, ctx: GremlinParser.TraversalMethod_filter_PredicateContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_filter_Traversal.
    def enterTraversalMethod_filter_Traversal(self, ctx: GremlinParser.TraversalMethod_filter_TraversalContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_filter_Traversal.
    def exitTraversalMethod_filter_Traversal(self, ctx: GremlinParser.TraversalMethod_filter_TraversalContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_flatMap.
    def enterTraversalMethod_flatMap(self, ctx: GremlinParser.TraversalMethod_flatMapContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_flatMap.
    def exitTraversalMethod_flatMap(self, ctx: GremlinParser.TraversalMethod_flatMapContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_fold_Empty.
    def enterTraversalMethod_fold_Empty(self, ctx: GremlinParser.TraversalMethod_fold_EmptyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_fold_Empty.
    def exitTraversalMethod_fold_Empty(self, ctx: GremlinParser.TraversalMethod_fold_EmptyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_fold_Object_BiFunction.
    def enterTraversalMethod_fold_Object_BiFunction(
        self, ctx: GremlinParser.TraversalMethod_fold_Object_BiFunctionContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_fold_Object_BiFunction.
    def exitTraversalMethod_fold_Object_BiFunction(
        self, ctx: GremlinParser.TraversalMethod_fold_Object_BiFunctionContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_format_String.
    def enterTraversalMethod_format_String(self, ctx: GremlinParser.TraversalMethod_format_StringContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_format_String.
    def exitTraversalMethod_format_String(self, ctx: GremlinParser.TraversalMethod_format_StringContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_from_String.
    def enterTraversalMethod_from_String(self, ctx: GremlinParser.TraversalMethod_from_StringContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_from_String.
    def exitTraversalMethod_from_String(self, ctx: GremlinParser.TraversalMethod_from_StringContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_from_Vertex.
    def enterTraversalMethod_from_Vertex(self, ctx: GremlinParser.TraversalMethod_from_VertexContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_from_Vertex.
    def exitTraversalMethod_from_Vertex(self, ctx: GremlinParser.TraversalMethod_from_VertexContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_from_Traversal.
    def enterTraversalMethod_from_Traversal(self, ctx: GremlinParser.TraversalMethod_from_TraversalContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_from_Traversal.
    def exitTraversalMethod_from_Traversal(self, ctx: GremlinParser.TraversalMethod_from_TraversalContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_group_Empty.
    def enterTraversalMethod_group_Empty(self, ctx: GremlinParser.TraversalMethod_group_EmptyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_group_Empty.
    def exitTraversalMethod_group_Empty(self, ctx: GremlinParser.TraversalMethod_group_EmptyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_group_String.
    def enterTraversalMethod_group_String(self, ctx: GremlinParser.TraversalMethod_group_StringContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_group_String.
    def exitTraversalMethod_group_String(self, ctx: GremlinParser.TraversalMethod_group_StringContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_groupCount_Empty.
    def enterTraversalMethod_groupCount_Empty(self, ctx: GremlinParser.TraversalMethod_groupCount_EmptyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_groupCount_Empty.
    def exitTraversalMethod_groupCount_Empty(self, ctx: GremlinParser.TraversalMethod_groupCount_EmptyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_groupCount_String.
    def enterTraversalMethod_groupCount_String(self, ctx: GremlinParser.TraversalMethod_groupCount_StringContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_groupCount_String.
    def exitTraversalMethod_groupCount_String(self, ctx: GremlinParser.TraversalMethod_groupCount_StringContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_has_String.
    def enterTraversalMethod_has_String(self, ctx: GremlinParser.TraversalMethod_has_StringContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_has_String.
    def exitTraversalMethod_has_String(self, ctx: GremlinParser.TraversalMethod_has_StringContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_has_String_Object.
    def enterTraversalMethod_has_String_Object(self, ctx: GremlinParser.TraversalMethod_has_String_ObjectContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_has_String_Object.
    def exitTraversalMethod_has_String_Object(self, ctx: GremlinParser.TraversalMethod_has_String_ObjectContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_has_String_P.
    def enterTraversalMethod_has_String_P(self, ctx: GremlinParser.TraversalMethod_has_String_PContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_has_String_P.
    def exitTraversalMethod_has_String_P(self, ctx: GremlinParser.TraversalMethod_has_String_PContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_has_String_String_Object.
    def enterTraversalMethod_has_String_String_Object(
        self, ctx: GremlinParser.TraversalMethod_has_String_String_ObjectContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_has_String_String_Object.
    def exitTraversalMethod_has_String_String_Object(
        self, ctx: GremlinParser.TraversalMethod_has_String_String_ObjectContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_has_String_String_P.
    def enterTraversalMethod_has_String_String_P(self, ctx: GremlinParser.TraversalMethod_has_String_String_PContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_has_String_String_P.
    def exitTraversalMethod_has_String_String_P(self, ctx: GremlinParser.TraversalMethod_has_String_String_PContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_has_String_Traversal.
    def enterTraversalMethod_has_String_Traversal(self, ctx: GremlinParser.TraversalMethod_has_String_TraversalContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_has_String_Traversal.
    def exitTraversalMethod_has_String_Traversal(self, ctx: GremlinParser.TraversalMethod_has_String_TraversalContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_has_T_Object.
    def enterTraversalMethod_has_T_Object(self, ctx: GremlinParser.TraversalMethod_has_T_ObjectContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_has_T_Object.
    def exitTraversalMethod_has_T_Object(self, ctx: GremlinParser.TraversalMethod_has_T_ObjectContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_has_T_P.
    def enterTraversalMethod_has_T_P(self, ctx: GremlinParser.TraversalMethod_has_T_PContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_has_T_P.
    def exitTraversalMethod_has_T_P(self, ctx: GremlinParser.TraversalMethod_has_T_PContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_has_T_Traversal.
    def enterTraversalMethod_has_T_Traversal(self, ctx: GremlinParser.TraversalMethod_has_T_TraversalContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_has_T_Traversal.
    def exitTraversalMethod_has_T_Traversal(self, ctx: GremlinParser.TraversalMethod_has_T_TraversalContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_hasId_Object_Object.
    def enterTraversalMethod_hasId_Object_Object(self, ctx: GremlinParser.TraversalMethod_hasId_Object_ObjectContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_hasId_Object_Object.
    def exitTraversalMethod_hasId_Object_Object(self, ctx: GremlinParser.TraversalMethod_hasId_Object_ObjectContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_hasId_P.
    def enterTraversalMethod_hasId_P(self, ctx: GremlinParser.TraversalMethod_hasId_PContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_hasId_P.
    def exitTraversalMethod_hasId_P(self, ctx: GremlinParser.TraversalMethod_hasId_PContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_hasKey_P.
    def enterTraversalMethod_hasKey_P(self, ctx: GremlinParser.TraversalMethod_hasKey_PContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_hasKey_P.
    def exitTraversalMethod_hasKey_P(self, ctx: GremlinParser.TraversalMethod_hasKey_PContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_hasKey_String_String.
    def enterTraversalMethod_hasKey_String_String(self, ctx: GremlinParser.TraversalMethod_hasKey_String_StringContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_hasKey_String_String.
    def exitTraversalMethod_hasKey_String_String(self, ctx: GremlinParser.TraversalMethod_hasKey_String_StringContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_hasLabel_P.
    def enterTraversalMethod_hasLabel_P(self, ctx: GremlinParser.TraversalMethod_hasLabel_PContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_hasLabel_P.
    def exitTraversalMethod_hasLabel_P(self, ctx: GremlinParser.TraversalMethod_hasLabel_PContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_hasLabel_String_String.
    def enterTraversalMethod_hasLabel_String_String(
        self, ctx: GremlinParser.TraversalMethod_hasLabel_String_StringContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_hasLabel_String_String.
    def exitTraversalMethod_hasLabel_String_String(
        self, ctx: GremlinParser.TraversalMethod_hasLabel_String_StringContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_hasNot.
    def enterTraversalMethod_hasNot(self, ctx: GremlinParser.TraversalMethod_hasNotContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_hasNot.
    def exitTraversalMethod_hasNot(self, ctx: GremlinParser.TraversalMethod_hasNotContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_hasValue_Object_Object.
    def enterTraversalMethod_hasValue_Object_Object(
        self, ctx: GremlinParser.TraversalMethod_hasValue_Object_ObjectContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_hasValue_Object_Object.
    def exitTraversalMethod_hasValue_Object_Object(
        self, ctx: GremlinParser.TraversalMethod_hasValue_Object_ObjectContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_hasValue_P.
    def enterTraversalMethod_hasValue_P(self, ctx: GremlinParser.TraversalMethod_hasValue_PContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_hasValue_P.
    def exitTraversalMethod_hasValue_P(self, ctx: GremlinParser.TraversalMethod_hasValue_PContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_id.
    def enterTraversalMethod_id(self, ctx: GremlinParser.TraversalMethod_idContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_id.
    def exitTraversalMethod_id(self, ctx: GremlinParser.TraversalMethod_idContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_identity.
    def enterTraversalMethod_identity(self, ctx: GremlinParser.TraversalMethod_identityContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_identity.
    def exitTraversalMethod_identity(self, ctx: GremlinParser.TraversalMethod_identityContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_in.
    def enterTraversalMethod_in(self, ctx: GremlinParser.TraversalMethod_inContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_in.
    def exitTraversalMethod_in(self, ctx: GremlinParser.TraversalMethod_inContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_inE.
    def enterTraversalMethod_inE(self, ctx: GremlinParser.TraversalMethod_inEContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_inE.
    def exitTraversalMethod_inE(self, ctx: GremlinParser.TraversalMethod_inEContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_intersect_Object.
    def enterTraversalMethod_intersect_Object(self, ctx: GremlinParser.TraversalMethod_intersect_ObjectContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_intersect_Object.
    def exitTraversalMethod_intersect_Object(self, ctx: GremlinParser.TraversalMethod_intersect_ObjectContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_inV.
    def enterTraversalMethod_inV(self, ctx: GremlinParser.TraversalMethod_inVContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_inV.
    def exitTraversalMethod_inV(self, ctx: GremlinParser.TraversalMethod_inVContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_index.
    def enterTraversalMethod_index(self, ctx: GremlinParser.TraversalMethod_indexContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_index.
    def exitTraversalMethod_index(self, ctx: GremlinParser.TraversalMethod_indexContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_inject.
    def enterTraversalMethod_inject(self, ctx: GremlinParser.TraversalMethod_injectContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_inject.
    def exitTraversalMethod_inject(self, ctx: GremlinParser.TraversalMethod_injectContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_is_Object.
    def enterTraversalMethod_is_Object(self, ctx: GremlinParser.TraversalMethod_is_ObjectContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_is_Object.
    def exitTraversalMethod_is_Object(self, ctx: GremlinParser.TraversalMethod_is_ObjectContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_is_P.
    def enterTraversalMethod_is_P(self, ctx: GremlinParser.TraversalMethod_is_PContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_is_P.
    def exitTraversalMethod_is_P(self, ctx: GremlinParser.TraversalMethod_is_PContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_key.
    def enterTraversalMethod_key(self, ctx: GremlinParser.TraversalMethod_keyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_key.
    def exitTraversalMethod_key(self, ctx: GremlinParser.TraversalMethod_keyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_label.
    def enterTraversalMethod_label(self, ctx: GremlinParser.TraversalMethod_labelContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_label.
    def exitTraversalMethod_label(self, ctx: GremlinParser.TraversalMethod_labelContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_length_Empty.
    def enterTraversalMethod_length_Empty(self, ctx: GremlinParser.TraversalMethod_length_EmptyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_length_Empty.
    def exitTraversalMethod_length_Empty(self, ctx: GremlinParser.TraversalMethod_length_EmptyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_length_Scope.
    def enterTraversalMethod_length_Scope(self, ctx: GremlinParser.TraversalMethod_length_ScopeContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_length_Scope.
    def exitTraversalMethod_length_Scope(self, ctx: GremlinParser.TraversalMethod_length_ScopeContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_limit_Scope_long.
    def enterTraversalMethod_limit_Scope_long(self, ctx: GremlinParser.TraversalMethod_limit_Scope_longContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_limit_Scope_long.
    def exitTraversalMethod_limit_Scope_long(self, ctx: GremlinParser.TraversalMethod_limit_Scope_longContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_limit_long.
    def enterTraversalMethod_limit_long(self, ctx: GremlinParser.TraversalMethod_limit_longContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_limit_long.
    def exitTraversalMethod_limit_long(self, ctx: GremlinParser.TraversalMethod_limit_longContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_local.
    def enterTraversalMethod_local(self, ctx: GremlinParser.TraversalMethod_localContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_local.
    def exitTraversalMethod_local(self, ctx: GremlinParser.TraversalMethod_localContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_loops_Empty.
    def enterTraversalMethod_loops_Empty(self, ctx: GremlinParser.TraversalMethod_loops_EmptyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_loops_Empty.
    def exitTraversalMethod_loops_Empty(self, ctx: GremlinParser.TraversalMethod_loops_EmptyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_loops_String.
    def enterTraversalMethod_loops_String(self, ctx: GremlinParser.TraversalMethod_loops_StringContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_loops_String.
    def exitTraversalMethod_loops_String(self, ctx: GremlinParser.TraversalMethod_loops_StringContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_lTrim_Empty.
    def enterTraversalMethod_lTrim_Empty(self, ctx: GremlinParser.TraversalMethod_lTrim_EmptyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_lTrim_Empty.
    def exitTraversalMethod_lTrim_Empty(self, ctx: GremlinParser.TraversalMethod_lTrim_EmptyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_lTrim_Scope.
    def enterTraversalMethod_lTrim_Scope(self, ctx: GremlinParser.TraversalMethod_lTrim_ScopeContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_lTrim_Scope.
    def exitTraversalMethod_lTrim_Scope(self, ctx: GremlinParser.TraversalMethod_lTrim_ScopeContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_map.
    def enterTraversalMethod_map(self, ctx: GremlinParser.TraversalMethod_mapContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_map.
    def exitTraversalMethod_map(self, ctx: GremlinParser.TraversalMethod_mapContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_match.
    def enterTraversalMethod_match(self, ctx: GremlinParser.TraversalMethod_matchContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_match.
    def exitTraversalMethod_match(self, ctx: GremlinParser.TraversalMethod_matchContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_math.
    def enterTraversalMethod_math(self, ctx: GremlinParser.TraversalMethod_mathContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_math.
    def exitTraversalMethod_math(self, ctx: GremlinParser.TraversalMethod_mathContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_max_Empty.
    def enterTraversalMethod_max_Empty(self, ctx: GremlinParser.TraversalMethod_max_EmptyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_max_Empty.
    def exitTraversalMethod_max_Empty(self, ctx: GremlinParser.TraversalMethod_max_EmptyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_max_Scope.
    def enterTraversalMethod_max_Scope(self, ctx: GremlinParser.TraversalMethod_max_ScopeContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_max_Scope.
    def exitTraversalMethod_max_Scope(self, ctx: GremlinParser.TraversalMethod_max_ScopeContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_mean_Empty.
    def enterTraversalMethod_mean_Empty(self, ctx: GremlinParser.TraversalMethod_mean_EmptyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_mean_Empty.
    def exitTraversalMethod_mean_Empty(self, ctx: GremlinParser.TraversalMethod_mean_EmptyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_mean_Scope.
    def enterTraversalMethod_mean_Scope(self, ctx: GremlinParser.TraversalMethod_mean_ScopeContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_mean_Scope.
    def exitTraversalMethod_mean_Scope(self, ctx: GremlinParser.TraversalMethod_mean_ScopeContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_merge_Object.
    def enterTraversalMethod_merge_Object(self, ctx: GremlinParser.TraversalMethod_merge_ObjectContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_merge_Object.
    def exitTraversalMethod_merge_Object(self, ctx: GremlinParser.TraversalMethod_merge_ObjectContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_mergeV_empty.
    def enterTraversalMethod_mergeV_empty(self, ctx: GremlinParser.TraversalMethod_mergeV_emptyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_mergeV_empty.
    def exitTraversalMethod_mergeV_empty(self, ctx: GremlinParser.TraversalMethod_mergeV_emptyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_mergeV_Map.
    def enterTraversalMethod_mergeV_Map(self, ctx: GremlinParser.TraversalMethod_mergeV_MapContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_mergeV_Map.
    def exitTraversalMethod_mergeV_Map(self, ctx: GremlinParser.TraversalMethod_mergeV_MapContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_mergeV_Traversal.
    def enterTraversalMethod_mergeV_Traversal(self, ctx: GremlinParser.TraversalMethod_mergeV_TraversalContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_mergeV_Traversal.
    def exitTraversalMethod_mergeV_Traversal(self, ctx: GremlinParser.TraversalMethod_mergeV_TraversalContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_mergeE_empty.
    def enterTraversalMethod_mergeE_empty(self, ctx: GremlinParser.TraversalMethod_mergeE_emptyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_mergeE_empty.
    def exitTraversalMethod_mergeE_empty(self, ctx: GremlinParser.TraversalMethod_mergeE_emptyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_mergeE_Map.
    def enterTraversalMethod_mergeE_Map(self, ctx: GremlinParser.TraversalMethod_mergeE_MapContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_mergeE_Map.
    def exitTraversalMethod_mergeE_Map(self, ctx: GremlinParser.TraversalMethod_mergeE_MapContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_mergeE_Traversal.
    def enterTraversalMethod_mergeE_Traversal(self, ctx: GremlinParser.TraversalMethod_mergeE_TraversalContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_mergeE_Traversal.
    def exitTraversalMethod_mergeE_Traversal(self, ctx: GremlinParser.TraversalMethod_mergeE_TraversalContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_min_Empty.
    def enterTraversalMethod_min_Empty(self, ctx: GremlinParser.TraversalMethod_min_EmptyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_min_Empty.
    def exitTraversalMethod_min_Empty(self, ctx: GremlinParser.TraversalMethod_min_EmptyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_min_Scope.
    def enterTraversalMethod_min_Scope(self, ctx: GremlinParser.TraversalMethod_min_ScopeContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_min_Scope.
    def exitTraversalMethod_min_Scope(self, ctx: GremlinParser.TraversalMethod_min_ScopeContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_none_P.
    def enterTraversalMethod_none_P(self, ctx: GremlinParser.TraversalMethod_none_PContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_none_P.
    def exitTraversalMethod_none_P(self, ctx: GremlinParser.TraversalMethod_none_PContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_not.
    def enterTraversalMethod_not(self, ctx: GremlinParser.TraversalMethod_notContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_not.
    def exitTraversalMethod_not(self, ctx: GremlinParser.TraversalMethod_notContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_option_Predicate_Traversal.
    def enterTraversalMethod_option_Predicate_Traversal(
        self, ctx: GremlinParser.TraversalMethod_option_Predicate_TraversalContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_option_Predicate_Traversal.
    def exitTraversalMethod_option_Predicate_Traversal(
        self, ctx: GremlinParser.TraversalMethod_option_Predicate_TraversalContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_option_Merge_Map.
    def enterTraversalMethod_option_Merge_Map(self, ctx: GremlinParser.TraversalMethod_option_Merge_MapContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_option_Merge_Map.
    def exitTraversalMethod_option_Merge_Map(self, ctx: GremlinParser.TraversalMethod_option_Merge_MapContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_option_Merge_Map_Cardinality.
    def enterTraversalMethod_option_Merge_Map_Cardinality(
        self, ctx: GremlinParser.TraversalMethod_option_Merge_Map_CardinalityContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_option_Merge_Map_Cardinality.
    def exitTraversalMethod_option_Merge_Map_Cardinality(
        self, ctx: GremlinParser.TraversalMethod_option_Merge_Map_CardinalityContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_option_Merge_Traversal.
    def enterTraversalMethod_option_Merge_Traversal(
        self, ctx: GremlinParser.TraversalMethod_option_Merge_TraversalContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_option_Merge_Traversal.
    def exitTraversalMethod_option_Merge_Traversal(
        self, ctx: GremlinParser.TraversalMethod_option_Merge_TraversalContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_option_Object_Traversal.
    def enterTraversalMethod_option_Object_Traversal(
        self, ctx: GremlinParser.TraversalMethod_option_Object_TraversalContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_option_Object_Traversal.
    def exitTraversalMethod_option_Object_Traversal(
        self, ctx: GremlinParser.TraversalMethod_option_Object_TraversalContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_option_Traversal.
    def enterTraversalMethod_option_Traversal(self, ctx: GremlinParser.TraversalMethod_option_TraversalContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_option_Traversal.
    def exitTraversalMethod_option_Traversal(self, ctx: GremlinParser.TraversalMethod_option_TraversalContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_optional.
    def enterTraversalMethod_optional(self, ctx: GremlinParser.TraversalMethod_optionalContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_optional.
    def exitTraversalMethod_optional(self, ctx: GremlinParser.TraversalMethod_optionalContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_or.
    def enterTraversalMethod_or(self, ctx: GremlinParser.TraversalMethod_orContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_or.
    def exitTraversalMethod_or(self, ctx: GremlinParser.TraversalMethod_orContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_order_Empty.
    def enterTraversalMethod_order_Empty(self, ctx: GremlinParser.TraversalMethod_order_EmptyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_order_Empty.
    def exitTraversalMethod_order_Empty(self, ctx: GremlinParser.TraversalMethod_order_EmptyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_order_Scope.
    def enterTraversalMethod_order_Scope(self, ctx: GremlinParser.TraversalMethod_order_ScopeContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_order_Scope.
    def exitTraversalMethod_order_Scope(self, ctx: GremlinParser.TraversalMethod_order_ScopeContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_otherV.
    def enterTraversalMethod_otherV(self, ctx: GremlinParser.TraversalMethod_otherVContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_otherV.
    def exitTraversalMethod_otherV(self, ctx: GremlinParser.TraversalMethod_otherVContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_out.
    def enterTraversalMethod_out(self, ctx: GremlinParser.TraversalMethod_outContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_out.
    def exitTraversalMethod_out(self, ctx: GremlinParser.TraversalMethod_outContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_outE.
    def enterTraversalMethod_outE(self, ctx: GremlinParser.TraversalMethod_outEContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_outE.
    def exitTraversalMethod_outE(self, ctx: GremlinParser.TraversalMethod_outEContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_outV.
    def enterTraversalMethod_outV(self, ctx: GremlinParser.TraversalMethod_outVContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_outV.
    def exitTraversalMethod_outV(self, ctx: GremlinParser.TraversalMethod_outVContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_pageRank_Empty.
    def enterTraversalMethod_pageRank_Empty(self, ctx: GremlinParser.TraversalMethod_pageRank_EmptyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_pageRank_Empty.
    def exitTraversalMethod_pageRank_Empty(self, ctx: GremlinParser.TraversalMethod_pageRank_EmptyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_pageRank_double.
    def enterTraversalMethod_pageRank_double(self, ctx: GremlinParser.TraversalMethod_pageRank_doubleContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_pageRank_double.
    def exitTraversalMethod_pageRank_double(self, ctx: GremlinParser.TraversalMethod_pageRank_doubleContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_path.
    def enterTraversalMethod_path(self, ctx: GremlinParser.TraversalMethod_pathContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_path.
    def exitTraversalMethod_path(self, ctx: GremlinParser.TraversalMethod_pathContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_peerPressure.
    def enterTraversalMethod_peerPressure(self, ctx: GremlinParser.TraversalMethod_peerPressureContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_peerPressure.
    def exitTraversalMethod_peerPressure(self, ctx: GremlinParser.TraversalMethod_peerPressureContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_product_Object.
    def enterTraversalMethod_product_Object(self, ctx: GremlinParser.TraversalMethod_product_ObjectContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_product_Object.
    def exitTraversalMethod_product_Object(self, ctx: GremlinParser.TraversalMethod_product_ObjectContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_profile_Empty.
    def enterTraversalMethod_profile_Empty(self, ctx: GremlinParser.TraversalMethod_profile_EmptyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_profile_Empty.
    def exitTraversalMethod_profile_Empty(self, ctx: GremlinParser.TraversalMethod_profile_EmptyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_profile_String.
    def enterTraversalMethod_profile_String(self, ctx: GremlinParser.TraversalMethod_profile_StringContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_profile_String.
    def exitTraversalMethod_profile_String(self, ctx: GremlinParser.TraversalMethod_profile_StringContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_project.
    def enterTraversalMethod_project(self, ctx: GremlinParser.TraversalMethod_projectContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_project.
    def exitTraversalMethod_project(self, ctx: GremlinParser.TraversalMethod_projectContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_properties.
    def enterTraversalMethod_properties(self, ctx: GremlinParser.TraversalMethod_propertiesContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_properties.
    def exitTraversalMethod_properties(self, ctx: GremlinParser.TraversalMethod_propertiesContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_property_Cardinality_Object_Object_Object.
    def enterTraversalMethod_property_Cardinality_Object_Object_Object(
        self, ctx: GremlinParser.TraversalMethod_property_Cardinality_Object_Object_ObjectContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_property_Cardinality_Object_Object_Object.
    def exitTraversalMethod_property_Cardinality_Object_Object_Object(
        self, ctx: GremlinParser.TraversalMethod_property_Cardinality_Object_Object_ObjectContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_property_Cardinality_Object.
    def enterTraversalMethod_property_Cardinality_Object(
        self, ctx: GremlinParser.TraversalMethod_property_Cardinality_ObjectContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_property_Cardinality_Object.
    def exitTraversalMethod_property_Cardinality_Object(
        self, ctx: GremlinParser.TraversalMethod_property_Cardinality_ObjectContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_property_Object_Object_Object.
    def enterTraversalMethod_property_Object_Object_Object(
        self, ctx: GremlinParser.TraversalMethod_property_Object_Object_ObjectContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_property_Object_Object_Object.
    def exitTraversalMethod_property_Object_Object_Object(
        self, ctx: GremlinParser.TraversalMethod_property_Object_Object_ObjectContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_property_Object.
    def enterTraversalMethod_property_Object(self, ctx: GremlinParser.TraversalMethod_property_ObjectContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_property_Object.
    def exitTraversalMethod_property_Object(self, ctx: GremlinParser.TraversalMethod_property_ObjectContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_propertyMap.
    def enterTraversalMethod_propertyMap(self, ctx: GremlinParser.TraversalMethod_propertyMapContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_propertyMap.
    def exitTraversalMethod_propertyMap(self, ctx: GremlinParser.TraversalMethod_propertyMapContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_range_Scope_long_long.
    def enterTraversalMethod_range_Scope_long_long(
        self, ctx: GremlinParser.TraversalMethod_range_Scope_long_longContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_range_Scope_long_long.
    def exitTraversalMethod_range_Scope_long_long(
        self, ctx: GremlinParser.TraversalMethod_range_Scope_long_longContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_range_long_long.
    def enterTraversalMethod_range_long_long(self, ctx: GremlinParser.TraversalMethod_range_long_longContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_range_long_long.
    def exitTraversalMethod_range_long_long(self, ctx: GremlinParser.TraversalMethod_range_long_longContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_read.
    def enterTraversalMethod_read(self, ctx: GremlinParser.TraversalMethod_readContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_read.
    def exitTraversalMethod_read(self, ctx: GremlinParser.TraversalMethod_readContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_repeat_String_Traversal.
    def enterTraversalMethod_repeat_String_Traversal(
        self, ctx: GremlinParser.TraversalMethod_repeat_String_TraversalContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_repeat_String_Traversal.
    def exitTraversalMethod_repeat_String_Traversal(
        self, ctx: GremlinParser.TraversalMethod_repeat_String_TraversalContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_repeat_Traversal.
    def enterTraversalMethod_repeat_Traversal(self, ctx: GremlinParser.TraversalMethod_repeat_TraversalContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_repeat_Traversal.
    def exitTraversalMethod_repeat_Traversal(self, ctx: GremlinParser.TraversalMethod_repeat_TraversalContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_replace_String_String.
    def enterTraversalMethod_replace_String_String(
        self, ctx: GremlinParser.TraversalMethod_replace_String_StringContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_replace_String_String.
    def exitTraversalMethod_replace_String_String(
        self, ctx: GremlinParser.TraversalMethod_replace_String_StringContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_replace_Scope_String_String.
    def enterTraversalMethod_replace_Scope_String_String(
        self, ctx: GremlinParser.TraversalMethod_replace_Scope_String_StringContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_replace_Scope_String_String.
    def exitTraversalMethod_replace_Scope_String_String(
        self, ctx: GremlinParser.TraversalMethod_replace_Scope_String_StringContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_reverse_Empty.
    def enterTraversalMethod_reverse_Empty(self, ctx: GremlinParser.TraversalMethod_reverse_EmptyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_reverse_Empty.
    def exitTraversalMethod_reverse_Empty(self, ctx: GremlinParser.TraversalMethod_reverse_EmptyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_rTrim_Empty.
    def enterTraversalMethod_rTrim_Empty(self, ctx: GremlinParser.TraversalMethod_rTrim_EmptyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_rTrim_Empty.
    def exitTraversalMethod_rTrim_Empty(self, ctx: GremlinParser.TraversalMethod_rTrim_EmptyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_rTrim_Scope.
    def enterTraversalMethod_rTrim_Scope(self, ctx: GremlinParser.TraversalMethod_rTrim_ScopeContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_rTrim_Scope.
    def exitTraversalMethod_rTrim_Scope(self, ctx: GremlinParser.TraversalMethod_rTrim_ScopeContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_sack_BiFunction.
    def enterTraversalMethod_sack_BiFunction(self, ctx: GremlinParser.TraversalMethod_sack_BiFunctionContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_sack_BiFunction.
    def exitTraversalMethod_sack_BiFunction(self, ctx: GremlinParser.TraversalMethod_sack_BiFunctionContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_sack_Empty.
    def enterTraversalMethod_sack_Empty(self, ctx: GremlinParser.TraversalMethod_sack_EmptyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_sack_Empty.
    def exitTraversalMethod_sack_Empty(self, ctx: GremlinParser.TraversalMethod_sack_EmptyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_sample_Scope_int.
    def enterTraversalMethod_sample_Scope_int(self, ctx: GremlinParser.TraversalMethod_sample_Scope_intContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_sample_Scope_int.
    def exitTraversalMethod_sample_Scope_int(self, ctx: GremlinParser.TraversalMethod_sample_Scope_intContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_sample_int.
    def enterTraversalMethod_sample_int(self, ctx: GremlinParser.TraversalMethod_sample_intContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_sample_int.
    def exitTraversalMethod_sample_int(self, ctx: GremlinParser.TraversalMethod_sample_intContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_select_Column.
    def enterTraversalMethod_select_Column(self, ctx: GremlinParser.TraversalMethod_select_ColumnContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_select_Column.
    def exitTraversalMethod_select_Column(self, ctx: GremlinParser.TraversalMethod_select_ColumnContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_select_Pop_String.
    def enterTraversalMethod_select_Pop_String(self, ctx: GremlinParser.TraversalMethod_select_Pop_StringContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_select_Pop_String.
    def exitTraversalMethod_select_Pop_String(self, ctx: GremlinParser.TraversalMethod_select_Pop_StringContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_select_Pop_String_String_String.
    def enterTraversalMethod_select_Pop_String_String_String(
        self, ctx: GremlinParser.TraversalMethod_select_Pop_String_String_StringContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_select_Pop_String_String_String.
    def exitTraversalMethod_select_Pop_String_String_String(
        self, ctx: GremlinParser.TraversalMethod_select_Pop_String_String_StringContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_select_Pop_Traversal.
    def enterTraversalMethod_select_Pop_Traversal(self, ctx: GremlinParser.TraversalMethod_select_Pop_TraversalContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_select_Pop_Traversal.
    def exitTraversalMethod_select_Pop_Traversal(self, ctx: GremlinParser.TraversalMethod_select_Pop_TraversalContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_select_String.
    def enterTraversalMethod_select_String(self, ctx: GremlinParser.TraversalMethod_select_StringContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_select_String.
    def exitTraversalMethod_select_String(self, ctx: GremlinParser.TraversalMethod_select_StringContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_select_String_String_String.
    def enterTraversalMethod_select_String_String_String(
        self, ctx: GremlinParser.TraversalMethod_select_String_String_StringContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_select_String_String_String.
    def exitTraversalMethod_select_String_String_String(
        self, ctx: GremlinParser.TraversalMethod_select_String_String_StringContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_select_Traversal.
    def enterTraversalMethod_select_Traversal(self, ctx: GremlinParser.TraversalMethod_select_TraversalContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_select_Traversal.
    def exitTraversalMethod_select_Traversal(self, ctx: GremlinParser.TraversalMethod_select_TraversalContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_shortestPath.
    def enterTraversalMethod_shortestPath(self, ctx: GremlinParser.TraversalMethod_shortestPathContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_shortestPath.
    def exitTraversalMethod_shortestPath(self, ctx: GremlinParser.TraversalMethod_shortestPathContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_sideEffect.
    def enterTraversalMethod_sideEffect(self, ctx: GremlinParser.TraversalMethod_sideEffectContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_sideEffect.
    def exitTraversalMethod_sideEffect(self, ctx: GremlinParser.TraversalMethod_sideEffectContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_simplePath.
    def enterTraversalMethod_simplePath(self, ctx: GremlinParser.TraversalMethod_simplePathContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_simplePath.
    def exitTraversalMethod_simplePath(self, ctx: GremlinParser.TraversalMethod_simplePathContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_skip_Scope_long.
    def enterTraversalMethod_skip_Scope_long(self, ctx: GremlinParser.TraversalMethod_skip_Scope_longContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_skip_Scope_long.
    def exitTraversalMethod_skip_Scope_long(self, ctx: GremlinParser.TraversalMethod_skip_Scope_longContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_skip_long.
    def enterTraversalMethod_skip_long(self, ctx: GremlinParser.TraversalMethod_skip_longContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_skip_long.
    def exitTraversalMethod_skip_long(self, ctx: GremlinParser.TraversalMethod_skip_longContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_split_String.
    def enterTraversalMethod_split_String(self, ctx: GremlinParser.TraversalMethod_split_StringContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_split_String.
    def exitTraversalMethod_split_String(self, ctx: GremlinParser.TraversalMethod_split_StringContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_split_Scope_String.
    def enterTraversalMethod_split_Scope_String(self, ctx: GremlinParser.TraversalMethod_split_Scope_StringContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_split_Scope_String.
    def exitTraversalMethod_split_Scope_String(self, ctx: GremlinParser.TraversalMethod_split_Scope_StringContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_store.
    def enterTraversalMethod_store(self, ctx: GremlinParser.TraversalMethod_storeContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_store.
    def exitTraversalMethod_store(self, ctx: GremlinParser.TraversalMethod_storeContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_subgraph.
    def enterTraversalMethod_subgraph(self, ctx: GremlinParser.TraversalMethod_subgraphContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_subgraph.
    def exitTraversalMethod_subgraph(self, ctx: GremlinParser.TraversalMethod_subgraphContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_substring_int.
    def enterTraversalMethod_substring_int(self, ctx: GremlinParser.TraversalMethod_substring_intContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_substring_int.
    def exitTraversalMethod_substring_int(self, ctx: GremlinParser.TraversalMethod_substring_intContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_substring_Scope_int.
    def enterTraversalMethod_substring_Scope_int(self, ctx: GremlinParser.TraversalMethod_substring_Scope_intContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_substring_Scope_int.
    def exitTraversalMethod_substring_Scope_int(self, ctx: GremlinParser.TraversalMethod_substring_Scope_intContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_substring_int_int.
    def enterTraversalMethod_substring_int_int(self, ctx: GremlinParser.TraversalMethod_substring_int_intContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_substring_int_int.
    def exitTraversalMethod_substring_int_int(self, ctx: GremlinParser.TraversalMethod_substring_int_intContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_substring_Scope_int_int.
    def enterTraversalMethod_substring_Scope_int_int(
        self, ctx: GremlinParser.TraversalMethod_substring_Scope_int_intContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_substring_Scope_int_int.
    def exitTraversalMethod_substring_Scope_int_int(
        self, ctx: GremlinParser.TraversalMethod_substring_Scope_int_intContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_sum_Empty.
    def enterTraversalMethod_sum_Empty(self, ctx: GremlinParser.TraversalMethod_sum_EmptyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_sum_Empty.
    def exitTraversalMethod_sum_Empty(self, ctx: GremlinParser.TraversalMethod_sum_EmptyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_sum_Scope.
    def enterTraversalMethod_sum_Scope(self, ctx: GremlinParser.TraversalMethod_sum_ScopeContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_sum_Scope.
    def exitTraversalMethod_sum_Scope(self, ctx: GremlinParser.TraversalMethod_sum_ScopeContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_tail_Empty.
    def enterTraversalMethod_tail_Empty(self, ctx: GremlinParser.TraversalMethod_tail_EmptyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_tail_Empty.
    def exitTraversalMethod_tail_Empty(self, ctx: GremlinParser.TraversalMethod_tail_EmptyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_tail_Scope.
    def enterTraversalMethod_tail_Scope(self, ctx: GremlinParser.TraversalMethod_tail_ScopeContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_tail_Scope.
    def exitTraversalMethod_tail_Scope(self, ctx: GremlinParser.TraversalMethod_tail_ScopeContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_tail_Scope_long.
    def enterTraversalMethod_tail_Scope_long(self, ctx: GremlinParser.TraversalMethod_tail_Scope_longContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_tail_Scope_long.
    def exitTraversalMethod_tail_Scope_long(self, ctx: GremlinParser.TraversalMethod_tail_Scope_longContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_tail_long.
    def enterTraversalMethod_tail_long(self, ctx: GremlinParser.TraversalMethod_tail_longContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_tail_long.
    def exitTraversalMethod_tail_long(self, ctx: GremlinParser.TraversalMethod_tail_longContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_timeLimit.
    def enterTraversalMethod_timeLimit(self, ctx: GremlinParser.TraversalMethod_timeLimitContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_timeLimit.
    def exitTraversalMethod_timeLimit(self, ctx: GremlinParser.TraversalMethod_timeLimitContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_times.
    def enterTraversalMethod_times(self, ctx: GremlinParser.TraversalMethod_timesContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_times.
    def exitTraversalMethod_times(self, ctx: GremlinParser.TraversalMethod_timesContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_to_Direction_String.
    def enterTraversalMethod_to_Direction_String(self, ctx: GremlinParser.TraversalMethod_to_Direction_StringContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_to_Direction_String.
    def exitTraversalMethod_to_Direction_String(self, ctx: GremlinParser.TraversalMethod_to_Direction_StringContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_to_String.
    def enterTraversalMethod_to_String(self, ctx: GremlinParser.TraversalMethod_to_StringContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_to_String.
    def exitTraversalMethod_to_String(self, ctx: GremlinParser.TraversalMethod_to_StringContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_to_Vertex.
    def enterTraversalMethod_to_Vertex(self, ctx: GremlinParser.TraversalMethod_to_VertexContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_to_Vertex.
    def exitTraversalMethod_to_Vertex(self, ctx: GremlinParser.TraversalMethod_to_VertexContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_to_Traversal.
    def enterTraversalMethod_to_Traversal(self, ctx: GremlinParser.TraversalMethod_to_TraversalContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_to_Traversal.
    def exitTraversalMethod_to_Traversal(self, ctx: GremlinParser.TraversalMethod_to_TraversalContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_toE.
    def enterTraversalMethod_toE(self, ctx: GremlinParser.TraversalMethod_toEContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_toE.
    def exitTraversalMethod_toE(self, ctx: GremlinParser.TraversalMethod_toEContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_toLower_Empty.
    def enterTraversalMethod_toLower_Empty(self, ctx: GremlinParser.TraversalMethod_toLower_EmptyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_toLower_Empty.
    def exitTraversalMethod_toLower_Empty(self, ctx: GremlinParser.TraversalMethod_toLower_EmptyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_toLower_Scope.
    def enterTraversalMethod_toLower_Scope(self, ctx: GremlinParser.TraversalMethod_toLower_ScopeContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_toLower_Scope.
    def exitTraversalMethod_toLower_Scope(self, ctx: GremlinParser.TraversalMethod_toLower_ScopeContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_toUpper_Empty.
    def enterTraversalMethod_toUpper_Empty(self, ctx: GremlinParser.TraversalMethod_toUpper_EmptyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_toUpper_Empty.
    def exitTraversalMethod_toUpper_Empty(self, ctx: GremlinParser.TraversalMethod_toUpper_EmptyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_toUpper_Scope.
    def enterTraversalMethod_toUpper_Scope(self, ctx: GremlinParser.TraversalMethod_toUpper_ScopeContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_toUpper_Scope.
    def exitTraversalMethod_toUpper_Scope(self, ctx: GremlinParser.TraversalMethod_toUpper_ScopeContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_toV.
    def enterTraversalMethod_toV(self, ctx: GremlinParser.TraversalMethod_toVContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_toV.
    def exitTraversalMethod_toV(self, ctx: GremlinParser.TraversalMethod_toVContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_tree_Empty.
    def enterTraversalMethod_tree_Empty(self, ctx: GremlinParser.TraversalMethod_tree_EmptyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_tree_Empty.
    def exitTraversalMethod_tree_Empty(self, ctx: GremlinParser.TraversalMethod_tree_EmptyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_tree_String.
    def enterTraversalMethod_tree_String(self, ctx: GremlinParser.TraversalMethod_tree_StringContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_tree_String.
    def exitTraversalMethod_tree_String(self, ctx: GremlinParser.TraversalMethod_tree_StringContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_trim_Empty.
    def enterTraversalMethod_trim_Empty(self, ctx: GremlinParser.TraversalMethod_trim_EmptyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_trim_Empty.
    def exitTraversalMethod_trim_Empty(self, ctx: GremlinParser.TraversalMethod_trim_EmptyContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_trim_Scope.
    def enterTraversalMethod_trim_Scope(self, ctx: GremlinParser.TraversalMethod_trim_ScopeContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_trim_Scope.
    def exitTraversalMethod_trim_Scope(self, ctx: GremlinParser.TraversalMethod_trim_ScopeContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_unfold.
    def enterTraversalMethod_unfold(self, ctx: GremlinParser.TraversalMethod_unfoldContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_unfold.
    def exitTraversalMethod_unfold(self, ctx: GremlinParser.TraversalMethod_unfoldContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_union.
    def enterTraversalMethod_union(self, ctx: GremlinParser.TraversalMethod_unionContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_union.
    def exitTraversalMethod_union(self, ctx: GremlinParser.TraversalMethod_unionContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_until_Predicate.
    def enterTraversalMethod_until_Predicate(self, ctx: GremlinParser.TraversalMethod_until_PredicateContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_until_Predicate.
    def exitTraversalMethod_until_Predicate(self, ctx: GremlinParser.TraversalMethod_until_PredicateContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_until_Traversal.
    def enterTraversalMethod_until_Traversal(self, ctx: GremlinParser.TraversalMethod_until_TraversalContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_until_Traversal.
    def exitTraversalMethod_until_Traversal(self, ctx: GremlinParser.TraversalMethod_until_TraversalContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_value.
    def enterTraversalMethod_value(self, ctx: GremlinParser.TraversalMethod_valueContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_value.
    def exitTraversalMethod_value(self, ctx: GremlinParser.TraversalMethod_valueContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_valueMap_String.
    def enterTraversalMethod_valueMap_String(self, ctx: GremlinParser.TraversalMethod_valueMap_StringContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_valueMap_String.
    def exitTraversalMethod_valueMap_String(self, ctx: GremlinParser.TraversalMethod_valueMap_StringContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_valueMap_boolean_String.
    def enterTraversalMethod_valueMap_boolean_String(
        self, ctx: GremlinParser.TraversalMethod_valueMap_boolean_StringContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_valueMap_boolean_String.
    def exitTraversalMethod_valueMap_boolean_String(
        self, ctx: GremlinParser.TraversalMethod_valueMap_boolean_StringContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_values.
    def enterTraversalMethod_values(self, ctx: GremlinParser.TraversalMethod_valuesContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_values.
    def exitTraversalMethod_values(self, ctx: GremlinParser.TraversalMethod_valuesContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_where_P.
    def enterTraversalMethod_where_P(self, ctx: GremlinParser.TraversalMethod_where_PContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_where_P.
    def exitTraversalMethod_where_P(self, ctx: GremlinParser.TraversalMethod_where_PContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_where_String_P.
    def enterTraversalMethod_where_String_P(self, ctx: GremlinParser.TraversalMethod_where_String_PContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_where_String_P.
    def exitTraversalMethod_where_String_P(self, ctx: GremlinParser.TraversalMethod_where_String_PContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_where_Traversal.
    def enterTraversalMethod_where_Traversal(self, ctx: GremlinParser.TraversalMethod_where_TraversalContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_where_Traversal.
    def exitTraversalMethod_where_Traversal(self, ctx: GremlinParser.TraversalMethod_where_TraversalContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_with_String.
    def enterTraversalMethod_with_String(self, ctx: GremlinParser.TraversalMethod_with_StringContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_with_String.
    def exitTraversalMethod_with_String(self, ctx: GremlinParser.TraversalMethod_with_StringContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_with_String_Object.
    def enterTraversalMethod_with_String_Object(self, ctx: GremlinParser.TraversalMethod_with_String_ObjectContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_with_String_Object.
    def exitTraversalMethod_with_String_Object(self, ctx: GremlinParser.TraversalMethod_with_String_ObjectContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMethod_write.
    def enterTraversalMethod_write(self, ctx: GremlinParser.TraversalMethod_writeContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMethod_write.
    def exitTraversalMethod_write(self, ctx: GremlinParser.TraversalMethod_writeContext):
        pass

    # Enter a parse tree produced by GremlinParser#structureVertexLiteral.
    def enterStructureVertexLiteral(self, ctx: GremlinParser.StructureVertexLiteralContext):
        pass

    # Exit a parse tree produced by GremlinParser#structureVertexLiteral.
    def exitStructureVertexLiteral(self, ctx: GremlinParser.StructureVertexLiteralContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalStrategy.
    def enterTraversalStrategy(self, ctx: GremlinParser.TraversalStrategyContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalStrategy.
    def exitTraversalStrategy(self, ctx: GremlinParser.TraversalStrategyContext):
        pass

    # Enter a parse tree produced by GremlinParser#configuration.
    def enterConfiguration(self, ctx: GremlinParser.ConfigurationContext):
        pass

    # Exit a parse tree produced by GremlinParser#configuration.
    def exitConfiguration(self, ctx: GremlinParser.ConfigurationContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalScope.
    def enterTraversalScope(self, ctx: GremlinParser.TraversalScopeContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalScope.
    def exitTraversalScope(self, ctx: GremlinParser.TraversalScopeContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalBarrier.
    def enterTraversalBarrier(self, ctx: GremlinParser.TraversalBarrierContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalBarrier.
    def exitTraversalBarrier(self, ctx: GremlinParser.TraversalBarrierContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalT.
    def enterTraversalT(self, ctx: GremlinParser.TraversalTContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalT.
    def exitTraversalT(self, ctx: GremlinParser.TraversalTContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalTShort.
    def enterTraversalTShort(self, ctx: GremlinParser.TraversalTShortContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalTShort.
    def exitTraversalTShort(self, ctx: GremlinParser.TraversalTShortContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalTLong.
    def enterTraversalTLong(self, ctx: GremlinParser.TraversalTLongContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalTLong.
    def exitTraversalTLong(self, ctx: GremlinParser.TraversalTLongContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalMerge.
    def enterTraversalMerge(self, ctx: GremlinParser.TraversalMergeContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalMerge.
    def exitTraversalMerge(self, ctx: GremlinParser.TraversalMergeContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalOrder.
    def enterTraversalOrder(self, ctx: GremlinParser.TraversalOrderContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalOrder.
    def exitTraversalOrder(self, ctx: GremlinParser.TraversalOrderContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalDirection.
    def enterTraversalDirection(self, ctx: GremlinParser.TraversalDirectionContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalDirection.
    def exitTraversalDirection(self, ctx: GremlinParser.TraversalDirectionContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalDirectionShort.
    def enterTraversalDirectionShort(self, ctx: GremlinParser.TraversalDirectionShortContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalDirectionShort.
    def exitTraversalDirectionShort(self, ctx: GremlinParser.TraversalDirectionShortContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalDirectionLong.
    def enterTraversalDirectionLong(self, ctx: GremlinParser.TraversalDirectionLongContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalDirectionLong.
    def exitTraversalDirectionLong(self, ctx: GremlinParser.TraversalDirectionLongContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalCardinality.
    def enterTraversalCardinality(self, ctx: GremlinParser.TraversalCardinalityContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalCardinality.
    def exitTraversalCardinality(self, ctx: GremlinParser.TraversalCardinalityContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalColumn.
    def enterTraversalColumn(self, ctx: GremlinParser.TraversalColumnContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalColumn.
    def exitTraversalColumn(self, ctx: GremlinParser.TraversalColumnContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalPop.
    def enterTraversalPop(self, ctx: GremlinParser.TraversalPopContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalPop.
    def exitTraversalPop(self, ctx: GremlinParser.TraversalPopContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalOperator.
    def enterTraversalOperator(self, ctx: GremlinParser.TraversalOperatorContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalOperator.
    def exitTraversalOperator(self, ctx: GremlinParser.TraversalOperatorContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalPick.
    def enterTraversalPick(self, ctx: GremlinParser.TraversalPickContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalPick.
    def exitTraversalPick(self, ctx: GremlinParser.TraversalPickContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalDT.
    def enterTraversalDT(self, ctx: GremlinParser.TraversalDTContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalDT.
    def exitTraversalDT(self, ctx: GremlinParser.TraversalDTContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalPredicate.
    def enterTraversalPredicate(self, ctx: GremlinParser.TraversalPredicateContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalPredicate.
    def exitTraversalPredicate(self, ctx: GremlinParser.TraversalPredicateContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalTerminalMethod.
    def enterTraversalTerminalMethod(self, ctx: GremlinParser.TraversalTerminalMethodContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalTerminalMethod.
    def exitTraversalTerminalMethod(self, ctx: GremlinParser.TraversalTerminalMethodContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalSackMethod.
    def enterTraversalSackMethod(self, ctx: GremlinParser.TraversalSackMethodContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalSackMethod.
    def exitTraversalSackMethod(self, ctx: GremlinParser.TraversalSackMethodContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalComparator.
    def enterTraversalComparator(self, ctx: GremlinParser.TraversalComparatorContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalComparator.
    def exitTraversalComparator(self, ctx: GremlinParser.TraversalComparatorContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalFunction.
    def enterTraversalFunction(self, ctx: GremlinParser.TraversalFunctionContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalFunction.
    def exitTraversalFunction(self, ctx: GremlinParser.TraversalFunctionContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalBiFunction.
    def enterTraversalBiFunction(self, ctx: GremlinParser.TraversalBiFunctionContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalBiFunction.
    def exitTraversalBiFunction(self, ctx: GremlinParser.TraversalBiFunctionContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalPredicate_eq.
    def enterTraversalPredicate_eq(self, ctx: GremlinParser.TraversalPredicate_eqContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalPredicate_eq.
    def exitTraversalPredicate_eq(self, ctx: GremlinParser.TraversalPredicate_eqContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalPredicate_neq.
    def enterTraversalPredicate_neq(self, ctx: GremlinParser.TraversalPredicate_neqContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalPredicate_neq.
    def exitTraversalPredicate_neq(self, ctx: GremlinParser.TraversalPredicate_neqContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalPredicate_lt.
    def enterTraversalPredicate_lt(self, ctx: GremlinParser.TraversalPredicate_ltContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalPredicate_lt.
    def exitTraversalPredicate_lt(self, ctx: GremlinParser.TraversalPredicate_ltContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalPredicate_lte.
    def enterTraversalPredicate_lte(self, ctx: GremlinParser.TraversalPredicate_lteContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalPredicate_lte.
    def exitTraversalPredicate_lte(self, ctx: GremlinParser.TraversalPredicate_lteContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalPredicate_gt.
    def enterTraversalPredicate_gt(self, ctx: GremlinParser.TraversalPredicate_gtContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalPredicate_gt.
    def exitTraversalPredicate_gt(self, ctx: GremlinParser.TraversalPredicate_gtContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalPredicate_gte.
    def enterTraversalPredicate_gte(self, ctx: GremlinParser.TraversalPredicate_gteContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalPredicate_gte.
    def exitTraversalPredicate_gte(self, ctx: GremlinParser.TraversalPredicate_gteContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalPredicate_inside.
    def enterTraversalPredicate_inside(self, ctx: GremlinParser.TraversalPredicate_insideContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalPredicate_inside.
    def exitTraversalPredicate_inside(self, ctx: GremlinParser.TraversalPredicate_insideContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalPredicate_outside.
    def enterTraversalPredicate_outside(self, ctx: GremlinParser.TraversalPredicate_outsideContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalPredicate_outside.
    def exitTraversalPredicate_outside(self, ctx: GremlinParser.TraversalPredicate_outsideContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalPredicate_between.
    def enterTraversalPredicate_between(self, ctx: GremlinParser.TraversalPredicate_betweenContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalPredicate_between.
    def exitTraversalPredicate_between(self, ctx: GremlinParser.TraversalPredicate_betweenContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalPredicate_within.
    def enterTraversalPredicate_within(self, ctx: GremlinParser.TraversalPredicate_withinContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalPredicate_within.
    def exitTraversalPredicate_within(self, ctx: GremlinParser.TraversalPredicate_withinContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalPredicate_without.
    def enterTraversalPredicate_without(self, ctx: GremlinParser.TraversalPredicate_withoutContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalPredicate_without.
    def exitTraversalPredicate_without(self, ctx: GremlinParser.TraversalPredicate_withoutContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalPredicate_not.
    def enterTraversalPredicate_not(self, ctx: GremlinParser.TraversalPredicate_notContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalPredicate_not.
    def exitTraversalPredicate_not(self, ctx: GremlinParser.TraversalPredicate_notContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalPredicate_containing.
    def enterTraversalPredicate_containing(self, ctx: GremlinParser.TraversalPredicate_containingContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalPredicate_containing.
    def exitTraversalPredicate_containing(self, ctx: GremlinParser.TraversalPredicate_containingContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalPredicate_notContaining.
    def enterTraversalPredicate_notContaining(self, ctx: GremlinParser.TraversalPredicate_notContainingContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalPredicate_notContaining.
    def exitTraversalPredicate_notContaining(self, ctx: GremlinParser.TraversalPredicate_notContainingContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalPredicate_startingWith.
    def enterTraversalPredicate_startingWith(self, ctx: GremlinParser.TraversalPredicate_startingWithContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalPredicate_startingWith.
    def exitTraversalPredicate_startingWith(self, ctx: GremlinParser.TraversalPredicate_startingWithContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalPredicate_notStartingWith.
    def enterTraversalPredicate_notStartingWith(self, ctx: GremlinParser.TraversalPredicate_notStartingWithContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalPredicate_notStartingWith.
    def exitTraversalPredicate_notStartingWith(self, ctx: GremlinParser.TraversalPredicate_notStartingWithContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalPredicate_endingWith.
    def enterTraversalPredicate_endingWith(self, ctx: GremlinParser.TraversalPredicate_endingWithContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalPredicate_endingWith.
    def exitTraversalPredicate_endingWith(self, ctx: GremlinParser.TraversalPredicate_endingWithContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalPredicate_notEndingWith.
    def enterTraversalPredicate_notEndingWith(self, ctx: GremlinParser.TraversalPredicate_notEndingWithContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalPredicate_notEndingWith.
    def exitTraversalPredicate_notEndingWith(self, ctx: GremlinParser.TraversalPredicate_notEndingWithContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalPredicate_regex.
    def enterTraversalPredicate_regex(self, ctx: GremlinParser.TraversalPredicate_regexContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalPredicate_regex.
    def exitTraversalPredicate_regex(self, ctx: GremlinParser.TraversalPredicate_regexContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalPredicate_notRegex.
    def enterTraversalPredicate_notRegex(self, ctx: GremlinParser.TraversalPredicate_notRegexContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalPredicate_notRegex.
    def exitTraversalPredicate_notRegex(self, ctx: GremlinParser.TraversalPredicate_notRegexContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalTerminalMethod_explain.
    def enterTraversalTerminalMethod_explain(self, ctx: GremlinParser.TraversalTerminalMethod_explainContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalTerminalMethod_explain.
    def exitTraversalTerminalMethod_explain(self, ctx: GremlinParser.TraversalTerminalMethod_explainContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalTerminalMethod_hasNext.
    def enterTraversalTerminalMethod_hasNext(self, ctx: GremlinParser.TraversalTerminalMethod_hasNextContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalTerminalMethod_hasNext.
    def exitTraversalTerminalMethod_hasNext(self, ctx: GremlinParser.TraversalTerminalMethod_hasNextContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalTerminalMethod_iterate.
    def enterTraversalTerminalMethod_iterate(self, ctx: GremlinParser.TraversalTerminalMethod_iterateContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalTerminalMethod_iterate.
    def exitTraversalTerminalMethod_iterate(self, ctx: GremlinParser.TraversalTerminalMethod_iterateContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalTerminalMethod_tryNext.
    def enterTraversalTerminalMethod_tryNext(self, ctx: GremlinParser.TraversalTerminalMethod_tryNextContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalTerminalMethod_tryNext.
    def exitTraversalTerminalMethod_tryNext(self, ctx: GremlinParser.TraversalTerminalMethod_tryNextContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalTerminalMethod_next.
    def enterTraversalTerminalMethod_next(self, ctx: GremlinParser.TraversalTerminalMethod_nextContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalTerminalMethod_next.
    def exitTraversalTerminalMethod_next(self, ctx: GremlinParser.TraversalTerminalMethod_nextContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalTerminalMethod_toList.
    def enterTraversalTerminalMethod_toList(self, ctx: GremlinParser.TraversalTerminalMethod_toListContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalTerminalMethod_toList.
    def exitTraversalTerminalMethod_toList(self, ctx: GremlinParser.TraversalTerminalMethod_toListContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalTerminalMethod_toSet.
    def enterTraversalTerminalMethod_toSet(self, ctx: GremlinParser.TraversalTerminalMethod_toSetContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalTerminalMethod_toSet.
    def exitTraversalTerminalMethod_toSet(self, ctx: GremlinParser.TraversalTerminalMethod_toSetContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalTerminalMethod_toBulkSet.
    def enterTraversalTerminalMethod_toBulkSet(self, ctx: GremlinParser.TraversalTerminalMethod_toBulkSetContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalTerminalMethod_toBulkSet.
    def exitTraversalTerminalMethod_toBulkSet(self, ctx: GremlinParser.TraversalTerminalMethod_toBulkSetContext):
        pass

    # Enter a parse tree produced by GremlinParser#withOptionKeys.
    def enterWithOptionKeys(self, ctx: GremlinParser.WithOptionKeysContext):
        pass

    # Exit a parse tree produced by GremlinParser#withOptionKeys.
    def exitWithOptionKeys(self, ctx: GremlinParser.WithOptionKeysContext):
        pass

    # Enter a parse tree produced by GremlinParser#connectedComponentConstants.
    def enterConnectedComponentConstants(self, ctx: GremlinParser.ConnectedComponentConstantsContext):
        pass

    # Exit a parse tree produced by GremlinParser#connectedComponentConstants.
    def exitConnectedComponentConstants(self, ctx: GremlinParser.ConnectedComponentConstantsContext):
        pass

    # Enter a parse tree produced by GremlinParser#pageRankConstants.
    def enterPageRankConstants(self, ctx: GremlinParser.PageRankConstantsContext):
        pass

    # Exit a parse tree produced by GremlinParser#pageRankConstants.
    def exitPageRankConstants(self, ctx: GremlinParser.PageRankConstantsContext):
        pass

    # Enter a parse tree produced by GremlinParser#peerPressureConstants.
    def enterPeerPressureConstants(self, ctx: GremlinParser.PeerPressureConstantsContext):
        pass

    # Exit a parse tree produced by GremlinParser#peerPressureConstants.
    def exitPeerPressureConstants(self, ctx: GremlinParser.PeerPressureConstantsContext):
        pass

    # Enter a parse tree produced by GremlinParser#shortestPathConstants.
    def enterShortestPathConstants(self, ctx: GremlinParser.ShortestPathConstantsContext):
        pass

    # Exit a parse tree produced by GremlinParser#shortestPathConstants.
    def exitShortestPathConstants(self, ctx: GremlinParser.ShortestPathConstantsContext):
        pass

    # Enter a parse tree produced by GremlinParser#withOptionsValues.
    def enterWithOptionsValues(self, ctx: GremlinParser.WithOptionsValuesContext):
        pass

    # Exit a parse tree produced by GremlinParser#withOptionsValues.
    def exitWithOptionsValues(self, ctx: GremlinParser.WithOptionsValuesContext):
        pass

    # Enter a parse tree produced by GremlinParser#ioOptionsKeys.
    def enterIoOptionsKeys(self, ctx: GremlinParser.IoOptionsKeysContext):
        pass

    # Exit a parse tree produced by GremlinParser#ioOptionsKeys.
    def exitIoOptionsKeys(self, ctx: GremlinParser.IoOptionsKeysContext):
        pass

    # Enter a parse tree produced by GremlinParser#ioOptionsValues.
    def enterIoOptionsValues(self, ctx: GremlinParser.IoOptionsValuesContext):
        pass

    # Exit a parse tree produced by GremlinParser#ioOptionsValues.
    def exitIoOptionsValues(self, ctx: GremlinParser.IoOptionsValuesContext):
        pass

    # Enter a parse tree produced by GremlinParser#connectedComponentConstants_component.
    def enterConnectedComponentConstants_component(
        self, ctx: GremlinParser.ConnectedComponentConstants_componentContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#connectedComponentConstants_component.
    def exitConnectedComponentConstants_component(
        self, ctx: GremlinParser.ConnectedComponentConstants_componentContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#connectedComponentConstants_edges.
    def enterConnectedComponentConstants_edges(self, ctx: GremlinParser.ConnectedComponentConstants_edgesContext):
        pass

    # Exit a parse tree produced by GremlinParser#connectedComponentConstants_edges.
    def exitConnectedComponentConstants_edges(self, ctx: GremlinParser.ConnectedComponentConstants_edgesContext):
        pass

    # Enter a parse tree produced by GremlinParser#connectedComponentConstants_propertyName.
    def enterConnectedComponentConstants_propertyName(
        self, ctx: GremlinParser.ConnectedComponentConstants_propertyNameContext
    ):
        pass

    # Exit a parse tree produced by GremlinParser#connectedComponentConstants_propertyName.
    def exitConnectedComponentConstants_propertyName(
        self, ctx: GremlinParser.ConnectedComponentConstants_propertyNameContext
    ):
        pass

    # Enter a parse tree produced by GremlinParser#pageRankConstants_edges.
    def enterPageRankConstants_edges(self, ctx: GremlinParser.PageRankConstants_edgesContext):
        pass

    # Exit a parse tree produced by GremlinParser#pageRankConstants_edges.
    def exitPageRankConstants_edges(self, ctx: GremlinParser.PageRankConstants_edgesContext):
        pass

    # Enter a parse tree produced by GremlinParser#pageRankConstants_times.
    def enterPageRankConstants_times(self, ctx: GremlinParser.PageRankConstants_timesContext):
        pass

    # Exit a parse tree produced by GremlinParser#pageRankConstants_times.
    def exitPageRankConstants_times(self, ctx: GremlinParser.PageRankConstants_timesContext):
        pass

    # Enter a parse tree produced by GremlinParser#pageRankConstants_propertyName.
    def enterPageRankConstants_propertyName(self, ctx: GremlinParser.PageRankConstants_propertyNameContext):
        pass

    # Exit a parse tree produced by GremlinParser#pageRankConstants_propertyName.
    def exitPageRankConstants_propertyName(self, ctx: GremlinParser.PageRankConstants_propertyNameContext):
        pass

    # Enter a parse tree produced by GremlinParser#peerPressureConstants_edges.
    def enterPeerPressureConstants_edges(self, ctx: GremlinParser.PeerPressureConstants_edgesContext):
        pass

    # Exit a parse tree produced by GremlinParser#peerPressureConstants_edges.
    def exitPeerPressureConstants_edges(self, ctx: GremlinParser.PeerPressureConstants_edgesContext):
        pass

    # Enter a parse tree produced by GremlinParser#peerPressureConstants_times.
    def enterPeerPressureConstants_times(self, ctx: GremlinParser.PeerPressureConstants_timesContext):
        pass

    # Exit a parse tree produced by GremlinParser#peerPressureConstants_times.
    def exitPeerPressureConstants_times(self, ctx: GremlinParser.PeerPressureConstants_timesContext):
        pass

    # Enter a parse tree produced by GremlinParser#peerPressureConstants_propertyName.
    def enterPeerPressureConstants_propertyName(self, ctx: GremlinParser.PeerPressureConstants_propertyNameContext):
        pass

    # Exit a parse tree produced by GremlinParser#peerPressureConstants_propertyName.
    def exitPeerPressureConstants_propertyName(self, ctx: GremlinParser.PeerPressureConstants_propertyNameContext):
        pass

    # Enter a parse tree produced by GremlinParser#shortestPathConstants_target.
    def enterShortestPathConstants_target(self, ctx: GremlinParser.ShortestPathConstants_targetContext):
        pass

    # Exit a parse tree produced by GremlinParser#shortestPathConstants_target.
    def exitShortestPathConstants_target(self, ctx: GremlinParser.ShortestPathConstants_targetContext):
        pass

    # Enter a parse tree produced by GremlinParser#shortestPathConstants_edges.
    def enterShortestPathConstants_edges(self, ctx: GremlinParser.ShortestPathConstants_edgesContext):
        pass

    # Exit a parse tree produced by GremlinParser#shortestPathConstants_edges.
    def exitShortestPathConstants_edges(self, ctx: GremlinParser.ShortestPathConstants_edgesContext):
        pass

    # Enter a parse tree produced by GremlinParser#shortestPathConstants_distance.
    def enterShortestPathConstants_distance(self, ctx: GremlinParser.ShortestPathConstants_distanceContext):
        pass

    # Exit a parse tree produced by GremlinParser#shortestPathConstants_distance.
    def exitShortestPathConstants_distance(self, ctx: GremlinParser.ShortestPathConstants_distanceContext):
        pass

    # Enter a parse tree produced by GremlinParser#shortestPathConstants_maxDistance.
    def enterShortestPathConstants_maxDistance(self, ctx: GremlinParser.ShortestPathConstants_maxDistanceContext):
        pass

    # Exit a parse tree produced by GremlinParser#shortestPathConstants_maxDistance.
    def exitShortestPathConstants_maxDistance(self, ctx: GremlinParser.ShortestPathConstants_maxDistanceContext):
        pass

    # Enter a parse tree produced by GremlinParser#shortestPathConstants_includeEdges.
    def enterShortestPathConstants_includeEdges(self, ctx: GremlinParser.ShortestPathConstants_includeEdgesContext):
        pass

    # Exit a parse tree produced by GremlinParser#shortestPathConstants_includeEdges.
    def exitShortestPathConstants_includeEdges(self, ctx: GremlinParser.ShortestPathConstants_includeEdgesContext):
        pass

    # Enter a parse tree produced by GremlinParser#withOptionsConstants_tokens.
    def enterWithOptionsConstants_tokens(self, ctx: GremlinParser.WithOptionsConstants_tokensContext):
        pass

    # Exit a parse tree produced by GremlinParser#withOptionsConstants_tokens.
    def exitWithOptionsConstants_tokens(self, ctx: GremlinParser.WithOptionsConstants_tokensContext):
        pass

    # Enter a parse tree produced by GremlinParser#withOptionsConstants_none.
    def enterWithOptionsConstants_none(self, ctx: GremlinParser.WithOptionsConstants_noneContext):
        pass

    # Exit a parse tree produced by GremlinParser#withOptionsConstants_none.
    def exitWithOptionsConstants_none(self, ctx: GremlinParser.WithOptionsConstants_noneContext):
        pass

    # Enter a parse tree produced by GremlinParser#withOptionsConstants_ids.
    def enterWithOptionsConstants_ids(self, ctx: GremlinParser.WithOptionsConstants_idsContext):
        pass

    # Exit a parse tree produced by GremlinParser#withOptionsConstants_ids.
    def exitWithOptionsConstants_ids(self, ctx: GremlinParser.WithOptionsConstants_idsContext):
        pass

    # Enter a parse tree produced by GremlinParser#withOptionsConstants_labels.
    def enterWithOptionsConstants_labels(self, ctx: GremlinParser.WithOptionsConstants_labelsContext):
        pass

    # Exit a parse tree produced by GremlinParser#withOptionsConstants_labels.
    def exitWithOptionsConstants_labels(self, ctx: GremlinParser.WithOptionsConstants_labelsContext):
        pass

    # Enter a parse tree produced by GremlinParser#withOptionsConstants_keys.
    def enterWithOptionsConstants_keys(self, ctx: GremlinParser.WithOptionsConstants_keysContext):
        pass

    # Exit a parse tree produced by GremlinParser#withOptionsConstants_keys.
    def exitWithOptionsConstants_keys(self, ctx: GremlinParser.WithOptionsConstants_keysContext):
        pass

    # Enter a parse tree produced by GremlinParser#withOptionsConstants_values.
    def enterWithOptionsConstants_values(self, ctx: GremlinParser.WithOptionsConstants_valuesContext):
        pass

    # Exit a parse tree produced by GremlinParser#withOptionsConstants_values.
    def exitWithOptionsConstants_values(self, ctx: GremlinParser.WithOptionsConstants_valuesContext):
        pass

    # Enter a parse tree produced by GremlinParser#withOptionsConstants_all.
    def enterWithOptionsConstants_all(self, ctx: GremlinParser.WithOptionsConstants_allContext):
        pass

    # Exit a parse tree produced by GremlinParser#withOptionsConstants_all.
    def exitWithOptionsConstants_all(self, ctx: GremlinParser.WithOptionsConstants_allContext):
        pass

    # Enter a parse tree produced by GremlinParser#withOptionsConstants_indexer.
    def enterWithOptionsConstants_indexer(self, ctx: GremlinParser.WithOptionsConstants_indexerContext):
        pass

    # Exit a parse tree produced by GremlinParser#withOptionsConstants_indexer.
    def exitWithOptionsConstants_indexer(self, ctx: GremlinParser.WithOptionsConstants_indexerContext):
        pass

    # Enter a parse tree produced by GremlinParser#withOptionsConstants_list.
    def enterWithOptionsConstants_list(self, ctx: GremlinParser.WithOptionsConstants_listContext):
        pass

    # Exit a parse tree produced by GremlinParser#withOptionsConstants_list.
    def exitWithOptionsConstants_list(self, ctx: GremlinParser.WithOptionsConstants_listContext):
        pass

    # Enter a parse tree produced by GremlinParser#withOptionsConstants_map.
    def enterWithOptionsConstants_map(self, ctx: GremlinParser.WithOptionsConstants_mapContext):
        pass

    # Exit a parse tree produced by GremlinParser#withOptionsConstants_map.
    def exitWithOptionsConstants_map(self, ctx: GremlinParser.WithOptionsConstants_mapContext):
        pass

    # Enter a parse tree produced by GremlinParser#ioOptionsConstants_reader.
    def enterIoOptionsConstants_reader(self, ctx: GremlinParser.IoOptionsConstants_readerContext):
        pass

    # Exit a parse tree produced by GremlinParser#ioOptionsConstants_reader.
    def exitIoOptionsConstants_reader(self, ctx: GremlinParser.IoOptionsConstants_readerContext):
        pass

    # Enter a parse tree produced by GremlinParser#ioOptionsConstants_writer.
    def enterIoOptionsConstants_writer(self, ctx: GremlinParser.IoOptionsConstants_writerContext):
        pass

    # Exit a parse tree produced by GremlinParser#ioOptionsConstants_writer.
    def exitIoOptionsConstants_writer(self, ctx: GremlinParser.IoOptionsConstants_writerContext):
        pass

    # Enter a parse tree produced by GremlinParser#ioOptionsConstants_gryo.
    def enterIoOptionsConstants_gryo(self, ctx: GremlinParser.IoOptionsConstants_gryoContext):
        pass

    # Exit a parse tree produced by GremlinParser#ioOptionsConstants_gryo.
    def exitIoOptionsConstants_gryo(self, ctx: GremlinParser.IoOptionsConstants_gryoContext):
        pass

    # Enter a parse tree produced by GremlinParser#ioOptionsConstants_graphson.
    def enterIoOptionsConstants_graphson(self, ctx: GremlinParser.IoOptionsConstants_graphsonContext):
        pass

    # Exit a parse tree produced by GremlinParser#ioOptionsConstants_graphson.
    def exitIoOptionsConstants_graphson(self, ctx: GremlinParser.IoOptionsConstants_graphsonContext):
        pass

    # Enter a parse tree produced by GremlinParser#ioOptionsConstants_graphml.
    def enterIoOptionsConstants_graphml(self, ctx: GremlinParser.IoOptionsConstants_graphmlContext):
        pass

    # Exit a parse tree produced by GremlinParser#ioOptionsConstants_graphml.
    def exitIoOptionsConstants_graphml(self, ctx: GremlinParser.IoOptionsConstants_graphmlContext):
        pass

    # Enter a parse tree produced by GremlinParser#connectedComponentStringConstant.
    def enterConnectedComponentStringConstant(self, ctx: GremlinParser.ConnectedComponentStringConstantContext):
        pass

    # Exit a parse tree produced by GremlinParser#connectedComponentStringConstant.
    def exitConnectedComponentStringConstant(self, ctx: GremlinParser.ConnectedComponentStringConstantContext):
        pass

    # Enter a parse tree produced by GremlinParser#pageRankStringConstant.
    def enterPageRankStringConstant(self, ctx: GremlinParser.PageRankStringConstantContext):
        pass

    # Exit a parse tree produced by GremlinParser#pageRankStringConstant.
    def exitPageRankStringConstant(self, ctx: GremlinParser.PageRankStringConstantContext):
        pass

    # Enter a parse tree produced by GremlinParser#peerPressureStringConstant.
    def enterPeerPressureStringConstant(self, ctx: GremlinParser.PeerPressureStringConstantContext):
        pass

    # Exit a parse tree produced by GremlinParser#peerPressureStringConstant.
    def exitPeerPressureStringConstant(self, ctx: GremlinParser.PeerPressureStringConstantContext):
        pass

    # Enter a parse tree produced by GremlinParser#shortestPathStringConstant.
    def enterShortestPathStringConstant(self, ctx: GremlinParser.ShortestPathStringConstantContext):
        pass

    # Exit a parse tree produced by GremlinParser#shortestPathStringConstant.
    def exitShortestPathStringConstant(self, ctx: GremlinParser.ShortestPathStringConstantContext):
        pass

    # Enter a parse tree produced by GremlinParser#withOptionsStringConstant.
    def enterWithOptionsStringConstant(self, ctx: GremlinParser.WithOptionsStringConstantContext):
        pass

    # Exit a parse tree produced by GremlinParser#withOptionsStringConstant.
    def exitWithOptionsStringConstant(self, ctx: GremlinParser.WithOptionsStringConstantContext):
        pass

    # Enter a parse tree produced by GremlinParser#ioOptionsStringConstant.
    def enterIoOptionsStringConstant(self, ctx: GremlinParser.IoOptionsStringConstantContext):
        pass

    # Exit a parse tree produced by GremlinParser#ioOptionsStringConstant.
    def exitIoOptionsStringConstant(self, ctx: GremlinParser.IoOptionsStringConstantContext):
        pass

    # Enter a parse tree produced by GremlinParser#booleanArgument.
    def enterBooleanArgument(self, ctx: GremlinParser.BooleanArgumentContext):
        pass

    # Exit a parse tree produced by GremlinParser#booleanArgument.
    def exitBooleanArgument(self, ctx: GremlinParser.BooleanArgumentContext):
        pass

    # Enter a parse tree produced by GremlinParser#integerArgument.
    def enterIntegerArgument(self, ctx: GremlinParser.IntegerArgumentContext):
        pass

    # Exit a parse tree produced by GremlinParser#integerArgument.
    def exitIntegerArgument(self, ctx: GremlinParser.IntegerArgumentContext):
        pass

    # Enter a parse tree produced by GremlinParser#floatArgument.
    def enterFloatArgument(self, ctx: GremlinParser.FloatArgumentContext):
        pass

    # Exit a parse tree produced by GremlinParser#floatArgument.
    def exitFloatArgument(self, ctx: GremlinParser.FloatArgumentContext):
        pass

    # Enter a parse tree produced by GremlinParser#stringArgument.
    def enterStringArgument(self, ctx: GremlinParser.StringArgumentContext):
        pass

    # Exit a parse tree produced by GremlinParser#stringArgument.
    def exitStringArgument(self, ctx: GremlinParser.StringArgumentContext):
        pass

    # Enter a parse tree produced by GremlinParser#stringNullableArgument.
    def enterStringNullableArgument(self, ctx: GremlinParser.StringNullableArgumentContext):
        pass

    # Exit a parse tree produced by GremlinParser#stringNullableArgument.
    def exitStringNullableArgument(self, ctx: GremlinParser.StringNullableArgumentContext):
        pass

    # Enter a parse tree produced by GremlinParser#stringNullableArgumentVarargs.
    def enterStringNullableArgumentVarargs(self, ctx: GremlinParser.StringNullableArgumentVarargsContext):
        pass

    # Exit a parse tree produced by GremlinParser#stringNullableArgumentVarargs.
    def exitStringNullableArgumentVarargs(self, ctx: GremlinParser.StringNullableArgumentVarargsContext):
        pass

    # Enter a parse tree produced by GremlinParser#dateArgument.
    def enterDateArgument(self, ctx: GremlinParser.DateArgumentContext):
        pass

    # Exit a parse tree produced by GremlinParser#dateArgument.
    def exitDateArgument(self, ctx: GremlinParser.DateArgumentContext):
        pass

    # Enter a parse tree produced by GremlinParser#genericArgument.
    def enterGenericArgument(self, ctx: GremlinParser.GenericArgumentContext):
        pass

    # Exit a parse tree produced by GremlinParser#genericArgument.
    def exitGenericArgument(self, ctx: GremlinParser.GenericArgumentContext):
        pass

    # Enter a parse tree produced by GremlinParser#genericArgumentVarargs.
    def enterGenericArgumentVarargs(self, ctx: GremlinParser.GenericArgumentVarargsContext):
        pass

    # Exit a parse tree produced by GremlinParser#genericArgumentVarargs.
    def exitGenericArgumentVarargs(self, ctx: GremlinParser.GenericArgumentVarargsContext):
        pass

    # Enter a parse tree produced by GremlinParser#genericMapArgument.
    def enterGenericMapArgument(self, ctx: GremlinParser.GenericMapArgumentContext):
        pass

    # Exit a parse tree produced by GremlinParser#genericMapArgument.
    def exitGenericMapArgument(self, ctx: GremlinParser.GenericMapArgumentContext):
        pass

    # Enter a parse tree produced by GremlinParser#genericMapNullableArgument.
    def enterGenericMapNullableArgument(self, ctx: GremlinParser.GenericMapNullableArgumentContext):
        pass

    # Exit a parse tree produced by GremlinParser#genericMapNullableArgument.
    def exitGenericMapNullableArgument(self, ctx: GremlinParser.GenericMapNullableArgumentContext):
        pass

    # Enter a parse tree produced by GremlinParser#nullableGenericLiteralMap.
    def enterNullableGenericLiteralMap(self, ctx: GremlinParser.NullableGenericLiteralMapContext):
        pass

    # Exit a parse tree produced by GremlinParser#nullableGenericLiteralMap.
    def exitNullableGenericLiteralMap(self, ctx: GremlinParser.NullableGenericLiteralMapContext):
        pass

    # Enter a parse tree produced by GremlinParser#structureVertexArgument.
    def enterStructureVertexArgument(self, ctx: GremlinParser.StructureVertexArgumentContext):
        pass

    # Exit a parse tree produced by GremlinParser#structureVertexArgument.
    def exitStructureVertexArgument(self, ctx: GremlinParser.StructureVertexArgumentContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalStrategyVarargs.
    def enterTraversalStrategyVarargs(self, ctx: GremlinParser.TraversalStrategyVarargsContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalStrategyVarargs.
    def exitTraversalStrategyVarargs(self, ctx: GremlinParser.TraversalStrategyVarargsContext):
        pass

    # Enter a parse tree produced by GremlinParser#traversalStrategyExpr.
    def enterTraversalStrategyExpr(self, ctx: GremlinParser.TraversalStrategyExprContext):
        pass

    # Exit a parse tree produced by GremlinParser#traversalStrategyExpr.
    def exitTraversalStrategyExpr(self, ctx: GremlinParser.TraversalStrategyExprContext):
        pass

    # Enter a parse tree produced by GremlinParser#classTypeList.
    def enterClassTypeList(self, ctx: GremlinParser.ClassTypeListContext):
        pass

    # Exit a parse tree produced by GremlinParser#classTypeList.
    def exitClassTypeList(self, ctx: GremlinParser.ClassTypeListContext):
        pass

    # Enter a parse tree produced by GremlinParser#classTypeExpr.
    def enterClassTypeExpr(self, ctx: GremlinParser.ClassTypeExprContext):
        pass

    # Exit a parse tree produced by GremlinParser#classTypeExpr.
    def exitClassTypeExpr(self, ctx: GremlinParser.ClassTypeExprContext):
        pass

    # Enter a parse tree produced by GremlinParser#nestedTraversalList.
    def enterNestedTraversalList(self, ctx: GremlinParser.NestedTraversalListContext):
        pass

    # Exit a parse tree produced by GremlinParser#nestedTraversalList.
    def exitNestedTraversalList(self, ctx: GremlinParser.NestedTraversalListContext):
        pass

    # Enter a parse tree produced by GremlinParser#nestedTraversalExpr.
    def enterNestedTraversalExpr(self, ctx: GremlinParser.NestedTraversalExprContext):
        pass

    # Exit a parse tree produced by GremlinParser#nestedTraversalExpr.
    def exitNestedTraversalExpr(self, ctx: GremlinParser.NestedTraversalExprContext):
        pass

    # Enter a parse tree produced by GremlinParser#genericCollectionLiteral.
    def enterGenericCollectionLiteral(self, ctx: GremlinParser.GenericCollectionLiteralContext):
        pass

    # Exit a parse tree produced by GremlinParser#genericCollectionLiteral.
    def exitGenericCollectionLiteral(self, ctx: GremlinParser.GenericCollectionLiteralContext):
        pass

    # Enter a parse tree produced by GremlinParser#genericLiteralVarargs.
    def enterGenericLiteralVarargs(self, ctx: GremlinParser.GenericLiteralVarargsContext):
        pass

    # Exit a parse tree produced by GremlinParser#genericLiteralVarargs.
    def exitGenericLiteralVarargs(self, ctx: GremlinParser.GenericLiteralVarargsContext):
        pass

    # Enter a parse tree produced by GremlinParser#genericLiteralExpr.
    def enterGenericLiteralExpr(self, ctx: GremlinParser.GenericLiteralExprContext):
        pass

    # Exit a parse tree produced by GremlinParser#genericLiteralExpr.
    def exitGenericLiteralExpr(self, ctx: GremlinParser.GenericLiteralExprContext):
        pass

    # Enter a parse tree produced by GremlinParser#genericMapNullableLiteral.
    def enterGenericMapNullableLiteral(self, ctx: GremlinParser.GenericMapNullableLiteralContext):
        pass

    # Exit a parse tree produced by GremlinParser#genericMapNullableLiteral.
    def exitGenericMapNullableLiteral(self, ctx: GremlinParser.GenericMapNullableLiteralContext):
        pass

    # Enter a parse tree produced by GremlinParser#genericRangeLiteral.
    def enterGenericRangeLiteral(self, ctx: GremlinParser.GenericRangeLiteralContext):
        pass

    # Exit a parse tree produced by GremlinParser#genericRangeLiteral.
    def exitGenericRangeLiteral(self, ctx: GremlinParser.GenericRangeLiteralContext):
        pass

    # Enter a parse tree produced by GremlinParser#genericSetLiteral.
    def enterGenericSetLiteral(self, ctx: GremlinParser.GenericSetLiteralContext):
        pass

    # Exit a parse tree produced by GremlinParser#genericSetLiteral.
    def exitGenericSetLiteral(self, ctx: GremlinParser.GenericSetLiteralContext):
        pass

    # Enter a parse tree produced by GremlinParser#stringNullableLiteralVarargs.
    def enterStringNullableLiteralVarargs(self, ctx: GremlinParser.StringNullableLiteralVarargsContext):
        pass

    # Exit a parse tree produced by GremlinParser#stringNullableLiteralVarargs.
    def exitStringNullableLiteralVarargs(self, ctx: GremlinParser.StringNullableLiteralVarargsContext):
        pass

    # Enter a parse tree produced by GremlinParser#genericLiteral.
    def enterGenericLiteral(self, ctx: GremlinParser.GenericLiteralContext):
        pass

    # Exit a parse tree produced by GremlinParser#genericLiteral.
    def exitGenericLiteral(self, ctx: GremlinParser.GenericLiteralContext):
        pass

    # Enter a parse tree produced by GremlinParser#genericMapLiteral.
    def enterGenericMapLiteral(self, ctx: GremlinParser.GenericMapLiteralContext):
        pass

    # Exit a parse tree produced by GremlinParser#genericMapLiteral.
    def exitGenericMapLiteral(self, ctx: GremlinParser.GenericMapLiteralContext):
        pass

    # Enter a parse tree produced by GremlinParser#mapKey.
    def enterMapKey(self, ctx: GremlinParser.MapKeyContext):
        pass

    # Exit a parse tree produced by GremlinParser#mapKey.
    def exitMapKey(self, ctx: GremlinParser.MapKeyContext):
        pass

    # Enter a parse tree produced by GremlinParser#mapEntry.
    def enterMapEntry(self, ctx: GremlinParser.MapEntryContext):
        pass

    # Exit a parse tree produced by GremlinParser#mapEntry.
    def exitMapEntry(self, ctx: GremlinParser.MapEntryContext):
        pass

    # Enter a parse tree produced by GremlinParser#stringLiteral.
    def enterStringLiteral(self, ctx: GremlinParser.StringLiteralContext):
        pass

    # Exit a parse tree produced by GremlinParser#stringLiteral.
    def exitStringLiteral(self, ctx: GremlinParser.StringLiteralContext):
        pass

    # Enter a parse tree produced by GremlinParser#stringNullableLiteral.
    def enterStringNullableLiteral(self, ctx: GremlinParser.StringNullableLiteralContext):
        pass

    # Exit a parse tree produced by GremlinParser#stringNullableLiteral.
    def exitStringNullableLiteral(self, ctx: GremlinParser.StringNullableLiteralContext):
        pass

    # Enter a parse tree produced by GremlinParser#integerLiteral.
    def enterIntegerLiteral(self, ctx: GremlinParser.IntegerLiteralContext):
        pass

    # Exit a parse tree produced by GremlinParser#integerLiteral.
    def exitIntegerLiteral(self, ctx: GremlinParser.IntegerLiteralContext):
        pass

    # Enter a parse tree produced by GremlinParser#floatLiteral.
    def enterFloatLiteral(self, ctx: GremlinParser.FloatLiteralContext):
        pass

    # Exit a parse tree produced by GremlinParser#floatLiteral.
    def exitFloatLiteral(self, ctx: GremlinParser.FloatLiteralContext):
        pass

    # Enter a parse tree produced by GremlinParser#numericLiteral.
    def enterNumericLiteral(self, ctx: GremlinParser.NumericLiteralContext):
        pass

    # Exit a parse tree produced by GremlinParser#numericLiteral.
    def exitNumericLiteral(self, ctx: GremlinParser.NumericLiteralContext):
        pass

    # Enter a parse tree produced by GremlinParser#booleanLiteral.
    def enterBooleanLiteral(self, ctx: GremlinParser.BooleanLiteralContext):
        pass

    # Exit a parse tree produced by GremlinParser#booleanLiteral.
    def exitBooleanLiteral(self, ctx: GremlinParser.BooleanLiteralContext):
        pass

    # Enter a parse tree produced by GremlinParser#dateLiteral.
    def enterDateLiteral(self, ctx: GremlinParser.DateLiteralContext):
        pass

    # Exit a parse tree produced by GremlinParser#dateLiteral.
    def exitDateLiteral(self, ctx: GremlinParser.DateLiteralContext):
        pass

    # Enter a parse tree produced by GremlinParser#nullLiteral.
    def enterNullLiteral(self, ctx: GremlinParser.NullLiteralContext):
        pass

    # Exit a parse tree produced by GremlinParser#nullLiteral.
    def exitNullLiteral(self, ctx: GremlinParser.NullLiteralContext):
        pass

    # Enter a parse tree produced by GremlinParser#nanLiteral.
    def enterNanLiteral(self, ctx: GremlinParser.NanLiteralContext):
        pass

    # Exit a parse tree produced by GremlinParser#nanLiteral.
    def exitNanLiteral(self, ctx: GremlinParser.NanLiteralContext):
        pass

    # Enter a parse tree produced by GremlinParser#infLiteral.
    def enterInfLiteral(self, ctx: GremlinParser.InfLiteralContext):
        pass

    # Exit a parse tree produced by GremlinParser#infLiteral.
    def exitInfLiteral(self, ctx: GremlinParser.InfLiteralContext):
        pass

    # Enter a parse tree produced by GremlinParser#uuidLiteral.
    def enterUuidLiteral(self, ctx: GremlinParser.UuidLiteralContext):
        pass

    # Exit a parse tree produced by GremlinParser#uuidLiteral.
    def exitUuidLiteral(self, ctx: GremlinParser.UuidLiteralContext):
        pass

    # Enter a parse tree produced by GremlinParser#nakedKey.
    def enterNakedKey(self, ctx: GremlinParser.NakedKeyContext):
        pass

    # Exit a parse tree produced by GremlinParser#nakedKey.
    def exitNakedKey(self, ctx: GremlinParser.NakedKeyContext):
        pass

    # Enter a parse tree produced by GremlinParser#classType.
    def enterClassType(self, ctx: GremlinParser.ClassTypeContext):
        pass

    # Exit a parse tree produced by GremlinParser#classType.
    def exitClassType(self, ctx: GremlinParser.ClassTypeContext):
        pass

    # Enter a parse tree produced by GremlinParser#variable.
    def enterVariable(self, ctx: GremlinParser.VariableContext):
        pass

    # Exit a parse tree produced by GremlinParser#variable.
    def exitVariable(self, ctx: GremlinParser.VariableContext):
        pass

    # Enter a parse tree produced by GremlinParser#keyword.
    def enterKeyword(self, ctx: GremlinParser.KeywordContext):
        pass

    # Exit a parse tree produced by GremlinParser#keyword.
    def exitKeyword(self, ctx: GremlinParser.KeywordContext):
        pass


del GremlinParser
