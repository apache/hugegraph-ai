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
"""Runtime configuration (env-driven, 12-factor).

DSL files reference secrets via ``${VAR}``; those are resolved here at runtime
and never persisted. The process itself is configured by the same mechanism.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_DB_DSN = "sqlite+aiosqlite:///./ontogeny.db"


@dataclass(frozen=True)
class Settings:
    db_dsn: str = DEFAULT_DB_DSN
    # Off by default: the X-Ontogeny-Principal dev header is a full identity
    # simulation (it may even claim is_admin/markings), so it must be an
    # explicit opt-in for CI/demo (ONTOGENY_DEV_AUTH=1), never a silent default.
    dev_auth: bool = False
    webhook_allowlist: tuple[str, ...] = field(default_factory=tuple)  # empty = deny all
    # HugeGraph credentials. A graph server in auth mode refuses anonymous access
    # AND is the only kind of 1.7 server that lets the platform create a graph,
    # so a deployment either has these or provisions graphs by hand.
    hugegraph_user: str | None = None
    hugegraph_password: str | None = None
    # Directory a platform-CREATED graph keeps its RocksDB files under. Left
    # unset, the server's own default applies, which is one shared directory for
    # every dynamically created graph -- see HugeGraphClient.ensure_graph.
    hugegraph_data_dir: str | None = None
    # Deployment-wide host allowlist for declarative functions' http steps. When
    # set, a step must satisfy BOTH this and its own capability's allow list; a
    # function can only ever narrow what the deployment permits, never widen it.
    function_http_allowlist: tuple[str, ...] = field(default_factory=tuple)
    llm_provider: str = "ollama"  # ollama | external | disabled
    llm_base_url: str | None = None  # Ollama / OpenAI-compatible endpoint
    llm_model: str | None = None
    llm_api_key: str | None = None  # external OpenAI-compatible APIs only
    # Wall clock one ``ontogeny.llm`` round trip may take inside a sandboxed function.
    # A function declaring the llm capability gets this much extra time per
    # declared call, on top of the sandbox's local-work budget.
    llm_call_timeout_s: float = 60.0
    storage_provider: str = "sqlite"  # hugegraph | sqlite
    extensions_dir: str | None = None  # colon-separated; default <repo>/extensions
    log_level: str = "INFO"
    env: dict[str, str] = field(default_factory=dict)  # resolution scope for ${VAR}

    def resolve_env_ref(self, value: str) -> str:
        """Resolve ``${VAR}`` references against process env + explicit scope."""
        import re

        def sub(m: "re.Match[str]") -> str:
            name = m.group(1)
            if name in self.env:
                return self.env[name]
            if name in os.environ:
                return os.environ[name]
            raise KeyError(f"environment variable {name!r} referenced by DSL is not set")

        return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", sub, value)


def load_settings(**overrides: str | bool) -> Settings:
    return Settings(
        db_dsn=overrides.get("db_dsn", os.environ.get("ONTOGENY_DB_DSN", DEFAULT_DB_DSN)),
        dev_auth=bool(overrides.get("dev_auth", os.environ.get("ONTOGENY_DEV_AUTH", "0") == "1")),
        webhook_allowlist=tuple(
            s.strip()
            for s in overrides.get(
                "webhook_allowlist", os.environ.get("ONTOGENY_WEBHOOK_ALLOWLIST", "")
            ).split(",")
            if s.strip()
        ),
        llm_provider=overrides.get("llm_provider", os.environ.get("ONTOGENY_LLM_PROVIDER", "ollama")) or "ollama",
        llm_base_url=overrides.get("llm_base_url", os.environ.get("ONTOGENY_LLM_BASE_URL")) or None,
        llm_model=overrides.get("llm_model", os.environ.get("ONTOGENY_LLM_MODEL")) or None,
        llm_api_key=overrides.get("llm_api_key", os.environ.get("ONTOGENY_LLM_API_KEY")) or None,
        hugegraph_user=overrides.get("hugegraph_user", os.environ.get("HUGEGRAPH_USER")) or None,
        hugegraph_password=overrides.get("hugegraph_password", os.environ.get("HUGEGRAPH_PASSWORD")) or None,
        hugegraph_data_dir=overrides.get("hugegraph_data_dir", os.environ.get("HUGEGRAPH_DATA_DIR")) or None,
        function_http_allowlist=tuple(
            s.strip()
            for s in overrides.get(
                "function_http_allowlist", os.environ.get("ONTOGENY_FUNCTION_HTTP_ALLOWLIST", "")
            ).split(",")
            if s.strip()
        ),
        llm_call_timeout_s=float(
            overrides.get("llm_call_timeout_s", os.environ.get("ONTOGENY_LLM_CALL_TIMEOUT_S", 60.0))
        ),
        storage_provider=overrides.get(
            "storage_provider",
            os.environ.get("ONTOGENY_STORAGE_PROVIDER")
            or ("hugegraph" if os.environ.get("HUGEGRAPH_URL") else "sqlite"),
        ) or "sqlite",
        extensions_dir=overrides.get("extensions_dir", os.environ.get("ONTOGENY_EXTENSIONS_DIR")) or None,
        log_level=overrides.get("log_level", os.environ.get("ONTOGENY_LOG_LEVEL", "INFO")),
    )
