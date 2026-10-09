---
name: agent-sync-config
description: Set up, check, or synchronize shared instructions, skills, curated project context, and MCP configuration across Codex and Claude Code. Use for a new repository, configuration drift, a client switch, or an explicit global configuration request.
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

Project setup packages this skill's runtime and licenses in the repository and
installs native project hooks. Global setup manages personal resources, installs
the terminal wrapper, and installs audit-only global hooks. The same scoped command
initializes missing resources and reconciles existing setup.

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

Honor the managed AGENTS.md section. Read updated instructions when switching
clients or when hooks indicate changed instructions. Project hooks audit and may
repair project resources when native permissions permit. Global hooks only report
personal drift: repair requires explicit global sync. Hook file presence does not
prove trust or execution; explain reported native trust/restart steps.

For installations predating 0.2.0, project setup may report legacy global hooks.
Explain the one-time explicit global upgrade; do not perform it unless the user
chooses global synchronization. Existing project registration does not authorize
global changes.

Portable resources from plugins require explicit adoption with `--import-skill`
or `--import-mcp` into the selected scope; resolve dependencies first. The tool
does not install, update, or translate plugins. Additional clients require tested
integrations; initial support is local Codex and Claude Code.
