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

import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Tuple

import gradio as gr
import pandas as pd

from hugegraph_llm.config import huge_settings, prompt, resource_path
from hugegraph_llm.flows import FlowName
from hugegraph_llm.flows.scheduler import SchedulerSingleton
from hugegraph_llm.utils.embedding_utils import get_index_folder_name
from hugegraph_llm.utils.hugegraph_utils import run_gremlin_query
from hugegraph_llm.utils.log import log


@dataclass
class GremlinResult:
    """Standardized result class for gremlin_generate function"""

    success: bool
    match_result: str
    template_gremlin: Optional[str] = None
    raw_gremlin: Optional[str] = None
    template_exec_result: Optional[str] = None
    raw_exec_result: Optional[str] = None
    error_message: Optional[str] = None

    @classmethod
    def error(cls, message: str) -> "GremlinResult":
        """Create an error result"""
        return cls(success=False, match_result=message, error_message=message)

    @classmethod
    def success_result(
        cls,
        match_result: str,
        template_gremlin: str,
        raw_gremlin: str,
        template_exec: str,
        raw_exec: str,
    ) -> "GremlinResult":
        """Create a successful result"""
        return cls(
            success=True,
            match_result=match_result,
            template_gremlin=template_gremlin,
            raw_gremlin=raw_gremlin,
            template_exec_result=template_exec,
            raw_exec_result=raw_exec,
        )


def store_schema(schema, question, gremlin_prompt):
    if (
        prompt.text2gql_graph_schema != schema
        or prompt.default_question != question
        or prompt.gremlin_generate_prompt != gremlin_prompt
    ):
        prompt.text2gql_graph_schema = schema
        prompt.default_question = question
        prompt.gremlin_generate_prompt = gremlin_prompt
        prompt.update_yaml_file()


def build_example_vector_index(temp_file) -> dict:
    folder_name = get_index_folder_name(huge_settings.graph_name, huge_settings.graph_space)
    index_path = os.path.join(resource_path, folder_name, "gremlin_examples")
    if not os.path.exists(index_path):
        os.makedirs(index_path)
    if temp_file is None:
        full_path = os.path.join(resource_path, "demo", "text2gremlin.csv")
    else:
        full_path = temp_file.name
        name, ext = os.path.splitext(temp_file.name)
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        _, file_name = os.path.split(f"{name}_{timestamp}{ext}")
        log.info("Copying file to: %s", file_name)
        target_file = os.path.join(resource_path, folder_name, "gremlin_examples", file_name)
        try:
            import shutil

            shutil.copy2(full_path, target_file)
            log.info("Successfully copied file to: %s", target_file)
        except (OSError, IOError) as e:
            log.error("Failed to copy file: %s", e)
            return {"error": f"Failed to copy file: {e}"}
        full_path = target_file
    if full_path.endswith(".json"):
        with open(full_path, "r", encoding="utf-8") as f:
            examples = json.load(f)
    elif full_path.endswith(".csv"):
        examples = pd.read_csv(full_path).to_dict("records")
    else:
        log.critical("Unsupported file format. Please input a JSON or CSV file.")
        return {"error": "Unsupported file format. Please input a JSON or CSV file."}

    return SchedulerSingleton.get_instance().schedule_flow(FlowName.BUILD_EXAMPLES_INDEX, examples)


def _process_schema(schema, generator, sm):
    """Process and validate schema input"""
    short_schema = False
    if not schema:
        return None, short_schema

    schema = schema.strip()
    if not schema.startswith("{"):
        short_schema = True
        log.info("Try to get schema from graph '%s'", schema)
        generator.import_schema(from_hugegraph=schema)
        schema = sm.schema.getSchema()
    else:
        try:
            schema = json.loads(schema)
            generator.import_schema(from_user_defined=schema)
        except json.JSONDecodeError as e:
            log.error("Invalid JSON schema provided: %s", e)
            return None, None  # Error case
    return schema, short_schema


def _configure_output_types(requested_outputs):
    """Configure which outputs are requested"""
    output_types = {
        "match_result": True,
        "template_gremlin": True,
        "raw_gremlin": True,
        "template_execution_result": True,
        "raw_execution_result": True,
    }
    if requested_outputs:
        for key in output_types:
            output_types[key] = False
        for key in requested_outputs:
            if key in output_types:
                output_types[key] = True
    return output_types


def _execute_queries(context, output_types):
    """Execute gremlin queries based on output requirements"""
    if output_types["template_execution_result"]:
        try:
            context["template_exec_res"] = run_gremlin_query(query=context["result"])
        except Exception as e:  # pylint: disable=broad-except
            context["template_exec_res"] = f"{e}"
    else:
        context["template_exec_res"] = ""

    if output_types["raw_execution_result"]:
        try:
            context["raw_exec_res"] = run_gremlin_query(query=context["raw_result"])
        except Exception as e:  # pylint: disable=broad-except
            context["raw_exec_res"] = f"{e}"
    else:
        context["raw_exec_res"] = ""


def simple_schema(schema: Dict[str, Any]) -> Dict[str, Any]:
    mini_schema = {}

    # Add necessary vertexlabels items (3)
    if "vertexlabels" in schema:
        mini_schema["vertexlabels"] = []
        for vertex in schema["vertexlabels"]:
            new_vertex = {key: vertex[key] for key in ["id", "name", "properties"] if key in vertex}
            mini_schema["vertexlabels"].append(new_vertex)

    # Add necessary edgelabels items (4)
    if "edgelabels" in schema:
        mini_schema["edgelabels"] = []
        for edge in schema["edgelabels"]:
            new_edge = {key: edge[key] for key in ["name", "source_label", "target_label", "properties"] if key in edge}
            mini_schema["edgelabels"].append(new_edge)

    return mini_schema


