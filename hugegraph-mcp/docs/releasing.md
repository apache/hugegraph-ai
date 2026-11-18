# Publishing HugeGraph MCP

Python packages are published through the shared
[`hugegraph/actions` workflow](https://github.com/hugegraph/actions/blob/master/.github/workflows/publish_python.yml).
This repository owns package versions, dependencies, and tests. The actions
repository owns building, artifact verification, and uploading. There is no
second tag-triggered publisher in this repository.

## Package Versions

Client and MCP use the release version defined in the root `pyproject.toml`.
Run `"${PYTHON_FOR_RELEASE:-python3}" scripts/version.py sync` after changing that version and
`"${PYTHON_FOR_RELEASE:-python3}" scripts/version.py check` before building. The MCP client dependency
minimum is synchronized with it. See [workspace release preparation](../../docs/releasing.md).
Publish the client before MCP. Previously published `1.7.1` artifacts remain
available and must not be overwritten or deleted.

`hugegraph-python` is the client distribution name, `pyhugegraph` is its import
name, and `hugegraph-python-client/` is its source directory. `hugegraph-mcp`
contains the MCP adapter and console entry point, not the entire AI workspace.
Users need neither a Git checkout nor a manual client installation.

## Shared Workflow

Select `component=both` (the default) to process client and MCP in order. Keep
`client` and `mcp` for individual validation or retry. Select the source repository
(`apache/hugegraph-ai` or `hugegraph/hugegraph-ai`) and a branch, tag, or commit via
`source_ref`; the workflow resolves it to one immutable commit before building.
Public PyPI uploads require the Apache source repository; fork sources are
limited to validation and TestPyPI. The source commit must contain the requested
component and its tests. Fork
validation can therefore run before the PR is merged into ASF `main`.

The workflow defaults to `publish=false`: it builds, tests, and records artifacts
without uploading a package. In `both` mode, MCP uses the verified client artifact
from the same run; this validates the package pair, not registry installation.
Use `both` with the same resolved source commit and run the release metadata
check first. Local validation does not establish that the remote publishing
workflow has succeeded.
With `publish=true`, `target` selects the `testpypi`
or `pypi` GitHub environment and its `PYPI_API_TOKEN`. The PyPI token must have
permission for the selected project; a token scoped only to `hugegraph-python`
cannot create or upload `hugegraph-mcp`. Follow the environment approval rules in
the actions repository.

For PyPI, the version comes from the selected component's `pyproject.toml`.
TestPyPI uses one shared `test_version` for client and MCP; see the actions
README for its format. Leave it empty for public PyPI. TestPyPI validation
does not establish compatibility with a client published only on public PyPI.

## Publish and Validate

1. Select a source commit containing both client fixes and MCP. Confirm package
   versions, the MCP client dependency, and passing unit/contract tests.
2. Run `component=both` with `publish=false` to validate both packages from the
   selected source commit without uploading.
3. Run the same inputs with `publish=true`. The workflow publishes the client,
   verifies registry availability, then validates MCP using that exact client
   version from the selected index before publishing MCP. If MCP fails after the
   client is published, fix the cause and use `component=mcp` to retry; do not
   re-upload an existing client version.
4. After the prepared release has been published, verify installation from outside the checkout
   (the command below is available only after publication):

   ```bash
   uvx --no-cache hugegraph-mcp@1.8.0
   ```

5. Configure the HugeGraph URL and credentials, connect an MCP client, and verify
   initialization, `tools/list`, `inspect_graph_tool`, and a bounded
   `query_graph_data_tool` request against a real HugeGraph Server >= 1.7.0.

The shared workflow tests wheel/sdist installation and uses
`tests/distribution_smoke.py` to exercise MCP stdio with a local HTTP fixture.
The script starts the installed command in a temporary directory, removes source
import overrides, and verifies initialization, 24 core tools, inspection, and a
structured query. This checks packaging and protocol wiring; it does not replace
real-server integration tests.

To repeat the distribution smoke locally, build a wheel and pass its absolute
path after building the aligned packages. Include the local client wheel to validate
before publication:

```bash
uv build --no-sources hugegraph-python-client --out-dir /tmp/mcp-dist
uv build --no-sources hugegraph-mcp --out-dir /tmp/mcp-dist
python hugegraph-mcp/tests/distribution_smoke.py -- \
  uvx --no-config --no-cache --index-url https://pypi.org/simple \
  --with "$(realpath /tmp/mcp-dist/hugegraph_python-*.whl)" \
  --from "$(realpath /tmp/mcp-dist/hugegraph_mcp-*.whl)" hugegraph-mcp
```

PR CI separately tests wheels for both packages from the same checkout. That
check may pass before the client is published and is not a substitute for the
published-client gate above.
