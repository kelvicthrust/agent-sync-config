---
name: agent-sync-config
description: Set up or check shared native instructions, skills, context references, compatible Claude commands and agents, and MCP configuration for Codex and Claude Code in a project or explicitly selected global scope.
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
Reports inventory resources with source/destination, disposition, and compatibility;
name the scope and paths; global reports have no project target. Exit
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

## Claude-first resources

Ordinary sync performs supported sharing and adaptation automatically. Do not add
`convert`, `--reference-claude`, replacement flags, new state, or custom roots.

- Portable skills move with supporting files to `.agents/skills` and receive Claude
  links. Simple instruction-only commands become valid shared skills; the legacy
  command is removed only after its replacement and Claude link are verified.
- Commands with arguments, shell preprocessing, execution controls, plugin
  variables, nested names, or unsafe relocation dependencies remain reference-only.
- Simple Claude agents retain their originals and get native `.codex/agents/*.toml`
  reference definitions. Flat name/description and optional model: inherit qualify.
  Codex reads the current original instruction body before acting; ordinary context
  paths retain their source context. Body edits need no regeneration. Complex
  metadata, model overrides, other execution controls, built-in names, external
  links, and differing native definitions remain conflicts.
- Claude rules, workflows, and output styles stay in `.claude`. Generated guidance
  in shared instructions tells Codex when to consult them, retaining rule conditions.
  These are content references, not activation of Claude loaders or execution controls.
  Workflow scripts are never run. Unsupported permissions must never be weakened.
- Settings, hooks, plugins, memory, and credentials remain provider-specific.
  Do not reference them as portable instructions or emulate their controls.

Use the report's `resources` entries to explain shared native behavior,
native reference agents, and review-only content references. Informational
limitations do not fail sync; conflicts and unresolved adaptations return 1.
Metadata, tool declarations, or generated native fields that differ need source
selection; body edits are shared through reading. Preserve additional native
settings. Missing original prompts are reported; native definitions are not deleted.
Never infer ownership or which edit is newer. Reconcile only with authorization.
Do not claim that filesystem conversion proves model compliance. Native agent
support depends on the client's version and existing controls.

Do not invent `.agents/rules`, `.agents/agents`, a workflow runtime, or copy this
skill into a target project. Project references stay repository-relative; global
references stay within the explicit personal scope. Ordinary sync remains offline.

### Review tool-bearing agents

For agent-bearing repositories, preview with `--dry-run --json` before sync. If a
report requests review of a flat Claude `tools` declaration, show the named source
and destination and explain: the Claude allowlist is **not translated or enforced**;
the reference agent uses existing native Codex permissions. Approval does not
authorize external actions, connect services, or bypass native trust/approvals.
Ask whether to approve those named references, skip them, or cancel. Honor an
existing explicit approval; do not infer blanket acceptance from a sync request.
After approval, pass each accepted name to the same sync command:

```sh
python3 <skill-directory>/scripts/agent_sync_config.py --scope project --project <repository> \
  --accept-agent-reference performance-coach
```

The option is repeatable and works in explicit global scope too. JSON/noninteractive
sync never prompts; unapproved agents return 1 while unrelated resources can sync.
Interactive terminal sync offers named review before writes; cancellation writes
nothing. Checks never accept approvals or write. Dry runs may preview named
approvals. Matching reference definitions need no renewed approval. Changed tools
or native generated fields remain conflicts even with this option; it never forces
an overwrite. Do not claim the original Claude allowlist protects the Codex agent.

## MCP

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
