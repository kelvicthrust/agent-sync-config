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
- Session/resume/prompt hooks, output contracts, trust, and read-only behavior.
- Personal defaults and local versus remote/cloud filesystem availability.

Verify fresh and existing repositories, repeat runs, conflicts, actual resource
discovery, native MCP loading, client switching, fresh/resumed sessions, read-only
behavior, and warm-check latency. Record tested versions and report each
capability separately.

Sharing files does not guarantee identical hook enforcement, plugin behavior,
or model compliance. A client without prompt hooks may require an explicit check
or startup wrapper; document that limitation. Plugins remain provider-managed.
