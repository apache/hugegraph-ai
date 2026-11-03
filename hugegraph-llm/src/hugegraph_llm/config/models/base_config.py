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


import os
import tempfile
from pathlib import Path
from typing import ClassVar, get_args

from dotenv import set_key
from pydantic import AliasChoices, PrivateAttr
from pydantic_settings import BaseSettings, SettingsConfigDict

from hugegraph_llm.utils.log import log

ENV_PATH_ENV_VAR = "HUGEGRAPH_LLM_ENV_PATH"


def _source_project_root() -> Path | None:
    package_root = Path(__file__).resolve().parents[2]
    if package_root.parent.name != "src":
        return None
    project_root = package_root.parent.parent
    return project_root if (project_root / "pyproject.toml").exists() else None


def resolve_env_path() -> str:
    explicit = os.getenv(ENV_PATH_ENV_VAR)
    if explicit is not None:
        if not explicit.strip():
            raise ValueError(f"{ENV_PATH_ENV_VAR} must not be empty")
        return str(Path(explicit).expanduser())
    if resources := os.getenv("HUGEGRAPH_LLM_RESOURCE_PATH"):
        return str(Path(resources).expanduser() / ".env")
    return str((_source_project_root() or Path.cwd()) / ".env")


env_path = resolve_env_path()


class BaseConfig(BaseSettings):
    """Read configuration without mutating the environment or mounted files.

    Pydantic resolves explicit constructor values, process env, dotenv, defaults
    in that order. UI saves persist only changed fields, never env-owned fields.
    """

    model_config = SettingsConfigDict(
        env_file=env_path,
        case_sensitive=False,
        extra="ignore",
        env_ignore_empty=False,
        populate_by_name=True,
    )
    _saved_values: dict = PrivateAttr(default_factory=dict)
    allow_empty_environment: ClassVar[frozenset[str]] = frozenset()

    @classmethod
    def _allows_empty(cls, field: str, process: bool) -> bool:
        annotation = cls.model_fields[field].annotation
        optional_string = str in get_args(annotation)
        return optional_string or (not process and annotation is str) or field in cls.allow_empty_environment

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        def normalize(source, process):
            values = source()
            for field, definition in cls.model_fields.items():
                if cls._allows_empty(field, process):
                    continue
                alias = definition.validation_alias
                names = alias.choices if isinstance(alias, AliasChoices) else [alias or field]
                for name in [field, *names]:
                    if isinstance(name, str) and values.get(name) == "":
                        values.pop(name)
            return values

        return (
            init_settings,
            lambda: normalize(env_settings, True),
            lambda: normalize(dotenv_settings, False),
            file_secret_settings,
        )

    @classmethod
    def environment_source(cls, field: str) -> str | None:
        alias = cls.model_fields[field].validation_alias
        names = alias.choices if isinstance(alias, AliasChoices) else [alias or field]
        environment = {name.upper(): name for name in os.environ}
        for name in names:
            if isinstance(name, str) and (source := environment.get(name.upper())):
                if os.environ[source] or cls._allows_empty(field, True):
                    return source
        return None

    def __init__(self, **data):
        try:
            data.setdefault("_env_file", env_path)
            super().__init__(**data)
            self._saved_values = self.model_dump()
        except Exception as exc:
            log.error("Failed to initialize %s from %s (%s)", type(self).__name__, env_path, type(exc).__name__)
            raise

    def update_env(self):
        current = self.model_dump()
        changed = {
            key: value
            for key, value in current.items()
            if key not in self._saved_values or value != self._saved_values[key]
        }
        managed = [field for field in changed if self.environment_source(field)]
        if managed:
            raise ValueError("Configuration managed by environment: " + ", ".join(managed))
        if not changed:
            return
        target = Path(env_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Stage all changes together. Failed writes leave the original intact;
        # restrictive permissions also apply when the file contains UI secrets.
        fd, staging = tempfile.mkstemp(prefix=".env-", dir=target.parent)
        os.close(fd)
        try:
            if target.exists():
                Path(staging).write_bytes(target.read_bytes())
            for field, value in changed.items():
                log.info("Update configuration field %s in %s", field.upper(), env_path)
                text = "" if value is None else str(value)
                needs_quotes = (
                    text != text.strip() or any(c in text for c in ("\n", "\r", " #")) or text.startswith(("'", '"'))
                )
                set_key(staging, field.upper(), text, quote_mode="always" if needs_quotes else "never")
            if target.exists():
                os.chmod(staging, target.stat().st_mode & 0o777)
            os.replace(staging, target)
        finally:
            Path(staging).unlink(missing_ok=True)
        self._saved_values = current

    def check_env(self):
        """Explicitly reload validated settings; startup never writes defaults."""
        try:
            loaded = type(self)()
            for field, value in loaded.model_dump().items():
                setattr(self, field, value)
            self._saved_values = self.model_dump()
        except Exception as exc:
            log.error("Failed to reload configuration file %s (%s)", env_path, type(exc).__name__)
            raise

    def generate_env(self):
        """Explicit CLI export; do not export credentials supplied by env."""
        if Path(env_path).exists() and input(f"Replace configuration in {env_path}? (y/n) ").lower() != "y":
            return
        self._saved_values = {key: value for key, value in self.model_dump().items() if self.environment_source(key)}
        self.update_env()
