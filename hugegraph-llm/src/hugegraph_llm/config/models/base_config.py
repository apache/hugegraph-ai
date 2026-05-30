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


import collections.abc
import os
import threading
import time
from typing import ClassVar, Optional

from dotenv import dotenv_values
from omegaconf import DictConfig, OmegaConf
from pydantic import BaseModel, ConfigDict, TypeAdapter

from hugegraph_llm.utils.log import log

dir_name = os.path.dirname
YAML_PATH = os.path.join(os.getcwd(), "config.yaml")
ENV_PATH = os.path.join(os.getcwd(), ".env")


def _flat_to_nested(flat_dict: dict, mapping: dict) -> dict:
    """Convert flat field names to nested dict using dot-notation mapping.

    Mapping: {"flat_name": "nested.path.key", ...}
    Fields not in the mapping are kept at the top level.
    """
    if not mapping:
        return flat_dict
    result: dict = {}
    for field_name, value in flat_dict.items():
        if field_name in mapping:
            path = mapping[field_name]
            parts = path.split(".")
            d = result
            for part in parts[:-1]:
                if part not in d:
                    d[part] = {}
                d = d[part]
            d[parts[-1]] = value
        else:
            result[field_name] = value
    return result


def _nested_to_flat(nested_dict: dict, mapping: dict) -> dict:
    """Convert nested dict from YAML to flat field names using dot-notation mapping.

    Reverse of _flat_to_nested. Walks the nested dict, matching dot-joined
    paths against the mapping keys.
    """
    if not mapping or not nested_dict:
        return nested_dict
    reverse_map = {v: k for k, v in mapping.items()}
    result = {}

    def _walk(prefix: str, d: dict) -> None:
        for key, value in d.items():
            full_key = f"{prefix}.{key}" if prefix else key
            if full_key in reverse_map:
                result[reverse_map[full_key]] = value
            elif isinstance(value, collections.abc.Mapping):
                _walk(full_key, value)
            else:
                result[full_key.replace(".", "_")] = value

    _walk("", nested_dict)
    return result


