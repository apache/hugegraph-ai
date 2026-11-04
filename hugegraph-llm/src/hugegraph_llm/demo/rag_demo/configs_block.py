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

from functools import partial, wraps
from typing import Optional

import gradio as gr
import requests
from requests.auth import HTTPBasicAuth

from hugegraph_llm.config import huge_settings, index_settings, llm_settings, runtime_config_lock
from hugegraph_llm.utils.log import log


def _restore_config(settings, values):
    for field, value in values.items():
        setattr(settings, field, value)


def _transactional_config_update(settings_getter, connection_group=None):
    """Serialize, persist on success, and roll back failed config updates."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            settings = settings_getter()
            with runtime_config_lock:
                original_values = settings.model_dump()
                try:
                    status_code = func(*args, **kwargs)
                    if not 200 <= status_code < 300:
                        _restore_config(settings, original_values)
                        return status_code
                    if connection_group is None:
                        settings.update_env()
                    else:
                        group = args[0] if connection_group == "role" else connection_group
                        settings.update_env(connection_group=group)
                except Exception:
                    _restore_config(settings, original_values)
                    raise
                gr.Info("Configured!")
                return status_code

        return wrapper

    return decorator


def test_api_connection(url, method="GET", headers=None, params=None, body=None, auth=None, origin_call=None) -> int:
    # TODO: use fastapi.request / starlette instead?
    try:
        if method.upper() == "GET":
            resp = requests.get(url, headers=headers, params=params, timeout=(1.0, 5.0), auth=auth)
        elif method.upper() == "POST":
            resp = requests.post(
                url,
                headers=headers,
                params=params,
                json=body,
                timeout=(1.0, 5.0),
                auth=auth,
            )
        else:
            raise ValueError("Unsupported HTTP method, please use GET/POST instead")
    except requests.exceptions.RequestException as e:
        # Request exception messages can include credentials or a sensitive URL.
        msg = f"Connection failed ({type(e).__name__}). Please check the connection settings."
        log.error(msg)
        if origin_call is None:
            raise gr.Error(msg) from None
        return -1  # Error code

    if 200 <= resp.status_code < 300:
        msg = "Test connection successful~"
        log.info(msg)
        gr.Info(msg)
    else:
        # Servers can echo request credentials in any response-body format.
        msg = f"Connection failed with status code: {resp.status_code}."
        log.error(msg)
        if origin_call is None:
            raise gr.Error(msg)
    return resp.status_code


@_transactional_config_update(lambda: index_settings)
def apply_vector_engine(engine: str):
    index_settings.cur_vector_index = engine
    return 200


@_transactional_config_update(lambda: index_settings)
def apply_vector_engine_backend(  # pylint: disable=too-many-branches
    engine: str,
    host: Optional[str] = None,
    port: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    api_key: Optional[str] = None,
    origin_call=None,
) -> int:
    """Validate, probe, and persist one vector backend configuration."""
    status_code = -1

    if engine == "Milvus":
        if host is not None:
            index_settings.milvus_host = host
        if port is not None and str(port).strip():
            index_settings.milvus_port = int(port)  # type: ignore[arg-type]
        index_settings.milvus_user = user or ""
        index_settings.milvus_password = password or ""
    elif engine == "Qdrant":
        if host is not None:
            index_settings.qdrant_host = host
        if port is not None and str(port).strip():
            index_settings.qdrant_port = int(port)  # type: ignore[arg-type]
        index_settings.qdrant_api_key = api_key or None
    else:
        raise ValueError(f"Unsupported vector engine: {engine}")

    # Reject a managed secret/target change before any credentialed connection.
    index_settings.validate_update()

    try:
        if engine == "Milvus":
            from pymilvus import connections, utility

            connections.connect(
                host=index_settings.milvus_host,
                port=index_settings.milvus_port,
                user=index_settings.milvus_user,
                password=index_settings.milvus_password,
            )
            _ = utility.list_collections()
            connections.disconnect("default")
            status_code = 200
        elif engine == "Qdrant":
            from qdrant_client import QdrantClient

            client = QdrantClient(
                host=index_settings.qdrant_host,
                port=index_settings.qdrant_port,
                api_key=index_settings.qdrant_api_key,
            )
            _ = client.get_collections()
            status_code = 200
    except ImportError as e:
        msg = f"Missing dependency: {e}. Please install with: uv sync --extra vectordb"
        if origin_call is None:
            raise gr.Error(msg) from e
        return -1
    except Exception as e:  # pylint: disable=broad-exception-caught
        msg = f"Connection failed: {e}"
        log.error(msg)
        if origin_call is None:
            raise gr.Error(msg) from e
        return -1

    return status_code


def _saved_key(group, key_field, supplied, destination_fields, clear=False):
    """Blank means retain, explicit clear deletes; new destinations need new keys."""
    if clear:
        if supplied:
            raise ValueError("Supply a key or clear it, not both")
        return None
    if supplied:
        return supplied
    previous = llm_settings._saved_values
    for field in destination_fields:
        old, new = previous.get(field), getattr(llm_settings, field)
        if field.startswith("litellm_") and field.endswith(("_language_model", "_model")):
            # A provider/model name can change within one provider without changing
            # where its key goes. An unqualified name remains an explicit route.
            old, new = str(old or "").split("/", 1)[0], str(new or "").split("/", 1)[0]
        if old != new and previous.get(key_field):
            raise ValueError("Changing the model destination requires a new API key or explicit clear")
    return previous.get(key_field)


@_transactional_config_update(lambda: llm_settings, "embedding")
def apply_embedding_config(arg1, arg2, arg3, origin_call=None, clear_api_key=False, provider=None) -> int:
    if provider is not None:
        llm_settings.embedding_type = provider
    provider = llm_settings.embedding_type
    prefix = "ollama" if provider == "ollama/local" else provider
    if provider not in ("openai", "litellm", "ollama/local"):
        raise ValueError("Unsupported embedding provider")
    if provider == "ollama/local":
        llm_settings.ollama_embedding_host = arg1
        llm_settings.ollama_embedding_port = int(arg2)
    else:
        setattr(llm_settings, f"{prefix}_embedding_model", arg3)
        setattr(llm_settings, f"{prefix}_embedding_api_base", arg2)
        key = f"{prefix}_embedding_api_key"
        setattr(
            llm_settings,
            key,
            _saved_key(
                "embedding",
                key,
                arg1,
                (
                    "embedding_type",
                    f"{prefix}_embedding_api_base",
                    *((f"{prefix}_embedding_model",) if provider == "litellm" else ()),
                ),
                clear_api_key,
            ),
        )
    setattr(llm_settings, f"{prefix}_embedding_model", arg3)
    return 200


@_transactional_config_update(lambda: llm_settings, "reranker")
def apply_reranker_config(
    reranker_api_key=None,
    reranker_model=None,
    cohere_base_url=None,
    origin_call=None,
    clear_api_key=False,
    provider=None,
) -> int:
    if provider is not None:
        llm_settings.reranker_type = provider if provider != "None" else None
    if llm_settings.reranker_type == "cohere":
        llm_settings.cohere_base_url = cohere_base_url
    llm_settings.reranker_api_key = _saved_key(
        "reranker", "reranker_api_key", reranker_api_key, ("reranker_type", "cohere_base_url"), clear_api_key
    )
    llm_settings.reranker_model = reranker_model
    return 200


@_transactional_config_update(lambda: huge_settings)
def apply_graph_config(url, name, user, pwd, gs, origin_call=None) -> int:
    # Add URL prefix automatically to improve the user experience
    if url and not (url.startswith("http://") or url.startswith("https://")):
        url = f"http://{url}"

    huge_settings.graph_url = url
    huge_settings.graph_name = name
    huge_settings.graph_user = user
    huge_settings.graph_pwd = pwd
    huge_settings.graph_space = gs
    huge_settings.validate_update()
    # Test graph connection (Auth)
    if gs and gs.strip():
        test_url = f"{url}/graphspaces/{gs}/graphs/{name}/schema"
    else:
        test_url = f"{url}/graphs/{name}/schema"
    auth = HTTPBasicAuth(user, pwd)
    # for http api return status
    response = test_api_connection(test_url, auth=auth, origin_call=origin_call)
    return response


@_transactional_config_update(lambda: llm_settings, "role")
def apply_llm_config(
    current_llm_config,
    api_key_or_host,
    api_base_or_port,
    model_name,
    max_tokens,
    origin_call=None,
    clear_api_key=False,
    provider=None,
) -> int:
    roles = ("chat", "extract", "text2gql") if current_llm_config == "all" else (current_llm_config,)
    for role in roles:
        if role not in ("chat", "extract", "text2gql"):
            raise ValueError("Unsupported model role")
        if provider is not None:
            setattr(llm_settings, f"{role}_llm_type", provider)
        provider = getattr(llm_settings, f"{role}_llm_type")
        prefix = "ollama" if provider == "ollama/local" else provider
        if role != "chat":
            setattr(llm_settings, f"{role}_use_chat", False)
        if provider == "ollama/local":
            setattr(llm_settings, f"ollama_{role}_host", api_key_or_host)
            setattr(llm_settings, f"ollama_{role}_port", int(api_base_or_port))
        elif provider in ("openai", "litellm"):
            base, key = f"{prefix}_{role}_api_base", f"{prefix}_{role}_api_key"
            setattr(llm_settings, f"{prefix}_{role}_language_model", model_name)
            setattr(llm_settings, base, api_base_or_port)
            setattr(
                llm_settings,
                key,
                _saved_key(
                    role,
                    key,
                    api_key_or_host,
                    (
                        f"{role}_llm_type",
                        base,
                        *((f"{prefix}_{role}_language_model",) if provider == "litellm" else ()),
                    ),
                    clear_api_key,
                ),
            )
            if max_tokens is not None:
                setattr(llm_settings, f"{prefix}_{role}_tokens", int(max_tokens))
        else:
            raise ValueError("Unsupported model provider")
        setattr(llm_settings, f"{prefix}_{role}_language_model", model_name)
    return 200


def test_saved_model(role="chat"):
    """Test a saved connection; never save, mutate, or roll back configuration."""
    from hugegraph_llm.models.embeddings.init_embedding import get_embedding
    from hugegraph_llm.models.llms.init_llm import get_chat_llm, get_extract_llm, get_text2gql_llm

    with runtime_config_lock:
        settings = llm_settings.model_copy(deep=True)
    if role in ("chat", "extract", "text2gql"):
        client = {"chat": get_chat_llm, "extract": get_extract_llm, "text2gql": get_text2gql_llm}[role](settings)
        result = client.generate(messages=[{"role": "user", "content": "hi"}])
    elif role == "embedding":
        result = get_embedding(settings).get_text_embedding("test")
    elif role == "reranker":
        from hugegraph_llm.models.rerankers.cohere import CohereReranker
        from hugegraph_llm.models.rerankers.siliconflow import SiliconReranker

        if settings.reranker_type not in ("cohere", "siliconflow"):
            raise ValueError("No reranker connection is configured")
        cls = CohereReranker if settings.reranker_type == "cohere" else SiliconReranker
        kwargs = {"api_key": settings.reranker_api_key, "model": settings.reranker_model}
        if settings.reranker_type == "cohere":
            kwargs["base_url"] = settings.cohere_base_url
        result = cls(**kwargs).get_rerank_lists("test", ["test"])
    else:
        raise ValueError("Unsupported model role")
    if not result:
        raise ValueError("Model service returned an empty response")
    return 200


@_transactional_config_update(lambda: llm_settings, "role")
def use_chat_connection(role, enabled, origin_call=None):
    if role not in ("extract", "text2gql"):
        raise ValueError("Unsupported inherited model role")
    setattr(llm_settings, f"{role}_use_chat", bool(enabled))
    return 200


def save_model_form(role, provider, key, base, model, tokens, clear):
    apply_llm_config(role, key, base, model, tokens, clear_api_key=clear, provider=provider)
    return False if role != "chat" else None


def test_model_form(role):
    try:
        test_saved_model(role)
    except Exception as exc:
        raise gr.Error(f"Connection test failed ({type(exc).__name__}). Saved configuration is unchanged.") from None
    gr.Info("Connection test successful")
    return 200


def _model_form(role, provider, inherit=None):
    """Rendering/editing a form never changes the active connection."""
    prefix = "ollama" if provider == "ollama/local" else provider
    if provider == "ollama/local":
        inputs = [
            gr.Textbox(interactive=True, value=getattr(llm_settings, f"ollama_{role}_host"), label="host"),
            gr.Textbox(interactive=True, value=str(getattr(llm_settings, f"ollama_{role}_port")), label="port"),
        ]
    else:
        inputs = [
            gr.Textbox(
                interactive=True,
                value="",
                label="API key",
                type="password",
                info="Leave blank to keep the saved key. Use Clear API key to delete it.",
            ),
            gr.Textbox(interactive=True, value=getattr(llm_settings, f"{prefix}_{role}_api_base"), label="API base"),
        ]
    inputs.append(
        gr.Textbox(interactive=True, value=getattr(llm_settings, f"{prefix}_{role}_language_model"), label="model")
    )
    inputs.append(
        gr.Textbox(
            interactive=True,
            value=getattr(llm_settings, f"{prefix}_{role}_tokens", ""),
            label="max tokens",
            visible=provider != "ollama/local",
        )
    )
    clear = gr.Checkbox(label="Clear API key", value=False, visible=provider != "ollama/local")
    gr.Button("Save configuration").click(
        partial(save_model_form, role, provider),
        inputs=[*inputs, clear],
        outputs=[inherit] if inherit is not None else [],
    )
    gr.Button("Test saved connection").click(partial(test_model_form, role))


def _register_model_form(role, dropdown, inherit=None):
    def render(provider):
        _model_form(role, provider, inherit)

    render.__name__ = f"{role}_llm_settings"
    gr.render(inputs=[dropdown])(render)


# TODO: refactor the function to reduce the number of statements & separate the logic
# pylint: disable=C0301,E1101
def create_configs_block() -> list:
    # pylint: disable=R0915 (too-many-statements)
    managed = [
        f"{field} ({settings.environment_source(field)})"
        for settings in (huge_settings, llm_settings, index_settings)
        for field in type(settings).model_fields
        if settings.environment_source(field)
    ]
    if managed:
        gr.Markdown(
            "**Managed externally:** "
            + ", ".join(managed)
            + ". Edit the deployment environment and restart to change these fields. "
            "Saving a different value here will be rejected."
        )

    with gr.Accordion("1. Set up the HugeGraph server.", open=False):
        with gr.Row():
            graph_config_input = [
                gr.Textbox(
                    interactive=True,
                    value=huge_settings.graph_url,
                    label="url",
                    info="IP:PORT (e.g. 127.0.0.1:8080) or full URL (e.g. http://127.0.0.1:8080)",
                ),
                gr.Textbox(
                    interactive=True,
                    value=huge_settings.graph_name,
                    label="graph",
                    info="The graph name of HugeGraph-Server instance",
                ),
                gr.Textbox(
                    interactive=True,
                    value=huge_settings.graph_user,
                    label="user",
                    info="Username for graph server auth",
                ),
                gr.Textbox(
                    interactive=True,
                    value=huge_settings.graph_pwd,
                    label="pwd",
                    type="password",
                    info="Password for graph server auth",
                ),
                gr.Textbox(
                    interactive=True,
                    value=huge_settings.graph_space,
                    label="graphspace (Optional)",
                    info="Namespace for multi-tenant scenarios (leave empty if not using graphspaces)",
                ),
            ]
        graph_config_button = gr.Button("Apply Configuration")
    graph_config_button.click(apply_graph_config, inputs=graph_config_input)  # pylint: disable=no-member

    with gr.Accordion("2. Set up the LLM.", open=False):
        gr.Markdown(
            "Save configuration without contacting the model service. Test the saved connection separately. "
            "Information extraction and Text2GQL use Chat until configured independently."
        )
        for role in ("chat", "extract", "text2gql"):
            with gr.Tab(label=role):
                inherit = None
                if role != "chat":
                    inherit = gr.Checkbox(label="Use Chat connection", value=getattr(llm_settings, f"{role}_use_chat"))
                    inherit.input(partial(use_chat_connection, role), inputs=inherit)
                    gr.Markdown("Saving a connection below switches this role to its own configuration.")
                dropdown = gr.Dropdown(
                    choices=["openai", "litellm", "ollama/local"],
                    value=getattr(llm_settings, f"{role}_llm_type"),
                    label="Provider",
                )
                _register_model_form(role, dropdown, inherit)

    with gr.Accordion("3. Set up the Embedding.", open=False):
        embedding_dropdown = gr.Dropdown(
            choices=["openai", "litellm", "ollama/local"], value=llm_settings.embedding_type, label="Provider"
        )

        @gr.render(inputs=[embedding_dropdown])
        def embedding_settings(provider):
            prefix = "ollama" if provider == "ollama/local" else provider
            if provider == "ollama/local":
                inputs = [
                    gr.Textbox(interactive=True, value=llm_settings.ollama_embedding_host, label="host"),
                    gr.Textbox(interactive=True, value=str(llm_settings.ollama_embedding_port), label="port"),
                ]
            else:
                inputs = [
                    gr.Textbox(interactive=True, value="", label="API key", type="password"),
                    gr.Textbox(
                        interactive=True, value=getattr(llm_settings, f"{prefix}_embedding_api_base"), label="API base"
                    ),
                ]
            inputs.append(
                gr.Textbox(interactive=True, value=getattr(llm_settings, f"{prefix}_embedding_model"), label="model")
            )
            clear = gr.Checkbox(label="Clear API key", value=False, visible=provider != "ollama/local")
            gr.Button("Save configuration").click(
                lambda key, base, model, clear_key: apply_embedding_config(
                    key, base, model, clear_api_key=clear_key, provider=provider
                ),
                inputs=[*inputs, clear],
            )
            gr.Button("Test saved connection").click(partial(test_model_form, "embedding"))

    with gr.Accordion("4. Set up the Reranker.", open=False):
        reranker_dropdown = gr.Dropdown(
            choices=["cohere", "siliconflow", ("default/offline", "None")],
            value=llm_settings.reranker_type or "None",
            label="Provider",
        )

        @gr.render(inputs=[reranker_dropdown])
        def reranker_settings(provider):
            inputs = [
                gr.Textbox(interactive=True, value="", label="API key", type="password"),
                gr.Textbox(
                    interactive=True,
                    value=llm_settings.reranker_model
                    or ("BAAI/bge-reranker-v2-m3" if provider == "siliconflow" else ""),
                    label="model",
                ),
                gr.Textbox(
                    interactive=True, value=llm_settings.cohere_base_url, label="API base", visible=provider == "cohere"
                ),
            ]
            clear = gr.Checkbox(label="Clear API key", value=False)
            gr.Button("Save configuration").click(
                lambda key, model, base, clear_key: apply_reranker_config(
                    key, model, base, clear_api_key=clear_key, provider=provider
                ),
                inputs=[*inputs, clear],
            )
            gr.Button("Test saved connection").click(partial(test_model_form, "reranker"))

    with gr.Accordion("5. Set up the vector engine.", open=False):
        engine_selector = gr.Dropdown(
            choices=["Faiss", "Milvus", "Qdrant"],
            value=index_settings.cur_vector_index,
            label="Select vector engine.",
        )
        engine_selector.select(
            fn=apply_vector_engine,
            inputs=[engine_selector],
        )

        @gr.render(inputs=[engine_selector])
        def vector_engine_settings(engine):
            if engine == "Milvus":
                with gr.Row():
                    milvus_inputs = [
                        gr.Textbox(
                            interactive=True,
                            value=index_settings.milvus_host,
                            label="host",
                        ),
                        gr.Textbox(
                            interactive=True,
                            value=str(index_settings.milvus_port),
                            label="port",
                        ),
                        gr.Textbox(
                            interactive=True,
                            value=index_settings.milvus_user,
                            label="user",
                        ),
                        gr.Textbox(
                            interactive=True,
                            value=index_settings.milvus_password,
                            label="password",
                            type="password",
                        ),
                    ]
                apply_backend_button = gr.Button("Apply Configuration")
                apply_backend_button.click(partial(apply_vector_engine_backend, "Milvus"), inputs=milvus_inputs)
            elif engine == "Qdrant":
                with gr.Row():
                    qdrant_inputs = [
                        gr.Textbox(
                            interactive=True,
                            value=index_settings.qdrant_host,
                            label="host",
                        ),
                        gr.Textbox(
                            interactive=True,
                            value=str(index_settings.qdrant_port),
                            label="port",
                        ),
                        gr.Textbox(
                            interactive=True,
                            value=(index_settings.qdrant_api_key or ""),
                            label="api_key",
                            type="password",
                        ),
                    ]
                apply_backend_button = gr.Button("Apply Configuration")
                apply_backend_button.click(
                    lambda h, p, k: apply_vector_engine_backend("Qdrant", h, p, None, None, k),
                    inputs=qdrant_inputs,
                )
            else:
                gr.Markdown("✅ Faiss 本地索引无需额外配置。")
                apply_faiss_button = gr.Button("Apply Configuration")
                apply_faiss_button.click(lambda: apply_vector_engine(engine))

    # The reason for returning this partial value is the functional need to refresh the ui
    return graph_config_input


def get_header_with_language_indicator(language: str) -> str:
    language_class = language.lower()

    if language == "CN":
        title_text = "当前prompt语言: 中文 (CN)"
    else:
        title_text = "Current prompt Language: English (EN)"
    html_content = f"""
    <div class="header-container">
        <h1 class="header-title">HugeGraph RAG Platform 🚀</h1>
        <div class="language-indicator-container">
            <div class="language-indicator {language_class}">
                {language}
            </div>
            <div class="custom-tooltip">
                {title_text}
            </div>
        </div>
    </div>
    """
    return html_content
