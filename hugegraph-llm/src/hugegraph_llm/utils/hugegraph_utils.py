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
import shutil
import stat
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

import requests
from pyhugegraph.client import PyHugeClient
from requests.auth import HTTPBasicAuth

from hugegraph_llm.config import huge_settings, resource_path
from hugegraph_llm.utils.log import log

MAX_BACKUP_DIRS = 7
MAX_VERTICES = 100000
MAX_EDGES = 200000
BACKUP_DIR = str(os.path.join(resource_path, "backup-graph-data-4020", huge_settings.graph_name))


def run_gremlin_query(query, fmt=True, connection=None):
    res = get_hg_client(connection=connection).gremlin().exec(query)
    return json.dumps(res, indent=4, ensure_ascii=False) if fmt else res


def get_hg_client(connection=None):
    if connection is None:
        connection = {
            "url": huge_settings.graph_url,
            "graph": huge_settings.graph_name,
            "user": huge_settings.graph_user,
            "pwd": huge_settings.graph_pwd,
            "graphspace": huge_settings.graph_space,
        }
    configured = _normalize_graph_url(huge_settings.graph_url)
    requested = _normalize_graph_url(connection["url"])
    if requested != configured:
        raise ValueError("Request graph URL must match the configured HugeGraph URL")
    return PyHugeClient(
        url=requested,
        graph=connection["graph"],
        user=connection["user"],
        pwd=connection["pwd"],
        graphspace=connection["graphspace"],
    )


def _normalize_graph_url(url):
    raw_url = str(url).strip()
    if "://" not in raw_url:
        raw_url = f"http://{raw_url}"
    try:
        parsed = urlsplit(raw_url)
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("not an absolute HTTP(S) URL")
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            raise ValueError("missing hostname")
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Graph URL must be a valid HTTP(S) URL") from exc
    default_port = 80 if parsed.scheme.lower() == "http" else 443
    authority = f"[{hostname}]" if ":" in hostname else hostname
    if port is not None and port != default_port:
        authority += f":{port}"
    return f"{parsed.scheme.lower()}://{authority}{parsed.path.rstrip('/')}"


def init_hg_test_data():
    client = get_hg_client()
    client.graphs().clear_graph_all_data()
    schema = client.schema()
    schema.property_key("name").as_text().if_not_exist().create()
    schema.property_key("birthDate").as_text().if_not_exist().create()
    schema.vertex_label("Person").properties("name", "birthDate").use_customize_string_id().if_not_exist().create()
    schema.vertex_label("Movie").properties("name").use_customize_string_id().if_not_exist().create()
    schema.edge_label("ActedIn").source_label("Person").target_label("Movie").if_not_exist().create()

    schema.index_label("PersonByName").on_v("Person").by("name").secondary().if_not_exist().create()
    schema.index_label("MovieByName").on_v("Movie").by("name").secondary().if_not_exist().create()

    graph = client.graph()
    graph.add_vertex("Person", {"name": "Al Pacino", "birthDate": "1940-04-25"}, id="Al Pacino")
    graph.add_vertex(
        "Person",
        {"name": "Robert De Niro", "birthDate": "1943-08-17"},
        id="Robert De Niro",
    )
    graph.add_vertex("Movie", {"name": "The Godfather"}, id="The Godfather")
    graph.add_vertex("Movie", {"name": "The Godfather Part II"}, id="The Godfather Part II")
    graph.add_vertex(
        "Movie",
        {"name": "The Godfather Coda The Death of Michael Corleone"},
        id="The Godfather Coda The Death of Michael Corleone",
    )

    graph.add_edge("ActedIn", "Al Pacino", "The Godfather", {})
    graph.add_edge("ActedIn", "Al Pacino", "The Godfather Part II", {})
    graph.add_edge("ActedIn", "Al Pacino", "The Godfather Coda The Death of Michael Corleone", {})
    graph.add_edge("ActedIn", "Robert De Niro", "The Godfather Part II", {})
    schema.get_schema()
    client.close()
    return {
        "vertex": ["Person", "Movie"],
        "edge": ["ActedIn"],
        "property": ["name", "birthDate"],
        "index": ["PersonByName", "MovieByName"],
    }


def clean_hg_data():
    client = get_hg_client()
    client.graphs().clear_graph_all_data()


def create_dir_safely(path):
    if not os.path.exists(path):
        os.makedirs(path)


