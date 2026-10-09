---
name: agent-sync-config
description: Set up, check, or synchronize shared instructions, skills, curated project context, and MCP configuration across Codex and Claude Code. Use for a new repository, configuration drift, reference drift, an explicit global configuration request, or removing/uninstalling shared global skills.
---

# Agent Sync Config

Use the bundled deterministic tool rather than implementing synchronization with
ad hoc copying or edits to provider configuration. Installing this skill globally
makes it available in any repository; installation does not select execution scope.

## Choose the scope

Honor an explicit project/global request. Global synchronization always requires
`--scope global` and must omit `--project`. Never escalate a project operation to
global scope because resources are missing, malformed, or conflicting.

For an ordinary setup/sync request without a scope, run:

```sh
python3 <skill-directory>/scripts/agent_sync_config.py --project <repository> --json
```

The tool resolves the Git/worktree or managed-project root. If that root has
`.agents`, `.claude`, `.codex`, `AGENTS.md`, `AGENTS.override.md`, `CLAUDE.md`, or
`.mcp.json`, it synchronizes project scope only. An error never selects global.

For a fresh project, the report returns exit code 2 with `selection_required: true`
and makes no changes. Ask in chat: “Initialize shared configuration in this
project, or synchronize your global configuration?” Wait for the user's choice,
then run the chosen explicit command below. Do not infer approval from silence.
Cancellation makes no changes. If the user already explicitly requested project
initialization or global synchronization, use that scope directly.

```sh
python3 <skill-directory>/scripts/agent_sync_config.py --scope project --project <repository>
python3 <skill-directory>/scripts/agent_sync_config.py --scope global
```

Project setup creates shared configuration, relative skill links, and a small
ownership manifest. It never installs this skill, a tool runtime, or automatic
hooks in the project. Global setup manages personal resources and the terminal
wrapper without automatic hooks. The tool stays installed on the machine.
The same scoped command initializes missing resources and reconciles existing setup.

## Check and reconcile

For check-only requests, planning mode, or read-only environments, run an audit.
Unscoped checks audit the project without asking or writing; global checks need
an explicit global scope:

```sh
python3 <skill-directory>/scripts/agent_sync_config.py check --scope project --project <repository>
python3 <skill-directory>/scripts/agent_sync_config.py check --scope global
```

Read the report: success is 0, conflicts/read-only drift is 1, and invalid input or
required scope selection is 2. Reports name the resolved scope; global reports
have no project target. Preserve conflicting content and propose a concrete
reconciliation to its canonical resources. Do not force overwrite, stage, or
commit unrelated changes. Rerun after an authorized reconciliation.

Project instructions belong in `AGENTS.md`; `CLAUDE.md` imports them. Project
skills live in `.agents/skills/`, curated context in `.agents/context/`, and MCP
in `.agents/mcp.json`. Personal instructions, skills, and MCP live in the registered
personal source (default `~/agent-config/`) and change only through global sync.
Use `--personal-root` only with global scope. `--project-only` remains a project
scope alias. Do not copy credentials, conversations, automatic memory, plugin
caches, or provider-specific capabilities into shared files.

Instruction and skill edits are shared immediately through imports/links. Invoke
sync to adopt new resources, repair references, reconcile conflicts, or regenerate
MCP output. No prompt hook or automatic repair is installed. The global Codex
skill entrypoint is ~/.agents/skills; do not create duplicate ~/.codex/skills links.

Explicit project sync migrates recorded unchanged legacy project hooks, packaged
setup runtime, and its owned discovery links. Explicit global sync separately
retires recorded legacy global hooks and verified owned Codex aliases. Preserve
modified or unowned artifacts, disabled-hook/trust controls, and system skills.
Explain reported migration conflicts without bypassing native trust. Read-only
checks never apply migration. A legacy global hook's message is not evidence that
a project operation synchronized global files; inspect the resolved scope and
reported paths before diagnosing a scope violation.

Portable resources from plugins require explicit adoption with `--import-skill`
or `--import-mcp` into the selected scope; resolve dependencies first. The tool
does not install, update, or translate plugins. Additional clients require tested
integrations; initial support is local Codex and Claude Code.

## Remove global skills or uninstall

Global lifecycle commands require explicit `--scope global`. Preview concrete
paths before cleanup, then honor the user's removal/uninstall request:

```sh
python3 <skill-directory>/scripts/agent_sync_config.py remove-skill <name> --scope global --dry-run --json
python3 <skill-directory>/scripts/agent_sync_config.py remove-skill <name> --scope global --yes --json
python3 <skill-directory>/scripts/agent_sync_config.py uninstall --scope global --dry-run --json
python3 <skill-directory>/scripts/agent_sync_config.py uninstall --scope global --yes --json
```

`--yes` confirms the specified cleanup; use it when the user already authorized
that operation. It does not decide ambiguous external removals. To delete
redundant owned personal sources after preserving native configuration, add
`--purge-shared-sources` to uninstall only when requested. Uninstall preserves
native instructions, remaining skills, MCP settings, unrelated hooks, and projects.
It removes the owned setup skill, any recorded legacy global handlers, wrapper,
and registration without recreating legacy Codex aliases.
Use uninstall rather than remove-skill for agent-sync-config itself.

Direct `npx skills remove --global` cannot delete our retained personal source.
A later sync/check reports `pending_removals` and suppresses reinstallation.
For a reported removal, ask whether to complete removal, restore the installation,
or cancel. Complete ordinary removal with remove-skill; complete setup-skill
removal with uninstall. For restoration, run interactive terminal sync when
available, or explicitly import the retained shared skill source after the user
chooses restoration. A reported reinstall can be accepted through explicit
--import-skill adoption from its new ordinary source. Never infer the answer
from --yes or a missing file. Checks remain strictly read-only.

Conflicts block deletion. Preserve them and explain the paths requiring
reconciliation. An interrupted uninstall keeps recovery metadata; retry with
the original purge choice from another runtime or checkout. Private backups
remain available; purge is not secure erasure.
