# Copyright 2026 Apache HugeGraph Authors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Deployment artifact integrity (static checks).

The docker daemon is not available in CI here, so these verify the things that
actually break deployments when code moves: referenced paths, compose parsing,
env/volume coherence, and the exact CLI flags used by the image CMD.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from ontogeny.cli import app as cli_app

REPO = Path(__file__).resolve().parent.parent
COMPOSE = REPO / "compose.yaml"
DOCKERFILE = REPO / "deploy" / "Dockerfile"
DOCKERIGNORE = REPO / ".dockerignore"


@pytest.fixture(scope="module")
def compose() -> dict:
    assert COMPOSE.is_file(), "compose.yaml missing"
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def dockerfile() -> str:
    assert DOCKERFILE.is_file(), "deploy/Dockerfile missing"
    return DOCKERFILE.read_text(encoding="utf-8")


class TestCompose:
    def test_default_service_is_the_app(self, compose):
        ontogeny = compose["services"]["ontogeny"]
        assert ontogeny["build"]["context"] == "."
        assert (REPO / ontogeny["build"]["dockerfile"]).is_file()
        assert any(":8000" in p for p in ontogeny["ports"])

    def test_data_volume_matches_dsn_and_demo_dir(self, compose):
        ontogeny = compose["services"]["ontogeny"]
        assert "ontogeny-data:/data" in ontogeny["volumes"]
        # the default DSN and the demo data dir both live under /data
        assert "/data/ontogeny.db" in ontogeny["environment"]["ONTOGENY_DB_DSN"]
        assert "ontogeny-data" in compose["volumes"]

    def test_llm_is_opt_in_but_wired(self, compose):
        env = compose["services"]["ontogeny"]["environment"]
        assert "ONTOGENY_LLM_BASE_URL" in env and "ONTOGENY_LLM_MODEL" in env

    def test_optional_profiles_are_declared_and_referenced(self, compose):
        # service name -> profile name (they differ for the graph profile)
        for service, profile in (("postgres", "postgres"), ("hugegraph", "graph")):
            assert service in compose["services"], service
            assert compose["services"][service]["profiles"] == [profile]
        assert "ontogeny-pg" in compose["volumes"] and "ontogeny-graph" in compose["volumes"]

    def test_postgres_profile_dsn_hint_is_overridable(self, compose):
        # ONTOGENY_DB_DSN must be env-overridable so the postgres profile can swap it
        assert "${ONTOGENY_DB_DSN:" in compose["services"]["ontogeny"]["environment"]["ONTOGENY_DB_DSN"]


class TestDockerfile:
    def test_build_context_paths_exist(self, dockerfile):
        copies = re.findall(r"^COPY\s+(.+)$", dockerfile, flags=re.MULTILINE)
        assert copies, "no COPY instructions found"
        for line in copies:
            parts = line.split()
            src = parts[0]
            if src.startswith("--from"):
                continue  # cross-stage copy
            assert (REPO / src).exists(), f"Dockerfile COPY references missing path: {src}"

    def test_builds_ui_and_serves_it_same_origin(self, dockerfile):
        assert "npm ci" in dockerfile and "npm run build" in dockerfile
        assert "COPY --from=ui /ui/dist ./web/dist" in dockerfile
        assert "ONTOGENY_UI_DIR=/app/web/dist" in dockerfile

    def test_runs_demo_bootstrap_on_the_volume(self, dockerfile):
        cmd = re.search(r'^CMD \[(.+)\]$', dockerfile, flags=re.MULTILINE)
        assert cmd, "no CMD found"
        cmd_text = cmd.group(1)
        assert "--demo" in cmd_text
        assert "--data-dir" in cmd_text and "/data" in cmd_text
        # the UI is prebuilt in the image; never shell out to npm at runtime
        assert "--no-build-ui" in cmd_text

    def test_non_root_and_healthcheck(self, dockerfile):
        assert "USER ontogeny" in dockerfile
        assert "HEALTHCHECK" in dockerfile
        m = re.search(r"urlopen\('(http://[^']+)'", dockerfile)
        assert m, "healthcheck must probe a concrete URL"

    def test_healthcheck_endpoint_exists_in_the_app(self, dockerfile):
        from ontogeny.api import build_app
        from ontogeny.config import Settings
        from ontogeny.service import ServiceContext

        m = re.search(r"urlopen\('http://[^/]+(/[^']*)'", dockerfile)
        assert m
        probed = m.group(1)
        sc = ServiceContext(Settings(), None)

        def walk(routes):
            for route in routes:
                yield getattr(route, "path", None)
                inner = getattr(route, "original_router", None)  # nested include_router
                if inner is not None:
                    yield from walk(getattr(inner, "routes", []))
                for sub in getattr(route, "routes", []) or []:
                    yield from walk([sub])

        paths = {p for p in walk(build_app(sc).routes) if p}
        assert probed in paths, f"healthcheck probes {probed}, which the API does not serve"


class TestDockerignore:
    def test_excludes_build_noise(self):
        text = DOCKERIGNORE.read_text(encoding="utf-8")
        for pattern in (".venv", "web/node_modules", "web/dist", "__pycache__"):
            assert pattern in text

    def test_keeps_sources_the_image_needs(self):
        text = DOCKERIGNORE.read_text(encoding="utf-8")
        for needed in ("server/", "web/package.json", "pyproject.toml", "domains/"):
            assert needed not in text, f"{needed} must be included in the build context"


class TestImageCmdFlags:
    """The CMD must be accepted by the real CLI (catches flag renames)."""

    def test_serve_accepts_every_cmd_flag(self):
        # Introspect the click params instead of the rendered `--help` text:
        # the help output is rich-wrapped (width/ANSI depend on the runner's
        # environment) and gave a false negative on CI while the command
        # itself accepted every flag. Param introspection is what "accepts"
        # actually means, and it is rendering-independent.
        from typer.main import get_command

        serve = get_command(cli_app).commands["serve"]
        names: set[str] = set()
        for p in serve.params:
            names.update(getattr(p, "opts", None) or [])
            names.update(getattr(p, "secondary_opts", None) or [])
        for flag in ("--demo", "--data-dir", "--no-build-ui", "--host", "--port"):
            assert flag in names, f"ontogeny serve no longer accepts {flag}"

    def test_demo_related_commands_exist(self):
        result = CliRunner().invoke(cli_app, ["--help"])
        assert result.exit_code == 0
        for cmd in ("serve", "sync", "publish", "validate", "evolve", "projection"):
            assert cmd in result.output, f"ontogeny lost the {cmd} command"
