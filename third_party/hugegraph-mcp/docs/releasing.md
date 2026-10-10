# Publishing HugeGraph MCP

Python packages are published through the shared
[`hugegraph/actions` workflow](https://github.com/hugegraph/actions/blob/master/.github/workflows/publish_python.yml).
This repository owns package versions, dependencies, and tests. The actions
repository owns building, artifact verification, and uploading. There is no
second tag-triggered publisher in this repository.

## Package Versions

The intermediate client and MCP packages use `1.7.1`. MCP requires
`hugegraph-python>=1.7.1,<2`; the published `1.7.0` client does not include all
client fixes required by MCP. Publish the client before the MCP package.

For the planned `1.8.0` release, update the repository's package versions together
and raise the MCP client dependency to `>=1.8.0,<2`. Already uploaded `1.7.1`
artifacts remain available; do not overwrite or delete them.

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
Both packages must have matching source versions and use the same resolved commit.
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
4. Verify installation from outside the checkout:

   ```bash
   uvx --no-cache hugegraph-mcp@1.7.1
   ```

5. Configure the HugeGraph URL and credentials, connect an MCP client, and verify
   initialization, `tools/list`, `inspect_graph_tool`, and a bounded
   `query_graph_data_tool` request against a real HugeGraph Server >= 1.7.0.

The shared workflow tests wheel/sdist installation and uses
`tests/distribution_smoke.py` to exercise MCP stdio with a local HTTP fixture.
The script starts the installed command in a temporary directory, removes source
import overrides, and verifies initialization, 16 v2 tools, inspection, and a
structured query. This checks packaging and protocol wiring; it does not replace
real-server integration tests.

To repeat the distribution smoke locally, build a wheel and pass its absolute
path (the client must already be on PyPI):

```bash
uv build --no-sources hugegraph-mcp --out-dir /tmp/mcp-dist
python hugegraph-mcp/tests/distribution_smoke.py -- \
  uvx --no-config --no-cache --index-url https://pypi.org/simple \
  --from /tmp/mcp-dist/hugegraph_mcp-1.7.1-py3-none-any.whl hugegraph-mcp
```

PR CI separately tests wheels for both packages from the same checkout. That
check may pass before the client is published and is not a substitute for the
published-client gate above.
