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

import asyncio
from collections import deque

import gradio as gr

from hugegraph_llm.api.admin_api import _is_configured_admin_token
from hugegraph_llm.config import admin_settings
from hugegraph_llm.utils.log import log


async def log_stream(log_path: str, lines: int = 125):
    """
    Stream the content of a log file like `tail -f`.
    """
    try:
        with open(log_path, "r", encoding="utf-8") as file:
            buffer = deque(file, maxlen=lines)
            for line in buffer:
                yield line  # Yield the initial lines
            while True:
                line = file.readline()
                if line:
                    yield line
                else:
                    await asyncio.sleep(0.1)  # Non-blocking sleep
    except FileNotFoundError as exc:
        raise Exception(f"Log file not found: {log_path}") from exc
    except Exception as e:
        raise Exception(f"An error occurred while reading the log: {str(e)}") from e


# Functions to read each log file
def read_llm_server_log(lines=250):
    log_path = "logs/llm-server.log"
    try:
        with open(log_path, "r", encoding="utf-8", errors="replace") as f:
            return "".join(deque(f, maxlen=lines))
    except FileNotFoundError:
        log.critical("Log file not found: %s", log_path)
        return "LLM Server log file not found."


# Functions to clear each log file
def clear_llm_server_log():
    log_path = "logs/llm-server.log"
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.truncate(0)  # Clear the contents of the file
        return "LLM Server log cleared."
    except Exception as e:  # pylint: disable=W0718
        log.error("An error occurred while clearing the log: %s", str(e))
        return "Failed to clear LLM Server log."


# Function to validate password and control access to logs
def check_password(password, request: gr.Request | None = None):
    client_ip = request.client.host if request else "Unknown IP"
    admin_token = admin_settings.admin_token

    if not _is_configured_admin_token(admin_token):
        log.error("Rejected admin log access with insecure token from IP: %s", client_ip)
        return (
            "",
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(value="Admin token is not configured securely.", visible=True),
        )

    if password == admin_token:
        # Return logs and update visibility
        llm_log = read_llm_server_log()
        # Log the successful access with the IP address
        log.info("Logs accessed successfully from IP: %s", client_ip)
        return (
            llm_log,
            gr.update(visible=True),
            gr.update(visible=True),
            gr.update(visible=True),
            gr.update(visible=False),
        )
    # Log the failed attempt with IP address
    log.error("Incorrect password attempt from IP: %s", client_ip)
    return (
        "",
        gr.update(visible=False),
        gr.update(visible=False),
        gr.update(visible=False),
        gr.update(value="Incorrect password. Access denied.", visible=True),
    )


def create_admin_block():
    with gr.Blocks():
        gr.Markdown("## Admin Info - Password Protected")

        # Password input
        password_input = gr.Textbox(
            label="Enter Password",
            type="password",
            placeholder="Enter password to access admin information",
        )

        # Error message box, initially hidden
        error_message = gr.Textbox(label="", visible=False, interactive=False, elem_classes="error-message")

        # Button to submit password
        submit_button = gr.Button("Submit")

        with gr.Row(visible=False) as hidden_row:
            with gr.Column():
                # LLM Server log display, refreshes every 1 second
                gr.Markdown("### LLM Server Log")
                llm_server_log_output = gr.Code(
                    label="LLM Server Log (llm-server.log)",
                    lines=20,
                    value="",
                    elem_classes="code-container-edit",
                    every=60,  # Refresh every 60 second
                )
                with gr.Row():
                    with gr.Column():
                        # Button to clear LLM Server log, initially hidden
                        clear_llm_server_button = gr.Button("Clear LLM Server Log", visible=False)
                    with gr.Column():
                        # Button to refresh LLM Server log manually
                        refresh_llm_server_button = gr.Button(
                            "Refresh LLM Server Log", visible=False, variant="primary"
                        )

        # Define what happens when the password is submitted
        submit_button.click(  # pylint: disable=E1101
            fn=check_password,
            inputs=[password_input],
            outputs=[
                llm_server_log_output,
                hidden_row,
                clear_llm_server_button,
                refresh_llm_server_button,
                error_message,
            ],
        )

        # Define what happens when the Clear LLM Server Log button is clicked
        clear_llm_server_button.click(  # pylint: disable=E1101
            fn=clear_llm_server_log,
            inputs=[],
            outputs=[llm_server_log_output],
        )

        # Define what happens when the Refresh LLM Server Log button is clicked
        refresh_llm_server_button.click(  # pylint: disable=E1101
            fn=read_llm_server_log,
            inputs=[],
            outputs=[llm_server_log_output],
        )
