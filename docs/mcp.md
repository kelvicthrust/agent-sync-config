# Native MCP sharing

The synchronizer reads native definitions directly. Project files are `.mcp.json`
for Claude and `.codex/config.toml` for Codex. Global files are top-level
`mcpServers` in `~/.claude.json` and `mcp_servers` in `~/.codex/config.toml`.
Claude's private project entries in `~/.claude.json` are not project-scope input.

A server present on only one side is a candidate for sharing. Equivalent native
definitions need no writes. Same-name differences are conflicts, even if only one
side was edited since your last run: there is no stored baseline or history.
Resolve them explicitly:

```sh
./bin/agent-sync-config --scope project --project /path/to/repo --mcp-source claude
./bin/agent-sync-config --scope global --mcp-source codex
```

Source selection resolves portable same-name differences. It does not remove
servers missing from one side; absent definitions can be adopted again. To remove
a shared server, remove it from both native configurations.

Import native Claude-format definitions with `--import-mcp /path/to/file.json`.
The file must contain `mcpServers`. An import explicitly selects the definitions
for its named servers, leaving other servers intact. Do not combine it with
`--mcp-source`. No neutral MCP manifest is created or stored.

| Portable concept | Codex | Claude |
| --- | --- | --- |
| stdio | `command`, `args` | `type: stdio`, `command`, `args` |
| HTTP | `url` | `type: http`, `url` |
| Nonsecret environment | `env` | `env` |
| Inherited environment | `env_vars` | `env` values `${NAME}` |
| Nonsecret headers | `http_headers` | `headers` |
| Environment headers | `env_http_headers` | `headers` values `${NAME}` |
| Bearer-token environment | `bearer_token_env_var` | `Authorization: Bearer ${NAME}` |

An omitted Claude stdio `type` is equivalent to `stdio`. Inherited environment
variables must keep the same name; aliased interpolation is not portable. Literal
credential environment values and headers are rejected for sharing. Use inherited
variables and configure them independently in each client's launch environment.

SSE, provider placeholders, plugin-managed definitions, Codex `cwd`, timeout/tool
policies, and native authentication options are outside the portable subset.
Unsupported definitions remain intact and are reported, including when a source
was selected. A selection never authorizes dropping unsupported destination
options. Nonconflicting definitions can still be shared.

Native options, unrelated settings, TOML comments, file permissions, credentials,
OAuth sessions, and approvals remain provider-managed. The tool neither resolves
environment variables nor starts servers. Reconnect/restart clients when required;
project Codex configuration requires native trust. Checks and dry runs are
strictly read-only.
