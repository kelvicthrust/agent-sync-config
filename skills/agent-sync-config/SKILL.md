---
name: agent-sync-config
description: Set up, check, or synchronize shared local instructions, skills, curated context, and MCP configuration across Codex and Claude Code. Use for a new repository, reported configuration drift, or a client switch without a successful automatic check.
---

# Agent Sync Config

Use the bundled deterministic tool rather than implementing synchronization with
ad hoc copying or edits to provider configuration.

From the current repository, run the script relative to this skill's installed
directory:

```sh
python3 <skill-directory>/scripts/agent_sync_config.py --project <repository>
```

The same command initializes missing configuration and reconciles existing setup.
It installs this skill, a terminal command, and machine hooks when missing. Read
the report: a nonzero result means conflict/drift (1) or an error (2).

For a check-only request, planning mode, or a read-only environment, use:

```sh
python3 <skill-directory>/scripts/agent_sync_config.py check --project <repository>
```

Preserve conflicting content. Inspect the reported files and propose a concrete
reconciliation to their canonical resources; do not force overwrite, stage, or
commit unrelated changes. Rerun after the authorized reconciliation.

Project instructions belong in `AGENTS.md`; `CLAUDE.md` imports them. Project
skills live in `.agents/skills/`, curated context in `.agents/context/`, and
shared MCP definitions in `.agents/mcp.json`. Personal configuration stays outside
the repository. Do not copy credentials, conversations, automatic memory, plugin
caches, or provider-specific capabilities into shared files.

Honor the managed AGENTS.md section. Read updated project/personal instructions
when switching clients or when hooks indicate changed instructions. Hook file
presence does not prove trust or execution; explain reported trust/restart steps.

Portable resources from plugins require explicit adoption using `--import-skill`
or `--import-mcp`; resolve plugin dependencies first. The tool does not install,
update, or translate plugins. New coding clients require tested integrations;
initial support is local Codex and Claude Code on macOS/Linux.
