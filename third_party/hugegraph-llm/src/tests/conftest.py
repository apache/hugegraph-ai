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

import logging
import os
import sys
from contextlib import suppress

import nltk
import pytest

# Get project root directory
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.insert(0, project_root)
# Add src directory to Python path
src_path = os.path.join(project_root, "src")
sys.path.insert(0, src_path)

from tests.fixtures.hugegraph_service import hugegraph_service  # noqa: E402

__all__ = ["hugegraph_client", "hugegraph_service"]


def _clear_quality_schema(client):
    schema = client.schema()
    for remove in (
        lambda: schema.edgeLabel("quality_created").remove(),
        lambda: schema.vertexLabel("quality_software").remove(),
        lambda: schema.vertexLabel("quality_person").remove(),
    ):
        with suppress(Exception):
            remove()


@pytest.fixture()
def hugegraph_client(hugegraph_service):
    from pyhugegraph.client import PyHugeClient

    from hugegraph_llm.config import huge_settings

    original = {
        "graph_url": huge_settings.graph_url,
        "graph_name": huge_settings.graph_name,
        "graph_user": huge_settings.graph_user,
        "graph_pwd": huge_settings.graph_pwd,
        "graph_space": huge_settings.graph_space,
    }
    huge_settings.graph_url = hugegraph_service.url
    huge_settings.graph_name = hugegraph_service.graph
    huge_settings.graph_user = hugegraph_service.user
    huge_settings.graph_pwd = hugegraph_service.password
    huge_settings.graph_space = hugegraph_service.graphspace

    client = PyHugeClient(
        url=hugegraph_service.url,
        graph=hugegraph_service.graph,
        user=hugegraph_service.user,
        pwd=hugegraph_service.password,
        graphspace=hugegraph_service.graphspace,
    )
    client.graphs().clear_graph_all_data()
    _clear_quality_schema(client)
    try:
        yield client
    finally:
        try:
            client.graphs().clear_graph_all_data()
            _clear_quality_schema(client)
        finally:
            for key, value in original.items():
                setattr(huge_settings, key, value)


# Download NLTK resources
def download_nltk_resources():
    try:
        nltk.data.find("corpora/stopwords")
    except LookupError:
        logging.info("Downloading NLTK stopwords resource...")
        nltk.download("stopwords", quiet=True)


# Download NLTK resources before tests start
download_nltk_resources()
# Default local tests away from external services while allowing selected
# integration runs to opt in explicitly.
os.environ.setdefault("SKIP_EXTERNAL_SERVICES", "true")
# Log current Python path for debugging
logging.debug("Python path: %s", sys.path)
