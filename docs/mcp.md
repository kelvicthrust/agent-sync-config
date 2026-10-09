# Shared MCP configuration

`.agents/mcp.json` is this project's neutral format, not a provider standard.
Personal definitions use the same format in the registered personal root's
`mcp.json`. Run `--scope project` for project definitions and `--scope global`
for personal definitions. Synchronization and explicit `--import-mcp` adoption
affect only the selected scope. A minimal manifest contains `schema: 1` and a `servers` object:

```json
{
  "schema": 1,
  "servers": {
    "local-tools": {
      "transport": "stdio",
      "command": "python3",
      "args": ["/absolute/path/to/server.py"],
      "env": {"LOG_LEVEL": "info"},
      "env_vars": ["SERVICE_API_KEY"]
    },
    "remote-tools": {
      "transport": "http",
      "url": "https://example.com/mcp",
      "bearer_token_env_var": "SERVICE_TOKEN",
      "env_headers": {"X-Tenant": "SERVICE_TENANT"}
    }
  }
}
```

Server names use letters, digits, hyphens, or underscores. stdio requires a
nonempty `command`; HTTP requires a nonempty `url`.

| Shared field | Codex output | Claude output |
| --- | --- | --- |
| `command`, `args` | Same fields | Same fields, `type: stdio` |
| `env` | Literal nonsecret environment values | Same values |
| `env_vars` | Inherited variable names | `env` entries with `${NAME}` |
| `url` | Same field | Same field, `type: http` |
| `headers` | `http_headers` | `headers` |
| `env_headers` | `env_http_headers` | Header values `${NAME}` |
| `bearer_token_env_var` | Same field | `Authorization: Bearer ${NAME}` |
| `cwd` | Same field | Unsupported; reported |

Use `env`/`headers` only for literal nonsecret values. Credential-like keys and
literal Authorization headers are rejected. `env_vars` passes a variable under
the same name; aliases and arbitrary interpolation are not portable. Provider
workspace placeholders in command paths, arguments, cwd, or URLs are rejected.
Use literal paths and independently define environment variables in the launch
environment. GUI clients may not inherit your terminal's environment.

The supported HTTP transport is streamable HTTP; SSE-only definitions are not
translated. Provider-specific timeout, tool filtering, and authentication options
cannot be adopted into the shared subset automatically. Preserve them in native
configuration and reconcile deliberately. An extra native option on a managed
definition is treated as a manual edit and preserved, not discarded.

On first setup, supported existing provider definitions can become canonical.
Identical definitions are adopted; differing ones are reported. A native server
without an explicit stdio `type` is treated as equivalent to `type: stdio`.

Subsequent runs compare canonical output, native configuration, and the recorded
last output. Canonical-only changes render safely; divergent native edits require
reconciliation. To resolve a conflict, review and update the canonical source and
the corresponding native definition to agree, then rerun. There is no force flag.

Personal Claude definitions use the top-level `mcpServers` in `~/.claude.json`.
Private project mappings in that file are preserved. Project output uses
`.mcp.json`. Codex uses global/trusted project `.codex/config.toml` layers.

OAuth credentials, login sessions, and native server approvals remain independent.
Reconnect/restart after changes when required. The tool does not resolve `${...}`
values or execute MCP servers during synchronization.
