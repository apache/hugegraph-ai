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


import traceback
from typing import Any, Dict, List, Union

import gradio as gr
from pyhugegraph.client import PyHugeClient

from hugegraph_llm.flows import FlowName
from hugegraph_llm.flows.scheduler import SchedulerSingleton
from hugegraph_llm.operators.document_op.chunk_split import (
    SPLIT_TYPE_DOCUMENT,
    VALID_SPLIT_TYPES,
)

from ..config import huge_settings
from .hugegraph_utils import clean_hg_data
from .log import log
from .vector_index_utils import read_documents


def get_graph_index_info():
    try:
        scheduler = SchedulerSingleton.get_instance()
        return scheduler.schedule_flow(FlowName.GET_GRAPH_INDEX_INFO)
    except Exception as e:  # pylint: disable=broad-exception-caught
        log.error(e)
        raise gr.Error(str(e))


def clean_all_graph_index():
    # Lazy import to avoid circular dependency
    from ..config import index_settings  # pylint: disable=import-outside-toplevel
    from .vector_index_utils import get_vector_index_class  # pylint: disable=import-outside-toplevel

    vector_index = get_vector_index_class(index_settings.cur_vector_index)
    vector_index.clean(huge_settings.graph_name, "graph_vids")
    vector_index.clean("gremlin_examples")
    log.warning("Clear graph index and text2gql index successfully!")
    gr.Info("Clear graph index and text2gql index successfully!")


def get_vertex_details(vertex_ids: List[str], context: Dict[str, Any]) -> List[Dict[str, Any]]:
    if isinstance(context.get("graph_client"), PyHugeClient):
        client = context["graph_client"]
    else:
        url = context.get("url") or "http://localhost:8080"
        graph = context.get("graph") or "hugegraph"
        user = context.get("user") or "admin"
        pwd = context.get("pwd") or "admin"
        gs = context.get("graphspace") or None
        client = PyHugeClient(url, graph, user, pwd, gs)
    if not vertex_ids:
        return []

    formatted_ids = ", ".join(f"'{vid}'" for vid in vertex_ids)
    gremlin_query = f"g.V({formatted_ids}).limit(20)"
    result = client.gremlin().exec(gremlin=gremlin_query)["data"]
    return result


def clean_all_graph_data():
    clean_hg_data()
    log.warning("Clear graph data successfully!")
    gr.Info("Clear graph data successfully!")


def extract_graph(
    input_file,
    input_text,
    schema,
    example_prompt,
    split_type=SPLIT_TYPE_DOCUMENT,
) -> str:
    texts = read_documents(input_file, input_text)
    scheduler = SchedulerSingleton.get_instance()
    if not schema:
        return "ERROR: please input with correct schema/format."
    if split_type not in VALID_SPLIT_TYPES:
        raise gr.Error("split_type must be document, paragraph, or sentence")
    try:
        return scheduler.schedule_flow(
            FlowName.GRAPH_EXTRACT,
            schema,
            texts,
            example_prompt,
            "property_graph",
            split_type=split_type,
        )
    except Exception as e:  # pylint: disable=broad-exception-caught
        log.error(e)
        raise gr.Error(str(e))


def update_vid_embedding():
    scheduler = SchedulerSingleton.get_instance()
    try:
        return scheduler.schedule_flow(FlowName.UPDATE_VID_EMBEDDINGS)
    except Exception as e:  # pylint: disable=broad-exception-caught
        log.error(e)
        raise gr.Error(str(e))


def import_graph_data(data: str, schema: str) -> Union[str, Dict[str, Any]]:
    try:
        scheduler = SchedulerSingleton.get_instance()
        return scheduler.schedule_flow(FlowName.IMPORT_GRAPH_DATA, data, schema)
    except Exception as e:  # pylint: disable=W0718
        log.error(e)
        traceback.print_exc()
        # Note: can't use gr.Error here
        gr.Warning(str(e) + " Please check the graph data format/type carefully.")
        return data


def build_schema(input_text, query_example, few_shot):
    scheduler = SchedulerSingleton.get_instance()
    try:
        return scheduler.schedule_flow(FlowName.BUILD_SCHEMA, input_text, query_example, few_shot)
    except Exception as e:  # pylint: disable=broad-exception-caught
        log.error("Schema generation failed: %s", e)
        raise gr.Error(f"Schema generation failed: {e}")