class ConfigManager:
    """Singleton manager for OmegaConf-based YAML configuration.

    Lifecycle:
    1. __init__: load config.yaml or migrate from .env, start file watcher
    2. Config classes read via get_section_with_env_override()
    3. Config classes write via update_section() + save()
    4. Background watcher polls for external changes → reload()
    """

    _instance: ClassVar[Optional["ConfigManager"]] = None

    def __new__(cls, sections=None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, sections=None):
        if self._initialized:
            return
        self._initialized = True
        self._yaml_path = YAML_PATH
        self._env_path = ENV_PATH
        self._sections: dict = sections or {}
        self._cfg: DictConfig = OmegaConf.create({})
        self._reload_lock = threading.Lock()
        self._watching = False
        self._watcher_thread: Optional[threading.Thread] = None
        self._last_mtime: float = 0.0
        self._reload_targets: list = []  # (section_name, config_object) tuples

        # Load .env into os.environ for backward compatibility and priority override
        if os.path.exists(self._env_path):
            for k, v in dotenv_values(self._env_path).items():
                os.environ[k] = v

        # Load or migrate
        if os.path.exists(self._yaml_path):
            self._cfg = OmegaConf.load(self._yaml_path)
            log.info("Loaded config from %s", self._yaml_path)
        elif os.path.exists(self._env_path):
            self._cfg = self._migrate_from_env()
        else:
            self._cfg = OmegaConf.create({})
            log.info("No config file found, using defaults")

        self._start_file_watcher()

    def _migrate_from_env(self) -> DictConfig:
        """Migrate .env to config.yaml with type conversion and nested structure.

        Only fields present in .env are written to YAML.
        """
        env_data = dotenv_values(self._env_path)
        cfg = OmegaConf.create({})
        for section_name, model_class in self._sections.items():
            model_fields = set(model_class.model_fields.keys())
            mapping = getattr(model_class, "_flat_to_nested_mapping", {})
            section_data = {}
            for env_key, env_value in env_data.items():
                lower_key = env_key.lower()
                if lower_key in model_fields and env_value:
                    section_data[lower_key] = env_value
            if section_data:
                instance = model_class(**section_data)
                full_dump = instance.model_dump()
                filtered = {k: v for k, v in full_dump.items() if k in section_data}
                nested = _flat_to_nested(filtered, mapping)
                cfg[section_name] = OmegaConf.create(nested)
            else:
                cfg[section_name] = OmegaConf.create({})
        OmegaConf.save(cfg, self._yaml_path)
        log.info("Migrated %s to %s", self._env_path, self._yaml_path)
        return cfg

    def load(self) -> DictConfig:
        """Re-read config from disk."""
        return OmegaConf.load(self._yaml_path)

    def save(self) -> None:
        """Persist current config tree to disk."""
        OmegaConf.save(self._cfg, self._yaml_path)

    def get_section(self, name: str) -> DictConfig:
        """Get a config section, creating it if it does not exist."""
        if name not in self._cfg:
            self._cfg[name] = OmegaConf.create({})
        return self._cfg[name]

    def get_section_with_env_override(self, section_name: str, model_class: type) -> dict:
        """Load section from YAML, convert nested→flat, then override with env vars.

        Priority: os.environ > config.yaml > pydantic defaults.
        """
        yaml_section = self.get_section(section_name)
        raw_dict = OmegaConf.to_container(yaml_section, resolve=True) if yaml_section else {}
        if raw_dict is None:
            raw_dict = {}

        mapping = getattr(model_class, "_flat_to_nested_mapping", {})
        section_dict = _nested_to_flat(raw_dict, mapping)

        env_var_map: dict = getattr(model_class, "_env_var_map", {})

        for field_name in model_class.model_fields:
            env_var_name = env_var_map.get(field_name, field_name.upper())
            env_value = os.environ.get(env_var_name)
            if env_value is not None and env_value != "":
                try:
                    field_info = model_class.model_fields[field_name]
                    ta = TypeAdapter(field_info.annotation)
                    section_dict[field_name] = ta.validate_python(env_value)
                except Exception:
                    section_dict[field_name] = env_value

        return section_dict

    def update_section(self, name: str, model: BaseModel) -> None:
        """Sync pydantic model fields into OmegaConf section with nested structure."""
        model_dict = model.model_dump()
        mapping = getattr(type(model), "_flat_to_nested_mapping", {})
        nested_dict = _flat_to_nested(model_dict, mapping)
        if name not in self._cfg:
            self._cfg[name] = OmegaConf.create({})
        self._cfg[name] = OmegaConf.create(nested_dict)

    def register_reload_target(self, section_name: str, config_object: BaseModel) -> None:
        """Register a config object for automatic sync on hot-reload."""
        self._reload_targets.append((section_name, config_object))

    def reload(self) -> bool:
        """Hot-reload config from YAML, validate, and sync to registered objects.

        Returns True on success. On failure, keeps current in-memory config.
        """
        with self._reload_lock:
            try:
                new_cfg = OmegaConf.load(self._yaml_path)
                for section_name, model_class in self._sections.items():
                    if section_name in new_cfg:
                        raw_dict = OmegaConf.to_container(new_cfg[section_name], resolve=True)
                        if raw_dict:
                            mapping = getattr(model_class, "_flat_to_nested_mapping", {})
                            flat_dict = _nested_to_flat(raw_dict, mapping)
                            model_class(**flat_dict)
                self._cfg = new_cfg
                for section_name, config_obj in self._reload_targets:
                    try:
                        config_obj.check_config()
                    except Exception as e:
                        log.error("Failed to sync '%s' on reload: %s", section_name, e)
                log.info("Config reloaded from %s", self._yaml_path)
                return True
            except Exception as e:
                log.error("Failed to reload config: %s. Keeping current values.", e)
                return False

    def _start_file_watcher(self) -> None:
        """Start background daemon thread polling for config file changes."""
        admin_section = self.get_section("admin")
        interval = admin_section.get("config_reload_interval", 5) if admin_section else 5
        if not isinstance(interval, (int, float)) or interval <= 0:
            log.info("Config hot-reload disabled (config_reload_interval=%s)", interval)
            return

        self._watching = True
        self._last_mtime = os.path.getmtime(self._yaml_path) if os.path.exists(self._yaml_path) else 0.0

        def _watch_loop():
            while self._watching:
                time.sleep(interval)
                try:
                    if not os.path.exists(self._yaml_path):
                        continue
                    current_mtime = os.path.getmtime(self._yaml_path)
                    if current_mtime != self._last_mtime:
                        self._last_mtime = current_mtime
                        log.info("Config file change detected, reloading...")
                        self.reload()
                except Exception as e:
                    log.error("File watcher error: %s", e)

        self._watcher_thread = threading.Thread(target=_watch_loop, daemon=True)
        self._watcher_thread.start()
        log.info("Config file watcher started (interval=%ss)", interval)

    def _stop_file_watcher(self) -> None:
        """Stop the background file watcher thread."""
        self._watching = False


