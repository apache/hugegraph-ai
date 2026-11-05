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


import errno
import os
import tempfile
import threading
from pathlib import Path
from typing import ClassVar

import yaml
from dotenv import dotenv_values
from pydantic import AliasChoices, PrivateAttr
from pydantic_settings import BaseSettings, SettingsConfigDict

ENV_PATH_ENV_VAR = "HUGEGRAPH_LLM_ENV_PATH"
_settings_lock = threading.RLock()


def resolve_env_path() -> str:
    explicit = os.getenv(ENV_PATH_ENV_VAR)
    if explicit is not None:
        if not explicit.strip():
            raise ValueError(f"{ENV_PATH_ENV_VAR} must not be empty")
        return str(Path(explicit).expanduser())
    if resources := os.getenv("HUGEGRAPH_LLM_RESOURCE_PATH"):
        return str(Path(resources).expanduser() / ".env")
    package = Path(__file__).resolve().parents[2]
    project = package.parent.parent
    return str(
        (project if package.parent.name == "src" and (project / "pyproject.toml").exists() else Path.cwd()) / ".env"
    )


env_path = resolve_env_path()


def settings_path() -> Path:
    explicit = os.getenv("HUGEGRAPH_LLM_SETTINGS_PATH")
    if explicit is not None:
        if not explicit.strip():
            raise ValueError("HUGEGRAPH_LLM_SETTINGS_PATH must not be empty")
        return Path(explicit).expanduser()
    root = os.getenv("HUGEGRAPH_LLM_RESOURCE_PATH")
    return (Path(root).expanduser() if root else Path(env_path).parent) / "settings.yaml"


def _read_settings() -> dict:
    with _settings_lock:
        path = settings_path()
        if not path.exists():
            return {}
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
        if value is None:
            return {}
        if not isinstance(value, dict):
            raise ValueError("settings.yaml must contain a mapping")
        return value


def _write_file(target: Path, text: str):
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".settings-", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(text)
        if target.exists():
            os.chmod(temporary, target.stat().st_mode & 0o777)
        try:
            os.replace(temporary, target)
        except OSError as exc:
            if exc.errno != errno.EBUSY or not target.exists():
                raise
            target.write_text(text, encoding="utf-8")
    finally:
        Path(temporary).unlink(missing_ok=True)


def _quote_dotenv(value) -> str:
    """Quote one value using the syntax parsed by python-dotenv."""
    escaped = str(value).replace("\\", "\\\\").replace("'", "\\'")
    return f"'{escaped}'"