def backup_data():
    try:
        client = get_hg_client()
        create_dir_safely(BACKUP_DIR)

        date_str = datetime.now().strftime("%Y%m%d")
        backup_subdir = os.path.join(BACKUP_DIR, f"{date_str}")
        create_dir_safely(backup_subdir)

        schema = client.schema().get_schema()
        files = {
            "vertices.json": f"g.V().limit({MAX_VERTICES})"
            f".aggregate('vertices').count().as('count').select('count','vertices')",
            "edges.json": f"g.E().limit({MAX_EDGES}).aggregate('edges').count().as('count').select('count','edges')",
            "schema.json": schema,
        }

        vertexlabels = schema["vertexlabels"]
        all_pk_flag = all(data.get("id_strategy") == "PRIMARY_KEY" for data in vertexlabels)

        for filename, query in files.items():
            write_backup_file(client, backup_subdir, filename, query, all_pk_flag)

        log.info("Backup successfully in %s.", backup_subdir)
        relative_backup_subdir = os.path.relpath(backup_subdir, start=resource_path)
        del_info = manage_backup_retention()
        return f"Backup successfully in '{relative_backup_subdir}' \n{del_info}"
    except Exception as e:  # pylint: disable=W0718
        log.critical("Backup failed: %s", e, exc_info=True)
        raise Exception("Failed to execute backup") from e


def write_backup_file(client, backup_subdir, filename, query, all_pk_flag):
    if filename == "edges.json":
        data = client.gremlin().exec(query)["data"][0]["edges"]
    elif filename == "vertices.json":
        vertices = client.gremlin().exec(query)["data"][0]["vertices"]
        data = (
            [{key: value for key, value in vertex.items() if key != "id"} for vertex in vertices]
            if all_pk_flag
            else vertices
        )
    elif filename == "schema.json":
        data = query
    else:
        raise ValueError(f"Unsupported backup file: {filename}")

    target = Path(backup_subdir) / filename
    target_mode = stat.S_IMODE(target.stat().st_mode) if target.exists() else None
    with TemporaryDirectory(dir=backup_subdir, prefix=f".{filename}.") as directory:
        temporary = Path(directory) / filename
        # Exclusive creation lets the kernel apply umask without changing it.
        with open(temporary, "x", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        if target_mode is not None:
            temporary.chmod(target_mode)
        os.replace(temporary, target)

    if filename == "schema.json":
        stale_schema = Path(backup_subdir) / "schema.groovy"
        if stale_schema.is_file():
            stale_schema.unlink()


def manage_backup_retention():
    try:
        backup_dirs = [
            os.path.join(BACKUP_DIR, d) for d in os.listdir(BACKUP_DIR) if os.path.isdir(os.path.join(BACKUP_DIR, d))
        ]
        backup_dirs.sort(key=os.path.getctime)
        if len(backup_dirs) > MAX_BACKUP_DIRS:
            old_backup = backup_dirs.pop(0)
            shutil.rmtree(old_backup)
            log.info("Deleted old backup: %s", old_backup)
            relative_old_backup = os.path.relpath(old_backup, start=resource_path)
            return f"Deleted old backup: {relative_old_backup}"
        return f"The current number of backup files <= {MAX_BACKUP_DIRS}, so no files are deleted"
    except Exception as e:  # pylint: disable=W0718
        log.error("Failed to manage backup retention: %s", e, exc_info=True)
        raise Exception("Failed to manage backup retention") from e


# TODO: In the path demo/rag_demo/configs_block.py,
# there is a function test_api_connection that is similar to this function,
# but it is not straightforward to reuse
def check_graph_db_connection(url: str, name: str, user: str, pwd: str, graph_space: str) -> bool:
    try:
        if graph_space and graph_space.strip():
            test_url = f"{url}/graphspaces/{graph_space}/graphs/{name}/schema"
        else:
            test_url = f"{url}/graphs/{name}/schema"
        auth = HTTPBasicAuth(user, pwd)
        response = requests.get(test_url, timeout=(1.0, 5.0), auth=auth)
        return response.status_code == 200
    except (requests.exceptions.RequestException, requests.exceptions.Timeout) as e:
        log.warning("GraphDB connection error: %s", str(e))
        return False
    except Exception as e:
        log.error("Unexpected connection error: %s", e, exc_info=True)
        raise Exception("Failed to execute update_vid_embedding") from e