class BaseConfig(BaseModel):
    """Base configuration class using OmegaConf/YAML for persistence.

    Subclasses must define:
    - _config_section: ClassVar[str] — YAML section name ("llm", "hugegraph", etc.)
    - _flat_to_nested_mapping: ClassVar[dict] — flat field → nested path mapping
    """

    model_config = ConfigDict(extra="ignore")

    _config_section: ClassVar[str] = ""
    _flat_to_nested_mapping: ClassVar[dict] = {}

    def __init__(self, **data):
        cfg_mgr = ConfigManager()
        yaml_data = {}
        if self._config_section:
            yaml_data = cfg_mgr.get_section_with_env_override(self._config_section, type(self))
        yaml_data.update(data)
        super().__init__(**yaml_data)
        if self._config_section:
            cfg_mgr.update_section(self._config_section, self)
            cfg_mgr.save()
            cfg_mgr.register_reload_target(self._config_section, self)
            log.info("Config section '%s' initialized.", self._config_section)

    def update_config(self) -> None:
        """Persist current pydantic field values to config.yaml."""
        cfg_mgr = ConfigManager()
        cfg_mgr.update_section(self._config_section, self)
        cfg_mgr.save()
        log.info("Config section '%s' updated and saved.", self._config_section)

    def generate_yaml(self) -> None:
        """Generate config.yaml section with current model default values."""
        cfg_mgr = ConfigManager()
        if os.path.exists(YAML_PATH):
            log.info(
                "%s already exists, do you want to override with the default configuration? (y/n)",
                YAML_PATH,
            )
            update = input()
            if update.lower() != "y":
                return
        cfg_mgr.update_section(self._config_section, self)
        cfg_mgr.save()
        log.info("Generated %s section '%s' successfully!", YAML_PATH, self._config_section)

    def check_config(self) -> None:
        """Synchronize config from YAML file to object attributes."""
        cfg_mgr = ConfigManager()
        try:
            yaml_data = cfg_mgr.get_section_with_env_override(self._config_section, type(self))
            for key, value in yaml_data.items():
                current = getattr(self, key, None)
                if current != value:
                    log.info(
                        "Update configuration from file: %s=%s (was: %s)",
                        key,
                        value,
                        current,
                    )
                    setattr(self, key, value)
            cfg_mgr.update_section(self._config_section, self)
            cfg_mgr.save()
        except Exception as e:
            log.error("An error occurred when checking config file: %s", e)
            raise

    # Backward-compatible aliases for existing consumer code
    def update_env(self) -> None:
        """[Deprecated] Use update_config() instead."""
        self.update_config()

    def generate_env(self) -> None:
        """[Deprecated] Use generate_yaml() instead."""
        self.generate_yaml()

    def check_env(self) -> None:
        """[Deprecated] Use check_config() instead."""
        self.check_config()
