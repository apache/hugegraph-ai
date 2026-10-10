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
"""ontogeny.demo — demo bootstrap and data mounting.

- :mod:`bootstrap`  the one-command installation (``ontogeny serve --demo``)
- :mod:`mounting`   the shared data-mounting core (builder + demo)
"""
from .bootstrap import (
    DEFAULT_DEMO_DIR,
    DEFAULT_PACKAGE,
    DemoPaths,
    copy_package,
    prepare_demo,
    reset_demo,
    seed_from_package,
    seed_source_db,
)

__all__ = [
    "DEFAULT_PACKAGE", "DEFAULT_DEMO_DIR", "DemoPaths", "prepare_demo", "reset_demo",
    "copy_package", "seed_from_package", "seed_source_db",
]