def gremlin_generate_for_ui(inp, example_num, schema, gremlin_prompt):
    """UI wrapper for gremlin_generate that returns tuple for Gradio compatibility"""
    # Execute via scheduler
    try:
        res = SchedulerSingleton.get_instance().schedule_flow(
            FlowName.TEXT2GREMLIN,
            inp,
            int(example_num) if isinstance(example_num, (int, float, str)) else 2,
            schema,
            gremlin_prompt,
            [
                "match_result",
                "template_gremlin",
                "raw_gremlin",
                "template_execution_result",
                "raw_execution_result",
            ],
        )
    except Exception as e:  # pylint: disable=broad-except
        log.error("UI text2gremlin error: %s", e)
        return json.dumps({"error": str(e)}, ensure_ascii=False), "", "", "", ""

    # Backward-compatible mapping for outputs
    match_result = res.get("match_result", [])
    match_result_str = (
        json.dumps(match_result, ensure_ascii=False, indent=2)
        if isinstance(match_result, (list, dict))
        else str(match_result)
    )

    return (
        match_result_str,
        res.get("template_gremlin", "") or "",
        res.get("raw_gremlin", "") or "",
        res.get("template_execution_result", "") or "",
        res.get("raw_execution_result", "") or "",
    )


def create_text2gremlin_block() -> Tuple:
    gr.Markdown(
        """## Build Vector Template Index (Optional)
    > Uploaded CSV file should be in `query,gremlin` format below:
    > e.g. `who is peter?`,`g.V().has('name', 'peter')`
    > JSON file should be in format below:
    > e.g. `[{"query":"who is peter", "gremlin":"g.V().has('name', 'peter')"}]`
    """
    )
    with gr.Row():
        file = gr.File(
            value=os.path.join(resource_path, "demo", "text2gremlin.csv"),
            label="Upload Text-Gremlin Pairs File",
        )
        out = gr.Textbox(label="Result Message")
    with gr.Row():
        btn = gr.Button("Build Example Vector Index", variant="primary")
    btn.click(build_example_vector_index, inputs=[file], outputs=[out])  # pylint: disable=no-member
    gr.Markdown("## Nature Language To Gremlin")

    with gr.Row():
        with gr.Column(scale=1):
            input_box = gr.Textbox(
                value=prompt.default_question,
                label="Nature Language Query",
                show_copy_button=True,
            )
            match = gr.Code(
                label="Similar Template (TopN)",
                language="javascript",
                elem_classes="code-container-show",
            )
            initialized_out = gr.Textbox(label="Gremlin With Template", show_copy_button=True)
            raw_out = gr.Textbox(label="Gremlin Without Template", show_copy_button=True)
            tmpl_exec_out = gr.Code(
                label="Query With Template Output",
                language="json",
                elem_classes="code-container-show",
            )
            raw_exec_out = gr.Code(
                label="Query Without Template Output",
                language="json",
                elem_classes="code-container-show",
            )

        with gr.Column(scale=1):
            example_num_slider = gr.Slider(minimum=0, maximum=10, step=1, value=2, label="Number of refer examples")
            schema_box = gr.Textbox(
                value=prompt.text2gql_graph_schema,
                label="Schema",
                lines=2,
                show_copy_button=True,
            )
            prompt_box = gr.Textbox(
                value=prompt.gremlin_generate_prompt,
                label="Prompt",
                lines=20,
                show_copy_button=True,
            )
            btn = gr.Button("Text2Gremlin", variant="primary")
    btn.click(  # pylint: disable=no-member
        fn=gremlin_generate_for_ui,
        inputs=[input_box, example_num_slider, schema_box, prompt_box],
        outputs=[match, initialized_out, raw_out, tmpl_exec_out, raw_exec_out],
    )

    return input_box, schema_box, prompt_box


def graph_rag_recall(
    query: str,
    gremlin_tmpl_num: int,
    rerank_method: Literal["bleu", "reranker"],
    near_neighbor_first: bool,
    custom_related_information: str,
    gremlin_prompt: str,
    max_graph_items: int,
    topk_return_results: int,
    vector_dis_threshold: float,
    topk_per_keyword: int,
    get_vertex_only: bool = False,
) -> dict:
    store_schema(prompt.text2gql_graph_schema, query, gremlin_prompt)
    context = SchedulerSingleton.get_instance().schedule_flow(
        FlowName.RAG_GRAPH_ONLY,
        query=query,
        gremlin_tmpl_num=gremlin_tmpl_num,
        rerank_method=rerank_method,
        near_neighbor_first=near_neighbor_first,
        custom_related_information=custom_related_information,
        gremlin_prompt=gremlin_prompt,
        max_graph_items=max_graph_items,
        topk_return_results=topk_return_results,
        vector_dis_threshold=vector_dis_threshold,
        topk_per_keyword=topk_per_keyword,
        is_graph_rag_recall=True,
        is_vector_only=get_vertex_only,
    )
    return context


def gremlin_generate_selective(
    inp: str,
    example_num: int,
    schema_input: str,
    gremlin_prompt_input: str,
    requested_outputs: Optional[List[str]] = None,
    graph_client_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    response_dict = SchedulerSingleton.get_instance().schedule_flow(
        FlowName.TEXT2GREMLIN,
        inp,
        example_num,
        schema_input,
        gremlin_prompt_input,
        requested_outputs,
        graph_client_config,
    )

    return response_dict
