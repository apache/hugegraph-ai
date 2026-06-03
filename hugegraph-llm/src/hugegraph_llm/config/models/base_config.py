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
from pathlib import Path

from dotenv import dotenv_values, set_key
from pydantic_settings import BaseSettings

from hugegraph_llm.utils.log import log

dir_name = os.path.dirname
ENV_PATH_ENV_VAR = "HUGEGRAPH_LLM_ENV_PATH"


def _source_project_root() -> Path | None:
    package_root = Path(__file__).resolve().parents[2]
    if package_root.parent.name != "src":
        return None
    project_root = package_root.parent.parent
    if (project_root / "pyproject.toml").exists():
        return project_root
    return None


def resolve_env_path() -> str:
    explicit_env_path = os.getenv(ENV_PATH_ENV_VAR)
    if explicit_env_path:
        return str(Path(explicit_env_path).expanduser())

    project_root = _source_project_root()
    if project_root is not None:
        return str(project_root / ".env")

    return str(Path.cwd() / ".env")


env_path = resolve_env_path()


class BaseConfig(BaseSettings):
    class Config:
        env_file = env_path
        case_sensitive = False
        extra = "ignore"  # ignore extra fields to avoid ValidationError
        env_ignore_empty = True

    def generate_env(self):
        if os.path.exists(env_path):
            log.info(
                "%s already exists, do you want to override with the default configuration? (y/n)",
                env_path,
            )
            update = input()
            if update.lower() != "y":
                return
            self.update_env()
        else:
            config_dict = self.model_dump()
            config_dict = {k.upper(): v for k, v in config_dict.items()}
            with open(env_path, "w", encoding="utf-8") as f:
                for k, v in config_dict.items():
                    if v is None:
                        f.write(f"{k}=\n")
                    else:
                        f.write(f"{k}={v}\n")
            log.info("Generate %s successfully!", env_path)

    def update_env(self):
        config_dict = self.model_dump()
        config_dict = {k.upper(): v for k, v in config_dict.items()}
        env_config = dotenv_values(f"{env_path}")

        # dotenv_values make None to '', while pydantic make None to None
        # dotenv_values make integer to string, while pydantic make integer to integer
        for k, v in config_dict.items():
            if k in env_config:
                if not (env_config[k] or v):
                    continue
                if env_config[k] == str(v):
                    continue
            log.info("Update %s: %s=%s", env_path, k, v)
            set_key(env_path, k, v if v else "", quote_mode="never")

    def check_env(self):
        """Synchronize configs between .env file and object.

        This method performs two steps:
        1. Updates object attributes from .env file values when they differ
        2. Adds missing configuration items to the .env file
        """
        try:
            # Read the.env file and prepare object config
            env_config = dotenv_values(env_path)
            config_dict = {k.upper(): v for k, v in self.model_dump().items()}

            # Step 1: Update the object from .env when values differ
            self._sync_env_to_object(env_config, config_dict)
            # Step 2: Add missing config items to .env
            self._sync_object_to_env(env_config, config_dict)
        except Exception as e:
            log.error("An error occurred when checking the .env variable file: %s", str(e))
            raise

    def _sync_env_to_object(self, env_config, config_dict):
        """Update object attributes from .env file values when they differ."""
        for env_key, env_value in env_config.items():
            if env_key in config_dict:
                obj_value = config_dict[env_key]
                obj_value_str = str(obj_value) if obj_value is not None else ""

                if env_value != obj_value_str:
                    log.info(
                        "Update configuration from the file: %s=%s (Original value: %s)",
                        env_key,
                        env_value,
                        obj_value_str,
                    )
                    # Update the object attribute (using lowercase key)
                    setattr(self, env_key.lower(), env_value)

    def _sync_object_to_env(self, env_config, config_dict):
        """Add missing configuration items to the .env file."""
        for obj_key, obj_value in config_dict.items():
            if obj_key not in env_config:
                obj_value_str = str(obj_value) if obj_value is not None else ""
                log.info(
                    "Add configuration items to the environment variable file: %s=%s",
                    obj_key,
                    obj_value,
                )
                # Add to .env
                set_key(env_path, obj_key, obj_value_str, quote_mode="never")

    def __init__(self, **data):
        try:
            file_exists = os.path.exists(env_path)
            # Step 1: Load environment variables if file exists
            if file_exists:
                env_config = dotenv_values(env_path)
                for k, v in env_config.items():
                    os.environ[k] = v

            # Step 2: Init the parent class with loaded environment variables
            super().__init__(**data)
            # Step 3: Handle environment file operations after initialization
            if not file_exists:
                self.generate_env()
            else:
                # Synchronize configurations between the object and .env file
                self.check_env()

            log.info("The %s file was loaded. Class: %s", env_path, self.__class__.__name__)
        except Exception as e:
            log.error("An error occurred when initializing the configuration object: %s", str(e))
            raise
