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

import argparse
import os

import gradio as gr
import uvicorn
from fastapi import APIRouter, Depends, FastAPI
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from hugegraph_llm.api.admin_api import admin_http_api
from hugegraph_llm.api.graph_extract_api import graph_extract_http_api
from hugegraph_llm.api.rag_api import rag_http_api
from hugegraph_llm.config import admin_settings, huge_settings, prompt
from hugegraph_llm.demo.rag_demo.admin_block import create_admin_block, log_stream
from hugegraph_llm.demo.rag_demo.configs_block import (
    apply_embedding_config,
    apply_graph_config,
    apply_llm_config,
    apply_reranker_config,
    create_configs_block,
    get_header_with_language_indicator,
)
from hugegraph_llm.demo.rag_demo.other_block import create_other_block, lifespan
from hugegraph_llm.demo.rag_demo.rag_block import create_rag_block, rag_answer
from hugegraph_llm.demo.rag_demo.text2gremlin_block import (
    create_text2gremlin_block,
    graph_rag_recall,
    gremlin_generate_selective,
)
from hugegraph_llm.demo.rag_demo.vector_graph_block import create_vector_graph_block
from hugegraph_llm.resources.demo.css import CSS
from hugegraph_llm.utils.log import log

sec = HTTPBearer()


def authenticate(credentials: HTTPAuthorizationCredentials = Depends(sec)):
    correct_token = admin_settings.user_token
    if credentials.credentials != correct_token:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=401,
            detail=f"Invalid token {credentials.credentials}, please contact the admin",
            headers={"WWW-Authenticate": "Bearer"},
        )


# pylint: disable=C0301
def init_rag_ui() -> gr.Interface:
    with gr.Blocks(
        theme="default",
        title="HugeGraph RAG Platform",
        css=CSS,
    ) as hugegraph_llm_ui:
        gr.HTML(value=get_header_with_language_indicator(prompt.llm_settings.language))

        """
        TODO: leave a general idea of the unresolved part
        graph_config_input = textbox_array_graph_config
         = [settings.graph_url, settings.graph_name, graph_user, settings.graph_pwd, settings.graph_space]

        llm_config_input = textbox_array_llm_config
         = if settings.llm_type == openai [settings.openai_api_key, settings.openai_api_base, settings.openai_language_model, settings.openai_max_tokens]
         = else if settings.llm_type == ollama [settings.ollama_host, settings.ollama_port, settings.ollama_language_model, ""]
         = else ["","","", ""]

        embedding_config_input = textbox_array_embedding_config
         = if settings.embedding_type == openai [settings.openai_api_key, settings.openai_api_base, settings.openai_embedding_model]
         = else if settings.embedding_type == ollama [settings.ollama_host, settings.ollama_port, settings.ollama_embedding_model]
         = else ["","",""]

        reranker_config_input = textbox_array_reranker_config
         = if settings.reranker_type == cohere [settings.reranker_api_key, settings.reranker_model, settings.cohere_base_url]
         = else if settings.reranker_type == siliconflow [settings.reranker_api_key, "BAAI/bge-reranker-v2-m3", ""]
         = else ["","",""]
        """

        textbox_array_graph_config = create_configs_block()

        with gr.Tab(label="1. Build RAG Index 💡"):
            textbox_input_text, textbox_input_schema, textbox_info_extract_template = create_vector_graph_block()
        with gr.Tab(label="2. (Graph)RAG & User Functions 📖"):
            (
                textbox_inp,
                textbox_answer_prompt_input,
                textbox_keywords_extract_prompt_input,
                textbox_custom_related_information,
            ) = create_rag_block()
        with gr.Tab(label="3. Text2gremlin ⚙️"):
            textbox_gremlin_inp, textbox_gremlin_schema, textbox_gremlin_prompt = create_text2gremlin_block()
        with gr.Tab(label="4. Graph Tools 🚧"):
            create_other_block()
        with gr.Tab(label="5. Admin Tools 🛠"):
            create_admin_block()

        def refresh_ui_config_prompt() -> tuple:
            # we can use its __init__() for in-place reload
            # settings.from_env()
            huge_settings.__init__()  # type: ignore[misc] # pylint: disable=C2801
            prompt.ensure_yaml_file_exists()
            return (
                huge_settings.graph_url,
                huge_settings.graph_name,
                huge_settings.graph_user,
                huge_settings.graph_pwd,
                huge_settings.graph_space,
                prompt.doc_input_text,
                prompt.graph_schema,
                prompt.extract_graph_prompt,
                prompt.default_question,
                prompt.answer_prompt,
                prompt.keywords_extract_prompt,
                prompt.custom_rerank_info,
                prompt.default_question,
                huge_settings.graph_name,
                prompt.gremlin_generate_prompt,
            )

        hugegraph_llm_ui.load(  # pylint: disable=E1101
            fn=refresh_ui_config_prompt,
            outputs=[
                textbox_array_graph_config[0],
                textbox_array_graph_config[1],
                textbox_array_graph_config[2],
                textbox_array_graph_config[3],
                textbox_array_graph_config[4],
                textbox_input_text,
                textbox_input_schema,
                textbox_info_extract_template,
                textbox_inp,
                textbox_answer_prompt_input,
                textbox_keywords_extract_prompt_input,
                textbox_custom_related_information,
                textbox_gremlin_inp,
                textbox_gremlin_schema,
                textbox_gremlin_prompt,
            ],
        )

    return hugegraph_llm_ui


def create_app():
    app = FastAPI(lifespan=lifespan)
    # we don't need to manually check the env now
    # settings.check_env()
    prompt.update_yaml_file()
    auth_enabled = admin_settings.enable_login.lower() == "true"
    log.info("(Status) Authentication is %s now.", "enabled" if auth_enabled else "disabled")
    api_auth = APIRouter(dependencies=[Depends(authenticate)] if auth_enabled else [])

    hugegraph_llm = init_rag_ui()

    rag_http_api(
        api_auth,
        rag_answer,
        graph_rag_recall,
        apply_graph_config,
        apply_llm_config,
        apply_embedding_config,
        apply_reranker_config,
        gremlin_generate_selective,
    )
    admin_http_api(api_auth, log_stream)
    graph_extract_http_api(api_auth)

    app.include_router(api_auth)
    # Mount Gradio inside FastAPI
    # TODO: support multi-user login when need
    app = gr.mount_gradio_app(
        app,
        hugegraph_llm,
        path="/",
        auth=("rag", admin_settings.user_token) if auth_enabled else None,
    )

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", type=str, default="0.0.0.0", help="host")
    parser.add_argument("--port", type=int, default=8001, help="port")
    args = parser.parse_args()

    uvicorn.run(
        "hugegraph_llm.demo.rag_demo.app:create_app",
        host=args.host,
        port=args.port,
        factory=True,
        reload=os.getenv("HG_DEV_RELOAD") == "1",
    )
