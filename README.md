# agent-sync-config

[![skills.sh](https://skills.sh/b/kelvicthrust/agent-sync-config)](https://skills.sh/kelvicthrust/agent-sync-config)

Share instructions, skills, and context between Codex and Claude Code through
native files and links. Run the tool explicitly to set up a project, synchronize
personal configuration, or check references. Existing conflicting content is
preserved.

Supports local macOS/Linux clients and Python 3.9+.
The tool is stateless: each run inspects the current filesystem. There are no
hooks, background processes, copied runtimes, launchers, custom configuration
roots, ownership manifests, or persistent application-state directories.

## Install once

Use the [Skills CLI](https://github.com/vercel-labs/skills), with Node.js/npm:

```sh
npx skills add kelvicthrust/agent-sync-config \
  --skill agent-sync-config --global --agent codex claude-code
```

This installs the default branch. For a pinned version, use the installation
command in the [release notes](https://github.com/kelvicthrust/agent-sync-config/releases).

For a local checkout, use its absolute path as the installation source. Ensure
`python3` resolves to Python 3.9+.

You do not need the latest Python version or any `pip install` step. Python 3.11+
is recommended because [Python 3.9 is past upstream support](https://devguide.python.org/versions/);
3.9 compatibility lets you use an existing interpreter without a forced upgrade.

`--global` installs the **skill** for discovery across repositories. It does not
synchronize personal configuration or select global execution. Restart an open
client if needed to discover the installed skill.

| Client | Invoke the skill |
| --- | --- |
| Codex CLI/IDE | `$agent-sync-config` |
| Codex desktop | Select `agent-sync-config` with `@` |
| Claude Code | `/agent-sync-config` |

Add your intention: “initialize this project,” “check this project,” or
“synchronize my global configuration.” The installed skill runs its bundled
script; nothing else needs to be installed to use it.

The [skills.sh badge and install counts](https://skills.sh/kelvicthrust/agent-sync-config)
use Skills CLI installation telemetry. The synchronizer reports no usage.
See [skills.sh documentation](https://www.skills.sh/docs).

## Apply it to a project

**New project:** enter the directory and invoke the skill. Without existing local
agent configuration, it asks whether to initialize the project or synchronize
global configuration. Choose project initialization, or request it explicitly.

**Existing project:** invoke the same skill. Existing local agent configuration
selects project scope; compatible instructions and ordinary skills are shared
locally. Conflicts are preserved and reported. Global installation never causes
project execution to synchronize your personal configuration.

From a checkout:

```sh
./bin/agent-sync-config --scope project --project /path/to/repo
./bin/agent-sync-config check --scope project --project /path/to/repo
```

From a typical Skills CLI installation:

```sh
python3 ~/.agents/skills/agent-sync-config/scripts/agent_sync_config.py \
  --scope project --project /path/to/repo
python3 ~/.agents/skills/agent-sync-config/scripts/agent_sync_config.py \
  check --scope project --project /path/to/repo
```

If your installer uses another location, use that installed script instead.
The checkout's command and installed script support the same arguments.

## Synchronize personal configuration

Ask the skill explicitly to synchronize global configuration, or run:

```sh
python3 ~/.agents/skills/agent-sync-config/scripts/agent_sync_config.py --scope global
python3 ~/.agents/skills/agent-sync-config/scripts/agent_sync_config.py check --scope global
```

Global operations use native global resources and leave the current project
untouched. Project operations leave global resources untouched. Global setup is
optional; it is never a prerequisite for project setup.

## Shared layout

| Resource | Project | Global |
| --- | --- | --- |
| Instructions | `AGENTS.md`, with `CLAUDE.md` importing it | `~/.codex/AGENTS.md`, referenced by `~/.claude/CLAUDE.md` |
| Skills | `.agents/skills/<name>` | `~/.agents/skills/<name>` |
| Claude skill references | `.claude/skills/<name>` | `~/.claude/skills/<name>` |
| Context | Existing documents referenced from AGENTS.md | Existing documents referenced from personal instructions |
| MCP | `.mcp.json`, `.codex/config.toml` | `~/.claude.json`, `~/.codex/config.toml` |

A fresh project without skills or MCP needs only:

```text
repo/
├── AGENTS.md
└── CLAUDE.md            # @AGENTS.md
```

With a shared project skill:

```text
.agents/skills/review-code/SKILL.md
.claude/skills/review-code -> ../../.agents/skills/review-code
```

Codex discovers `.agents/skills` directly. Claude uses its native discovery links.
Relative project links work after relocation or cloning. `.codex` still holds
native settings and MCP when needed; it is not a second skill source.

Edit shared instructions in AGENTS.md and skills in `.agents/skills`. Both clients
see the same files through references. Add links to existing context documents,
for example `docs/architecture.md`, in the instructions; the tool does not create
a separate context store or automatically inject every referenced document.

Run sync to adopt a new compatible provider-only skill or repair references.
No background synchronization runs. New client sessions load instructions;
refresh behavior in an already-running client remains provider-specific.

## Existing content and scope rules

Claude-only instructions become AGENTS.md when compatible. Matching ordinary
skill copies can become references; differing contents are preserved and reported.
External symlinks and dependency-bearing skills require explicit reconciliation.
Portable imports are available:

```sh
./bin/agent-sync-config --scope project --project /path/to/repo \
  --import-skill /path/to/review-code
```

The synchronizer itself is always excluded from shared adoption and cannot be
imported. Its runtime, dependencies, licenses, and installer-created discovery
links stay in the original installation.

Without a scope, sync selects project mode when `.agents`, `.claude`, `.codex`,
`AGENTS.md`, `AGENTS.override.md`, `CLAUDE.md`, or `.mcp.json` exists. Fresh
interactive sync offers the scope choice. Cancellation makes no changes. Fresh
noninteractive/JSON sync returns `2` without writes; supply an explicit scope.
Unscoped check audits project scope without prompting.

Git/worktree discovery resolves the root from nested directories. Outside Git,
use the intended directory or `--project`; there is no stored project registry.
`--project-only` aliases project scope. Contradictory flags and global configuration
as a project target are rejected. Malformed configuration never selects global.

Native overrides, nested instructions, enterprise policy, system skills, plugins,
and provider settings remain intact. Clients retain their own precedence:
same-name global/project skills are not guaranteed to resolve identically.
The tool does not flatten scopes or synchronize credentials, memory, or history.

## Native MCP sharing

MCP configuration formats differ, so explicit synchronization translates the
supported portable subset between native files. There is no neutral MCP source.
A definition present on only one side can be shared; equivalent definitions need
no change. If the same server differs between providers, choose its source:

```sh
./bin/agent-sync-config --scope project --project /path/to/repo --mcp-source claude
./bin/agent-sync-config --scope global --mcp-source codex
```

An explicit native Claude-format import can also resolve definitions:

```sh
./bin/agent-sync-config --scope project --project /path/to/repo \
  --import-mcp /path/to/native-mcp.json
```

Imports affect only names in the imported file. Source selection resolves
portable same-name differences; it does not delete servers absent on one side.
Unsupported options and literal credentials are preserved and reported, not
silently discarded or copied. Unrelated settings and TOML comments are retained.
Native authentication and approvals remain independent. Reconnect clients when
required. See [MCP compatibility](docs/mcp.md).

## Checks, previews, and removal

```sh
./bin/agent-sync-config check --scope project --project /path/to/repo --json
./bin/agent-sync-config --scope global --dry-run --json
```

Checks and dry runs write nothing, including runtime state. Exit codes:
`0` success, `1` conflicts or check drift, `2` invalid input, scope selection, or
filesystem failure. Reports include the resolved scope and affected paths.
Successful repeat sync makes no further changes.

There is no removal history. Sync can repair a provider link you deliberately
deleted, and can adopt an ordinary copy that remains elsewhere. Complete skill
removal must remove the source and its provider entries through your installer.
For a Skills CLI global installation:

```sh
npx skills remove review-code --global --agent codex claude-code
npx skills remove agent-sync-config --global --agent codex claude-code
```

Removing the synchronizer leaves shared native references usable. Reinstall it
only when you need setup or checks again. The tool does not modify installer
lockfiles, manage exclusions, or perform uninstall/purge operations.

Existing conflicts remain preserved. Individual file writes are atomic; the
operation is not a transaction and has no durable backups or automatic rollback.
Run one sync at a time. Interrupted or partially completed setup can be inspected
and retried; reports do not claim historical ownership or recovery guarantees.
The tool never stages, commits, or pushes.

See [testing](docs/testing.md) for acceptance scenarios and verification, and
[future clients](docs/future-support.md) for extension boundaries.
