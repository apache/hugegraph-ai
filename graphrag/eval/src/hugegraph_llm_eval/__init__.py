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

"""Installable evaluation SDK for GraphRAG pipelines and Python projects.

The package depends on Pydantic only. Callers supply evaluation inputs, inject a
Judge model when a metric needs one, and receive structured records that can be
persisted elsewhere or fed back into a pipeline repair loop.
"""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _distribution_version

from hugegraph_llm_eval.api import aevaluate, aevaluate_many, evaluate, evaluate_many
from hugegraph_llm_eval.artifacts.memory import InMemoryArtifactStore
from hugegraph_llm_eval.contracts.domain.evaluation import (
    EvaluationContext,
    EvaluationInput,
    EvaluationRecord,
    EvaluationRecordDraft,
    EvaluationRecordStatus,
    EvaluationRunStatus,
    EvaluationSubject,
    Evaluator,
    EvaluatorDescriptor,
)
from hugegraph_llm_eval.evaluation.engine import EvaluationEngine, EvaluationResult, MetricEvaluator
from hugegraph_llm_eval.evaluation.judges.base import (
    Judge,
    JudgeCallError,
    JudgeDescriptor,
    JudgeMessage,
    JudgeOptions,
    JudgeRequest,
    JudgeResult,
)
from hugegraph_llm_eval.evaluation.judges.batching import BatchingOptions
from hugegraph_llm_eval.evaluation.judges.content import JudgeContent
from hugegraph_llm_eval.evaluation.options import CancellationToken, EvaluationOptions
from hugegraph_llm_eval.integrations.answer.evaluators.correctness import (
    AnswerCorrectnessEvaluator,
    FactualCorrectnessEvaluator,
)
from hugegraph_llm_eval.integrations.answer.evaluators.grounding import (
    FaithfulnessEvaluator as AnswerFaithfulnessEvaluator,
)
from hugegraph_llm_eval.integrations.answer.evaluators.grounding import NoiseSensitivityEvaluator
from hugegraph_llm_eval.integrations.answer.evaluators.lexical import RougeLEvaluator
from hugegraph_llm_eval.integrations.graph_extraction.evaluators.faithfulness import (
    FaithfulnessEvaluator as GraphFaithfulnessEvaluator,
)
from hugegraph_llm_eval.integrations.graph_extraction.evaluators.schema_validity import SchemaValidityEvaluator
from hugegraph_llm_eval.integrations.graph_extraction.evaluators.semantic import (
    SemanticEntityEvaluator,
    SemanticTripleEvaluator,
)
from hugegraph_llm_eval.integrations.judges.claude_code import ClaudeCodeJudge
from hugegraph_llm_eval.integrations.judges.codex_app_server import CodexAppServerJudge
from hugegraph_llm_eval.integrations.judges.factory import (
    AuthMode,
    ClaudeCodeJudgeConfig,
    CodexJudgeConfig,
    JudgeConfig,
    OpenAIJudgeConfig,
    create_judge,
    managed_judge,
    parse_judge_config,
)
from hugegraph_llm_eval.integrations.judges.openai_client import OpenAIClientTransport, openai_judge
from hugegraph_llm_eval.integrations.retrieval.evaluators.context_quality import (
    ContextPrecisionEvaluator,
    ContextRelevancyEvaluator,
)
from hugegraph_llm_eval.integrations.retrieval.evaluators.coverage import (
    ContextEntityRecallEvaluator,
    EvidenceRecallEvaluator,
)
from hugegraph_llm_eval.integrations.retrieval.evaluators.ranking import (
    HitAtKEvaluator,
    MRREvaluator,
    RecallAtKEvaluator,
)
from hugegraph_llm_eval.samples import (
    answer_input,
    graph_extraction_input,
    graph_review_input,
    retrieval_input,
)

try:
    __version__ = _distribution_version("hugegraph-llm-eval")
except PackageNotFoundError:  # Source tree without an installed distribution.
    __version__ = "0.0.0"

__all__ = [
    "AnswerCorrectnessEvaluator",
    "AnswerFaithfulnessEvaluator",
    "AuthMode",
    "BatchingOptions",
    "CancellationToken",
    "ClaudeCodeJudge",
    "ClaudeCodeJudgeConfig",
    "CodexAppServerJudge",
    "CodexJudgeConfig",
    "ContextEntityRecallEvaluator",
    "ContextPrecisionEvaluator",
    "ContextRelevancyEvaluator",
    "EvaluationContext",
    "EvaluationEngine",
    "EvaluationInput",
    "EvaluationOptions",
    "EvaluationRecord",
    "EvaluationRecordDraft",
    "EvaluationRecordStatus",
    "EvaluationResult",
    "EvaluationRunStatus",
    "EvaluationSubject",
    "Evaluator",
    "EvaluatorDescriptor",
    "EvidenceRecallEvaluator",
    "FactualCorrectnessEvaluator",
    "GraphFaithfulnessEvaluator",
    "HitAtKEvaluator",
    "InMemoryArtifactStore",
    "Judge",
    "JudgeCallError",
    "JudgeConfig",
    "JudgeContent",
    "JudgeDescriptor",
    "JudgeMessage",
    "JudgeOptions",
    "JudgeRequest",
    "JudgeResult",
    "MRREvaluator",
    "MetricEvaluator",
    "NoiseSensitivityEvaluator",
    "OpenAIClientTransport",
    "OpenAIJudgeConfig",
    "RecallAtKEvaluator",
    "RougeLEvaluator",
    "SchemaValidityEvaluator",
    "SemanticEntityEvaluator",
    "SemanticTripleEvaluator",
    "__version__",
    "aevaluate",
    "aevaluate_many",
    "answer_input",
    "create_judge",
    "evaluate",
    "evaluate_many",
    "graph_extraction_input",
    "graph_review_input",
    "managed_judge",
    "openai_judge",
    "parse_judge_config",
    "retrieval_input",
]
