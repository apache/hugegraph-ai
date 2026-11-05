# Preparing a release

The root `pyproject.toml` owns `project.version` and the image configuration under
`tool.hugegraph.release`. Subpackage versions remain static so each wheel/sdist
can be built independently and the shared publisher can read their metadata.
MCP initialization and LLM OpenAPI report the installed distribution version,
so they follow the same source without another runtime version constant.

With Python 3.12+ at the repository root:

```bash
# Edit only the root release version, then synchronize generated fields.
"${PYTHON_FOR_RELEASE:-python3}" scripts/version.py sync
"${PYTHON_FOR_RELEASE:-python3}" scripts/version.py check
"${PYTHON_FOR_RELEASE:-python3}" scripts/version.py get version
```

Synchronization updates the six subpackages (including the standalone LLM SDK),
MCP's client dependency minimum, LLM's exact SDK dependency,
Compose deployment image references and current installation examples. Historical migrations, compatibility minimums, backend capability
evidence and protocol versions are maintained separately. CI rejects drift.
The root `tool.hugegraph.ci` table also defines the shared uv version and primary
Python runtime; see [CI selection](quality/ci.md) for full-validation controls.
Ruff and ty use `>=` lower bounds in root development dependencies. CI uses
those same ranges, and local pre-commit hooks run Ruff through uv without a fixed
hook revision or a separate tool version.

Build the source LLM image with `bash scripts/build_llm_image.sh`. The script
uses the root image repository and release tag. Set `PYTHON_FOR_RELEASE` to a
Python 3.12+ executable when `python3` is older. Before images are published,
build locally or follow the source installation instructions; release tags in
documentation become pullable only after publication.

`scripts/apache-release.sh [version [username [password]]]` retains its existing
argument order and defaults to the root version. It checks metadata and the
release branch version before archiving/signing/uploading. Follow the existing
ASF release process for signatures, voting and distribution.
The script resolves the release branch to one commit, extracts a temporary
detached worktree, and checks all synchronized fields in the complete checkout
before creating the distribution archive. The final `git archive` uses the same
immutable commit and retains `.gitattributes` distribution exclusions. CI also
builds and installs the resulting source archive without the excluded ML module.
To check another snapshot directly, use
`"${PYTHON_FOR_RELEASE:-python3}" scripts/version.py check --root /path/to/snapshot`.

CI intentionally follows Server `latest` during development. Its core-version
guard fails on drift and logs the digest used. For reproducible Compose
deployments, set `HUGEGRAPH_SERVER_IMAGE` to a verified release tag or digest;
this leaves the root CI image choice unchanged.

Python publication uses the existing external
[`hugegraph/actions` workflow](../hugegraph-mcp/docs/releasing.md): validate with
`publish=false`, publish the client before MCP and the SDK before LLM, and verify
installation from outside the checkout. LLM requires the matching SDK release;
before publication, validate them together from source or local wheels. Already uploaded versions must not be overwritten.