class BaseConfig(BaseSettings):
    """Load deployment defaults and explicit saved connections without startup writes.

    Constructor values win, followed by saved application settings, process env,
    dotenv and defaults. A connection comes wholly from one source: its key can
    never be silently combined with a lower-priority destination.
    """

    model_config = SettingsConfigDict(
        env_file=env_path,
        case_sensitive=False,
        extra="ignore",
        env_ignore_empty=False,
        populate_by_name=True,
    )
    _saved_values: dict = PrivateAttr(default_factory=dict)
    section: ClassVar[str] = ""
    connection_groups: ClassVar[dict[str, tuple[str, ...]]] = {}
    allow_empty_environment: ClassVar[frozenset[str]] = frozenset()

    @classmethod
    def _source_names(cls, field):
        alias = cls.model_fields[field].validation_alias
        names = alias.choices if isinstance(alias, AliasChoices) else [alias or field]
        return tuple(dict.fromkeys([*names, field]))

    @classmethod
    def _canonical(cls, source):
        raw = source()
        result = {}
        for field in cls.model_fields:
            for name in cls._source_names(field):
                if name in raw:
                    result[field] = raw[name]
                    break
        return result

    @classmethod
    def _saved_source(cls):
        if not cls.section:
            return {}
        section = _read_settings().get(cls.section or cls.__name__, {})
        if not isinstance(section, dict) or any(not isinstance(v, dict) for v in section.values()):
            raise ValueError("Invalid saved configuration section")
        values = {}
        for name, group in section.items():
            allowed = (
                set(cls.connection_groups.get(name, ()))
                if name != "options"
                else set(cls.model_fields) - {f for fields in cls.connection_groups.values() for f in fields}
            )
            if set(group) - allowed:
                raise ValueError("Unknown field in saved configuration")
            values.update(group)
        return values

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        # Filter process placeholders before AliasChoices chooses a name.
        allowed = {name.upper() for f in cls.allow_empty_environment for name in cls._source_names(f)}
        for source in (env_settings, dotenv_settings):
            source.env_vars = {k: v for k, v in source.env_vars.items() if v not in (None, "") or k.upper() in allowed}

        def resolved():
            layers = [
                cls._canonical(init_settings),
                cls._saved_source(),
                cls._canonical(env_settings),
                cls._canonical(dotenv_settings),
                cls._canonical(file_secret_settings),
            ]
            for fields in cls.connection_groups.values():
                owner = next((i for i, layer in enumerate(layers) if any(f in layer for f in fields)), None)
                if owner is not None:
                    for layer in layers[owner + 1 :]:
                        for field in fields:
                            layer.pop(field, None)
            values = {}
            for layer in reversed(layers):
                values.update(layer)
            return values

        return (resolved,)

    def __init__(self, **data):
        data.setdefault("_env_file", env_path)
        super().__init__(**data)
        self._saved_values = self.model_dump()

    @classmethod
    def _process_source(cls, field):
        names = {name.lower() for name in cls._source_names(field)}
        return next((name for name, value in os.environ.items() if name.lower() in names and value), None)

    def environment_source(self, field: str) -> str | None:
        # Saved application connections can override bootstrap environment;
        # security/admin settings keep deployment ownership.
        return None if self.section else self._process_source(field)

    def validate_update(self):
        current = self.model_dump()
        changed = {k: v for k, v in current.items() if self._saved_values.get(k) != v}
        if any(self.environment_source(k) for k in changed):
            raise ValueError("Configuration managed by environment")
        validated = type(self)(**current).model_dump()
        for key, value in validated.items():
            setattr(self, key, value)
        return {k: validated[k] for k in changed}

    def group_values(self, group: str) -> dict:
        return {field: getattr(self, field) for field in self.connection_groups[group]}

    def validate_connection(self, group):
        pass

    def update_env(self, connection_group=None):
        """Persist app-owned snapshots; never rewrite deployment dotenv or env."""
        changed = self.validate_update()
        if not changed and connection_group is None:
            return
        with _settings_lock:
            document = _read_settings()
            section = document.setdefault(self.section or type(self).__name__, {})
            grouped = set()
            for group, fields in self.connection_groups.items():
                grouped.update(fields)
                if group == connection_group or set(changed).intersection(fields):
                    self.validate_connection(group)
                    section[group] = self.group_values(group)
            options = {k: getattr(self, k) for k in changed if k not in grouped}
            if options:
                section.setdefault("options", {}).update(options)
            _write_file(settings_path(), yaml.safe_dump(document, allow_unicode=True, sort_keys=False))
        self._saved_values = self.model_dump()

    def check_env(self):
        loaded = type(self)()
        for field, value in loaded.model_dump().items():
            setattr(self, field, value)
        self._saved_values = self.model_dump()

    def generate_env(self):
        """Explicit export, omitting unset fields and process-injected secrets."""
        target = Path(env_path)
        if target.exists() and input(f"Replace configuration in {env_path}? (y/n) ").lower() != "y":
            return

        values = dict(dotenv_values(target)) if target.exists() else {}
        for field in type(self).model_fields:
            for alias in self._source_names(field):
                values.pop(alias, None)
                values.pop(alias.upper(), None)
            value = getattr(self, field)
            if value is not None and not self._process_source(field):
                values[field.upper()] = str(value)
        _write_file(target, "".join(f"{k}={_quote_dotenv(v)}\n" for k, v in values.items() if v is not None))
