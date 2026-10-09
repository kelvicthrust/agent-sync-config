# Future coding clients

Initial support is for local Codex and Claude Code. Cursor, Grok, and other
coding clients are not implemented or verified integrations. Changing a model
within a client generally retains that client's resource loader; changing the
client requires a separate compatibility check.

Keep `AGENTS.md`, `.agents/skills/`, curated context, and the neutral MCP manifest
as canonical resources. Add an explicit client adapter when support is requested,
without introducing another source of truth.

Each adapter must establish:

- Project/global instruction discovery, precedence, imports, and nested scopes.
- Skill discovery, invocation, symlink support, and duplicate handling.
- Native MCP paths, transports, environment syntax, and credential boundaries.
- Native instruction refresh on session/resume, imports, and read-only behavior.
- Personal defaults and local versus remote/cloud filesystem availability.

Verify fresh and existing repositories, repeat runs, conflicts, actual resource
discovery, native MCP loading, client switching, fresh/resumed sessions, read-only
behavior, and explicit check performance. Record tested versions and report each
capability separately.

Sharing files does not guarantee identical plugin behavior or model compliance.
Adapters should establish shared references without bundling the synchronizer
into projects or adding automatic hooks. Repairs and MCP rendering use explicit
checks/syncs. Plugins remain provider-managed.
