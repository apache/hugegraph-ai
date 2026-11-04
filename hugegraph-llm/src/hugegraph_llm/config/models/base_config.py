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
from pathlib import Path
from typing import ClassVar, get_args
from urllib.parse import urlsplit

from dotenv import dotenv_values, set_key
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
    credential_endpoints: ClassVar[dict[str, tuple[str, ...]]] = {}

    @classmethod
    def _source_names(cls, field):
        alias = cls.model_fields[field].validation_alias
        names = alias.choices if isinstance(alias, AliasChoices) else [alias or field]
        return tuple(dict.fromkeys([*names, field]))

    @classmethod
    def _allows_empty(cls, field: str, process: bool) -> bool:
        if process:
            return field in cls.allow_empty_environment
        annotation = cls.model_fields[field].annotation
        return annotation is str or str in get_args(annotation)

    @classmethod
    def _file_value(cls, field, values=None, *, use_default=True):
        if values is None:
            values = {key.upper(): value for key, value in dotenv_values(env_path).items()}
        for name in cls._source_names(field):
            value = values.get(name.upper())
            if value is not None and (value != "" or cls._allows_empty(field, False)):
                return value
        return cls.model_fields[field].default if use_default else None

    @staticmethod
    def _endpoint_identity(field, value):
        if value is None:
            return None
        if field.endswith("_port"):
            return int(value)
        value = str(value).strip()
        if field.endswith("_host"):
            return value.lower()
        if not field.endswith(("_url", "_base")):
            return value
        try:
            parsed = urlsplit(value if "://" in value else "http://" + value)
            scheme = parsed.scheme.lower()
            port = parsed.port if parsed.port is not None else {"http": 80, "https": 443}.get(scheme)
            return (
                scheme,
                parsed.hostname,
                port,
                parsed.path.rstrip("/"),
                parsed.query,
                parsed.username,
                parsed.password,
            )
        except ValueError:
            # An invalid URL can never establish that a stored secret is safe
            # to reuse. Leave connection validation to the existing caller.
            return object()

    @classmethod
    def _endpoint_fields(cls, credential, values=None):
        return cls.credential_endpoints[credential]

    @classmethod
    def _direct_environment_source(cls, field):
        environment = {name.upper(): name for name in os.environ}
        for name in cls._source_names(field):
            if source := environment.get(name.upper()):
                if os.environ[source] or cls._allows_empty(field, True):
                    return source
        return None

    @classmethod
    def _credential_source(cls, field):
        return cls._direct_environment_source(field)

    @classmethod
    def _changed_endpoint_source(cls, credential, current=None):
        if cls._credential_source(credential):
            return None
        fields = cls._endpoint_fields(credential, current)
        sources = {field: cls._direct_environment_source(field) for field in fields}
        if not any(sources.values()):
            return None
        values = {key.upper(): value for key, value in dotenv_values(env_path).items()}
        if not cls._file_value(credential, values, use_default=False):
            return None
        for field, source in sources.items():
            previous = cls._file_value(field, values)
            effective = next(
                (current[name] for name in cls._source_names(field) if current and name in current),
                os.environ[source] if source else previous,
            )
            if cls._endpoint_identity(field, effective) != cls._endpoint_identity(field, previous):
                return next(source for source in sources.values() if source)
        return None

    def environment_source(self, field: str) -> str | None:
        """Only injected values are read-only; an injected key owns its target."""
        cls = type(self)
        if field in cls.credential_endpoints:
            return cls._credential_source(field)
        if source := cls._direct_environment_source(field):
            return source
        for credential in cls.credential_endpoints:
            if field in cls._endpoint_fields(credential, self.model_dump()) and (
                source := cls._credential_source(credential)
            ):
                return source
        return None

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        # Remove placeholders before AliasChoices selects a value, so an empty
        # specific process name cannot hide a nonempty generic process alias.
        allowed = {name.upper() for field in cls.allow_empty_environment for name in cls._source_names(field)}
        env_settings.env_vars = {
            name: value for name, value in env_settings.env_vars.items() if value != "" or name.upper() in allowed
        }

        def normalize(source, process):
            values = source()
            for field in cls.model_fields:
                if not cls._allows_empty(field, process):
                    for name in cls._source_names(field):
                        if values.get(name) == "":
                            values.pop(name)
            return values

        def scoped_environment():
            values = normalize(env_settings, True)
            for credential in cls.credential_endpoints:
                if source := cls._changed_endpoint_source(credential, init_settings()):
                    values[cls._source_names(credential)[0]] = (
                        "" if cls.model_fields[credential].annotation is str else None
                    )
                    if cls._file_value(credential):
                        log.warning(
                            "Ignoring stored %s because its endpoint changed through %s; "
                            "configure the new credential explicitly",
                            credential.upper(),
                            source,
                        )
            return values

        return init_settings, scoped_environment, lambda: normalize(dotenv_settings, False), file_secret_settings

    def __init__(self, **data):
        try:
            data.setdefault("_env_file", env_path)
            super().__init__(**data)
            self._saved_values = self.model_dump()
        except Exception as exc:
            log.error("Failed to initialize %s from %s (%s)", type(self).__name__, env_path, type(exc).__name__)
            raise

    def validate_update(self):
        """Reject managed field changes before persistence or connection probes."""
        current = self.model_dump()
        changed = {
            key: value
            for key, value in current.items()
            if key not in self._saved_values or value != self._saved_values[key]
        }
        managed = [field for field in changed if self.environment_source(field)]
        if managed:
            raise ValueError("Configuration managed by environment: " + ", ".join(managed))
        return changed

    def update_env(self):
        current = self.model_dump()
        changed = self.validate_update()
        if not changed:
            return
        # A user-saved credential belongs to the effective target. Record that
        # target too, so a later reload does not mistake it for an old secret.
        to_write = dict(changed)
        for credential in self.credential_endpoints:
            if credential in changed:
                endpoints = self._endpoint_fields(credential, current)
                if any(self._direct_environment_source(field) for field in endpoints):
                    to_write.update({field: current[field] for field in endpoints if current[field] is not None})
        target = Path(env_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Stage all changes together. Failed writes leave the original intact;
        # restrictive permissions also apply when the file contains UI secrets.
        fd, staging = tempfile.mkstemp(prefix=".env-", dir=target.parent)
        os.close(fd)
        try:
            if target.exists():
                Path(staging).write_bytes(target.read_bytes())
            for field, value in to_write.items():
                log.info("Update configuration field %s in %s", field.upper(), env_path)
                text = "" if value is None else str(value)
                needs_quotes = (
                    text != text.strip() or any(c in text for c in ("\n", "\r", " #")) or text.startswith(("'", '"'))
                )
                set_key(staging, field.upper(), text, quote_mode="always" if needs_quotes else "never")
            if target.exists():
                os.chmod(staging, target.stat().st_mode & 0o777)
            try:
                os.replace(staging, target)
            except OSError as exc:
                if exc.errno != errno.EBUSY or not target.exists():
                    raise
                log.warning(
                    "Atomic replacement is unavailable for bind-mounted configuration %s; "
                    "falling back to an in-place update",
                    env_path,
                )
                target.write_bytes(Path(staging).read_bytes())
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
