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
"""E2E backend server for frontend integration tests.

Boots the real API stack on a free port and prints ``READY <port>``. Uses the
same demo bootstrap as ``ontogeny serve --demo`` (single source of truth for seed
data) with a throwaway data directory, so promotions never touch the repo.

Run: PYTHONPATH=server .venv/bin/python tests/e2e_server.py
"""
from __future__ import annotations

import os
import socket
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "server"))


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    from ontogeny.demo import prepare_demo

    tmp = Path(tempfile.mkdtemp(prefix="ontogeny-e2e-"))
    paths = prepare_demo(tmp / "demo", package=REPO / "domains" / "product-manufacturing")
    os.environ.update(paths.as_env())
    os.environ.update(
        {
            # the integration suite drives the API with dev-principal headers;
            # dev_auth is off by default in production now
            "ONTOGENY_DEV_AUTH": "1",
            "ONTOGENY_LLM_BASE_URL": os.environ.get("ONTOGENY_LLM_BASE_URL", "http://10.70.11.36:63302"),
            "ONTOGENY_LLM_MODEL": os.environ.get("ONTOGENY_LLM_MODEL", "qwen3.8:27b"),
            "ONTOGENY_UI_DIR": str(tmp / "no-ui"),  # API-only: the SPA is covered by unit tests
        }
    )

    import uvicorn

    port = _free_port()
    print(f"READY {port}", flush=True)
    uvicorn.run("ontogeny.api_factory:create_app_factory", factory=True, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
