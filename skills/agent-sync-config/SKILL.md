---
name: agent-sync-config
description: Set up or check shared native instructions, skills, context references, and MCP configuration for Codex and Claude Code in a project or explicitly selected global scope.
---

# Agent Sync Config

Use the bundled deterministic tool with Python 3.9+ to inspect current native
files and establish shared references. Installing this skill globally makes it available in any
repository; installation never selects execution scope. Keep the tool in its
installer-owned location. Never copy it into shared configuration or projects.

## Select the scope

Honor an explicit project/global request. Global operations always require
`--scope global` and omit `--project`. Never escalate a project request because
resources are missing, malformed, or conflicting.

For an ordinary setup/sync request without an explicit scope, run:

```sh
python3 <skill-directory>/scripts/agent_sync_config.py --project <repository> --json
```

Existing local `.agents`, `.claude`, `.codex`, `AGENTS.md`, `AGENTS.override.md`,
`CLAUDE.md`, or `.mcp.json` selects project scope. Git/worktree discovery resolves
the root; outside Git, use the explicitly selected/current directory.

A fresh noninteractive request returns exit code 2 and `selection_required: true`
without writes. Ask whether to initialize this project or synchronize global
configuration, wait for the choice, then use the explicit scope. Cancellation
makes no changes. If the request already specifies the scope, invoke it directly:

```sh
python3 <skill-directory>/scripts/agent_sync_config.py --scope project --project <repository>
python3 <skill-directory>/scripts/agent_sync_config.py --scope global
```

## Check and share

For checks, planning mode, or read-only environments, audit without writes:

```sh
python3 <skill-directory>/scripts/agent_sync_config.py check --scope project --project <repository>
python3 <skill-directory>/scripts/agent_sync_config.py check --scope global
```

Unscoped check audits project scope. `--dry-run` previews changes without writes.
Reports name the scope and paths; global reports have no project target. Exit
codes are 0 for success, 1 for conflicts/check drift, and 2 for invalid input,
scope selection, or filesystem failure. Read the report before claiming success.

Project instructions live in AGENTS.md; CLAUDE.md imports them. Global shared
instructions live in ~/.codex/AGENTS.md, with ~/.claude/CLAUDE.md referencing them.
Skills live in .agents/skills (or ~/.agents/skills globally); Claude uses relative
per-skill links. Do not add duplicate .codex/skills entries. Reference existing
context documents from the shared instructions; create no custom context store.

Instruction and skill edits are shared through references immediately. Explicit
sync adopts compatible new ordinary skills or repairs references. Preserve
conflicting files, external dependencies, native overrides, system skills,
provider-managed skills, plugin settings, and unrelated hooks.

MCP uses native .mcp.json and .codex/config.toml in projects, or ~/.claude.json
and ~/.codex/config.toml globally. No neutral MCP file or historical baseline is
stored. Differing definitions require a user-selected source:

```sh
python3 <skill-directory>/scripts/agent_sync_config.py --scope project --project <repository> --mcp-source claude
python3 <skill-directory>/scripts/agent_sync_config.py --scope global --mcp-source codex
```

Ask which source to use unless the user already selected it. Explicit
--import-mcp accepts native Claude-format mcpServers; --import-skill adopts a
self-contained ordinary skill into the selected scope. Do not translate or copy
credentials, plugin runtime dependencies, provider-specific settings, memory,
conversations, or caches. The synchronizer cannot import itself.

## Installation, removal, and legacy resources

The tool stores no ownership manifest, registry, history, backups, persistent
locks, or recovery state. It installs no hooks or terminal launcher. Each run
inspects current files; missing references do not reveal removal intent.
Explicit sync can repair a removed provider link. Complete removals have no
hidden shared source to restore; a remaining ordinary copy can be adopted again.

Use the user's installer for installation, updates, and removal. For Skills CLI,
remove the tool with `npx skills remove agent-sync-config --global --agent codex
claude-code`. Removing the tool leaves native shared references usable.

Legacy custom sources, manifests, setup packages, hooks, aliases, and external
instruction links are preserved and reported. Reconcile native replacements and
cleanup explicitly; never run retired uninstall/remove-skill/purge commands or
invent ownership-based deletion. Never stage, commit, or push unless requested.
