# Publishing HugeGraph MCP

HugeGraph MCP is distributed from PyPI and launched with `uvx`. It depends on
`hugegraph-python-client`, so release the client before the MCP package.

## Repository Setup

Configure PyPI Trusted Publishers for these GitHub environments and workflows:

| PyPI project | GitHub environment | Workflow |
| --- | --- | --- |
| `hugegraph-python-client` | `pypi-hugegraph-python-client` | `publish-hugegraph-python-client.yml` |
| `hugegraph-mcp` | `pypi-hugegraph-mcp` | `publish-hugegraph-mcp.yml` |

Require reviewer approval on both GitHub environments. The workflows request
short-lived OIDC credentials and do not use long-lived PyPI API tokens.

## Release Order

1. Update and verify the versions in both package `pyproject.toml` files.
2. Publish the client by pushing `client-v<version>`, for example
   `client-v1.7.0`.
3. Confirm that the client version is available from PyPI.
4. Publish MCP by pushing `mcp-v<version>`, for example `mcp-v1.7.0`.
5. Verify the public installation:

   ```bash
   uvx --from hugegraph-mcp==1.7.0 hugegraph-mcp
   ```

The MCP build job resolves its wheel only against published dependencies, so it
stops before upload when the required client release is unavailable.
