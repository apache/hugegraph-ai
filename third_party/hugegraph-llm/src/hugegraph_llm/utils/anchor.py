#  Licensed to the Apache Software Foundation (ASF) under one or more
#  contributor license agreements.  See the NOTICE file distributed with
#  this work for additional information regarding copyright ownership.
#  The ASF licenses this file to You under the Apache License, Version 2.0
#  (the "License"); you may not use this file except in compliance with
#  the License.  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

from pathlib import Path


def get_project_root() -> Path:
    """
    Returns the Path object of the project root directory.

    The function searches for common project root indicators like pyproject.toml
    or .git directory by traversing up the directory tree from the current file location.

    Returns:
        Path: The absolute path to the project root directory

    Raises:
        RuntimeError: If no project root indicators could be found
    """
    current_path = Path(__file__).resolve()
    for parent in current_path.parents:
        if (parent / "pyproject.toml").exists() or (parent / ".git").exists():
            return parent
    # Raise an error if no project root is found
    raise RuntimeError(
        "Project root could not be determined. Ensure that 'pyproject.toml' or '.git' exists in the project directory."
    )
