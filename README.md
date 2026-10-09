# agent-sync-config

[![skills.sh](https://skills.sh/b/kelvicthrust/agent-sync-config)](https://skills.sh/kelvicthrust/agent-sync-config)

Share local agent instructions, skills, curated context, and MCP definitions
across Codex and Claude Code. One repeatable command initializes a new repository
or reconciles an existing one, while preserving conflicting content.

**v0.3.0 preview (not yet released).** Initial support targets macOS/Linux with Python 3.11+ and
local Codex/Claude Code clients. Ensure `python3` resolves to Python 3.11+ in
the terminal and native hook environment. See [testing and compatibility](docs/testing.md)
for verified capabilities and limits.

## Install once

Install the skill using the [skills CLI](https://github.com/vercel-labs/skills)
(requires Node.js/npm):

```sh
npx skills add kelvicthrust/agent-sync-config \
  --skill agent-sync-config --global --agent codex claude-code
```

To install the previously released v0.2.0 preview (without the lifecycle commands below):

```sh
npx skills add https://github.com/kelvicthrust/agent-sync-config/tree/v0.2.0 \
  --skill agent-sync-config --global --agent codex claude-code
```

See [v0.2.0 release notes](https://github.com/kelvicthrust/agent-sync-config/releases/tag/v0.2.0)
for changes and migration steps. The unversioned command above follows the
repository's default branch; creating a release does not change that source.

For a local checkout, replace `kelvicthrust/agent-sync-config` with its absolute
path. `--global` here installs the **skill** for discovery in any project. It does
not synchronize your personal settings or initialize projects. You do not need
to install it separately in every repository. Restart an open client to rediscover it.

View [install counts on skills.sh](https://skills.sh/kelvicthrust/agent-sync-config).
The badge and leaderboard use anonymous installation telemetry from the skills
CLI; running the synchronizer itself does not report usage. See the
[skills.sh documentation](https://www.skills.sh/docs) for how counts are tracked.

Use the same skill in either client:

| Client | Skill invocation |
| --- | --- |
| Claude Code | `/agent-sync-config` |
| Codex CLI/IDE | `$agent-sync-config` |
| Codex desktop | Type `@` and select `agent-sync-config` |

If Codex lists both project and global copies, select the project copy from its
skill picker for local work. In a noninteractive Codex request, an explicit
`[$agent-sync-config](/absolute/project/.agents/skills/agent-sync-config/SKILL.md)`
reference disambiguates the copy. Both copies enforce the same scope rules.

The skill runs its bundled Python script, so the terminal command does not have
to be installed first. Add your intention to the request, for example
`$agent-sync-config synchronize my global configuration` or
`/agent-sync-config initialize this project`.

## Synchronize your global configuration

Explicitly ask the skill to synchronize global configuration. From a checkout,
the equivalent terminal command is:

```sh
./bin/agent-sync-config --scope global
```

This adopts compatible existing personal instructions, skills, and MCP definitions
into one personal source (default `~/agent-config/`) and links/renders the global
Codex and Claude resources from it. Conflicting existing content is preserved and
reported. Provider-only settings, plugins, credentials, history, and automatic
memory stay provider-managed; they are not all interchangeable.

Global setup installs `~/.local/bin/agent-sync-config` and global audit-only hooks.
Add `~/.local/bin` to your PATH if needed. After that, from any directory:

```sh
agent-sync-config --scope global        # initialize or sync personal resources
agent-sync-config check --scope global  # audit personal resources without writes
```

Global operations do not read, initialize, or reconcile the current project's
configuration. Edit `~/agent-config/AGENTS.md`, `skills/`, or `mcp.json`, then run
explicit global sync when needed. Global hooks can report drift but never repair it.

## Apply it to a project

**New project:** enter its directory and invoke the skill. If no local agent
configuration exists, it asks whether to initialize this project or synchronize
global configuration. Choose project initialization to create local shared
resources. You can also request project initialization explicitly to skip the
choice. Global setup is optional and is never a prerequisite for project setup.

**Existing project:** enter its directory and invoke the same skill. It adopts
and reconciles project resources only, preserving existing instructions, settings,
unrelated hooks, and conflicts. Existing `.agents`, `.claude`, `.codex`, `AGENTS.md`,
`AGENTS.override.md`, `CLAUDE.md`, or `.mcp.json` selects project scope. Malformed
configuration produces an error; it never redirects the operation to global scope.

From a terminal, use the same commands for first setup and later synchronization:

```sh
agent-sync-config --scope project        # initialize or sync this project
agent-sync-config check --scope project  # audit this project without writes
```

Or from a local checkout before installing a terminal wrapper:

```sh
./bin/agent-sync-config --scope project --project /path/to/your-repo
./bin/agent-sync-config check --scope project --project /path/to/your-repo
```

Edit project instructions in `AGENTS.md`, skills in `.agents/skills/`, curated
context in `.agents/context/`, and MCP definitions in `.agents/mcp.json`. Both
clients use those canonical resources. Repeat the same project command after
changes or when a hook reports drift. The managed section in AGENTS.md explains
when to invoke the skill; project setup includes its runtime and licenses.

Setup installs SessionStart/UserPromptSubmit hooks in the project. Review Codex
hooks through `/hooks`; restart Claude Code after initial installation. Native
trust, permissions, and disabled-hook controls still apply. When switching clients,
a trusted project hook checks the local resources before continuing. Run the
skill/check explicitly if hooks are disabled, untrusted, or report drift. The tested
Codex payloads lack sandbox policy, so their hooks audit and explicit sync repairs.

## Scope rules and reports

Without `--scope`, sync uses project scope when a local marker exists. A fresh
project in an interactive terminal offers the same project/global choice as the
skill. Canceling makes no changes. Fresh noninteractive or `--json` sync exits `2`
with a scope-selection message before locks or writes; provide an explicit scope.

Unscoped `check` audits project scope without prompting or writing. Global checks
always require `--scope global`. The project root uses Git/worktree discovery,
then managed-project discovery for repositories without Git.

`--project-only` remains an alias for `--scope project`. Contradictory scopes,
`--project` with global scope, and `--personal-root` outside global scope are
rejected. Your home, personal source, and native global configuration directories
cannot be project targets.

`check` is strictly read-only, including runtime state. Reports include the resolved
scope; global reports have no project target. Exit codes: `0` success, `1` conflicts
or read-only drift, `2` invalid configuration, missing scope selection, lock
contention, or filesystem error. Use `--json` for structured reports.

The tool never stages files, commits, or pushes. Individual configuration writes
are atomic; the overall operation is not a transaction. Nonconflicting changes
may be applied even when another resource has a conflict. For disposable homes,
see [testing](docs/testing.md).

## What appears in a project

For a fresh repository without provider-specific files:

```text
your-project/
├── AGENTS.md                 # shared project instructions + managed guidance
├── CLAUDE.md                 # @AGENTS.md
├── .agents/
│   ├── agent-sync.json       # layout version, managed links, last rendered MCP
│   ├── context/              # curated project docs
│   └── skills/
│       └── agent-sync-config/ # packaged setup skill, runtime, licenses
├── .claude/
│   ├── settings.json         # merged project hooks
│   └── skills/               # per-skill relative links
└── .codex/
    └── hooks.json            # merged project hooks
```

The context folder stays empty until you add resources or setup adopts existing
ones; Git does not track empty folders. The packaged setup runtime allows project
hooks to work after relocation or cloning, including nested directories and
worktrees, without a fixed machine path. With another project skill:

```text
.agents/skills/review-code/SKILL.md
.claude/skills/review-code -> ../../.agents/skills/review-code
```

Codex reads `.agents/skills/` directly. Setup also adopts an existing legacy
`.codex/skills/` directory and maintains its per-skill links, but does not create
that duplicate directory in a fresh project.

Existing curated `.claude/context/` and `.codex/context/` content can be adopted
into `.agents/context/`. After conflict-free adoption, those existing directories
become relative links. New projects reference canonical context from AGENTS.md;
there is no automatic injection of every context document or memory directory.

If shared MCP servers are configured, setup adds:

```text
.agents/mcp.json       # canonical definitions
.mcp.json              # generated Claude MCP configuration
.codex/config.toml     # generated Codex MCP tables
```

Commit project instructions, canonical resources, the project manifest, relative
links, project hooks, the packaged setup runtime/licenses, and nonsecret generated
MCP configuration. Personal defaults, credentials, backups, and runtime cache remain outside the project.

## Instructions and existing resources

`AGENTS.md` is the canonical project instruction file. `CLAUDE.md` imports it.
Setup adds a delimited managed section explaining when to run the skill, where
to edit shared resources, and how to run the read-only check. Subsequent runs
update that section while preserving surrounding instructions.

If only CLAUDE instructions exist, setup adopts their content. If both providers
have different instructions, it preserves the differing files and reports the
conflict. Reconcile their content into AGENTS.md, then replace CLAUDE.md with its
import wrapper and rerun. Existing AGENTS.override.md files are reported because
they can mask shared instructions. Linked instruction sources and external skill
dependencies require explicit reconciliation rather than forced replacement.

Setup verifies the installed skill's entrypoints. A reference inside AGENTS.md
does not install a skill or guarantee that a model follows it.

## Personal defaults

Personal resources default to `~/agent-config/`; use
`--scope global --personal-root /path` on the first global setup to adopt another
location. Later runs reuse the registered root and reject silently introducing a second source of truth.

```text
~/agent-config/
├── AGENTS.md
├── skills/
│   └── agent-sync-config/
├── mcp.json                 # only when personal MCP servers exist
└── .agent-sync.json         # machine-specific ownership/install state
```

The global Codex AGENTS.md and Claude CLAUDE.md link to the personal AGENTS.md.
Global skill entrypoints link to the personal skills. Existing system skills,
provider-only settings, private project configuration, and plugins are preserved.
Different existing personal instruction files require reconciliation; they are
not assumed to have already been synchronized.

Version personal instructions, skills, and nonsecret MCP definitions separately
from this tool's repository. Keep `.agent-sync.json` machine-local. Runtime
registration, metadata cache, synchronization lock, and private backups live in
`~/.local/state/agent-sync-config/`.

## Remove a shared global skill

Use the synchronizer for immediate removal of both the shared source and its
owned installations:

```sh
agent-sync-config remove-skill review-code --scope global --dry-run
agent-sync-config remove-skill review-code --scope global
```

The second command lists the affected paths and asks for confirmation. For an
explicit cleanup in a script, add `--yes`; `--json` alone does not confirm it.
Removal deletes the recorded source under the personal `skills/` directory,
unchanged managed entrypoints, and its matching Skills CLI lock entry. Modified
sources, redirected links, conflicting copies, and changed installation records
block cleanup and remain untouched. Synchronize intentional source edits first
to accept their current content, then review removal again.

An intentional removal is recorded in `.agent-sync.json`, so future syncs do not
adopt leftover provider copies. Explicit `--import-skill /path/to/skill` adoption
can reinstall it. A new installation through `npx skills add` is reported for
acceptance rather than silently adopted.

You can still remove an installed skill through the Skills CLI:

```sh
npx skills remove review-code --global --agent codex claude-code
agent-sync-config --scope global
```

When a previously managed entrypoint or observed installation record disappears,
interactive global sync offers **complete removal**, **restore installation**,
or **cancel**. Until you choose, it leaves that skill's shared source in place
and stops recreating its links. Removing only one provider entrypoint also asks
for a decision; separate provider exclusions are not supported. Hooks and
read-only checks report the pending decision without changing personal files.
JSON/noninteractive sync returns exit code `1`; `--yes` does not select removal
or restoration. Unrelated resources may still synchronize.

The Skills CLI has no callback into this tool. Direct `npx skills remove` therefore
needs this later reconciliation; it cannot immediately clean our shared source.
A no-op CLI removal that finds no installed skill is not treated as a removal.
Skills CLI metadata integration currently supports version 3 lockfiles (tested
with CLI 1.7.1). Unsupported or malformed lockfiles are reported and preserved.

## Uninstall global synchronization

Remove the integration while keeping your remaining configuration usable:

```sh
agent-sync-config uninstall --scope global --dry-run
agent-sync-config uninstall --scope global
```

This turns owned global instruction links into ordinary files, preserves remaining
skills as ordinary directories in `~/.agents/skills`, and points Claude and any
existing legacy Codex skill links there. Native MCP definitions remain in place.
It removes only owned global hooks, the terminal wrapper, the setup skill, and
global registration/cache entries. Project configuration and registration,
unrelated settings/hooks/plugins, system skills, and private backups stay intact.
Restart clients after uninstalling to refresh their discovery and hooks.

By default, retained personal sources have a detached manifest and no active
global synchronization. To also delete the redundant owned shared sources,
choose the purge option on the uninstall command:

```sh
agent-sync-config uninstall --scope global --purge-shared-sources --dry-run
agent-sync-config uninstall --scope global --purge-shared-sources
```

Purge verifies the native replacements before deleting owned shared sources.
It preserves unrelated files and version-control data in the personal directory
and removes directories only when empty. It is not secure erasure: private
backups remain available. Conflicts, dependency symlinks, or nested private version-control data block
uninstall/purge before changes when native preservation or deletion is unsafe.
An interrupted uninstall can be retried from another installed copy or this
checkout, using the same purge choice and home; ownership recovery is retained
until cleanup finishes. Removing `agent-sync-config` with `remove-skill` directs
you to `uninstall` instead.

If you already uninstalled without purge, the terminal wrapper is gone. Run the
bundled script from this checkout to clean retained sources afterward:

```sh
python3 skills/agent-sync-config/scripts/agent_sync_config.py \
  uninstall --scope global --purge-shared-sources
```

Lifecycle commands currently support global scope only. Project uninstall and
global update reconciliation are separate work. Avoid unrestricted
`npx skills remove` inside this publisher repository: its shipped `skills/`
directory overlaps another client's installation directory. Our lifecycle
commands target recorded global resources and leave the publisher checkout alone.

## Upgrade to the 0.3.0 lifecycle behavior

Install the updated skill and run its updated bundled script once to record
ownership, upgrade the global runtime, and refresh the terminal wrapper:

```sh
python3 ~/.agents/skills/agent-sync-config/scripts/agent_sync_config.py --scope global
agent-sync-config --version  # should report 0.3.0
```

From this local checkout, use `./bin/agent-sync-config --scope global` instead.
Use the updated script/skill for this first upgrade; an existing terminal wrapper
may still execute 0.2.0. Existing missing entrypoints are reported for a decision
rather than repaired automatically. Audits interpret older
manifests without writing an upgrade. Review native hook trust and restart clients
when updating the runtime. This checkout is the 0.3.0 preview; the published
v0.2.0 tag does not contain these lifecycle commands.

## Automatic checks and limits

Project and global SessionStart/UserPromptSubmit hooks run separate scoped checks.
Project hooks use the repository runtime; global hooks audit personal resources
independently of the current project. Healthy warm prompt checks are silent.
New/resumed sessions and changed instructions receive a reminder to read current
guidance. Only project hooks can repair, subject to native permissions.

The warm path uses directory entries, stat/readlink metadata, and a cached
fingerprint. It does not traverse project source code, run git diff, download
packages, or contact providers. Changed MCP configuration is parsed semantically.

**Claude Code project hooks:** recognized writable prompt modes can repair
missing managed links, remove unchanged obsolete links, and render unambiguous shared MCP changes.
Planning mode and unknown permission modes only report required repairs.

**Codex:** tested versions 0.142.0, 0.160.0, and 0.162.0-alpha.2 omit sandbox
policy in the hook payload. They can report `bypassPermissions` even with a read-only sandbox.
Hooks therefore audit and report drift by default. They repair only when a payload explicitly
identifies a writable sandbox. Run the skill/tool to reconcile drift when edits
are allowed; do not interpret a hook's permission mode alone as write access.

Hooks never install or upgrade the tool automatically, recreate missing shared
instructions, or overwrite conflicting content. Locks, registration, metadata
caches, and private backups live outside projects.
Runtime state is the only permitted outside-project write during project operations;
personal/provider configuration stays unchanged. Metadata caching is allowed
during hook audits; set `AGENT_SYNC_READ_ONLY=1` for strict
no-cache/no-repair hook execution. CLI `check` is always read-only.

Native trust, disabled hooks, safe modes, managed policies, and client flags can
prevent hook execution. Setup preserves these controls and explains the native
trust step; file presence cannot prove hooks are enabled. MCP changes may require
server reconnection or a client restart. No hot-reload guarantee is made.

## Upgrading from 0.1.0

Install the updated skill, then explicitly request global sync once (or run its
updated bundled script with `--scope global`). This upgrades the installed global
runtime and replaces owned legacy global handlers with audit-only handlers.
Review changed Codex hook trust and restart clients as needed.

Project setup reports a required legacy global upgrade but leaves it untouched.
Old registry entries that allowed combined synchronization do not authorize the
new engine to modify personal configuration. Until explicitly upgraded, old
installed global handlers can still run the old combined behavior. Then run
project setup in each repository to package its runtime and install local hooks.

## MCP and plugins

Use the neutral definitions documented in [MCP configuration](docs/mcp.md).
Provider config is generated output. Manual edits to a managed definition are
preserved and reported using the last generated state. Unmanaged servers and
settings remain untouched. Removed shared servers are removed only when their
native definitions still match the recorded output.

Credential values are not resolved or copied. Use named environment references;
authenticate OAuth servers independently in each client. Unsupported fields are
reported, never silently dropped.

Plugins remain provider-managed. Their install/update lifecycle, hooks, agents,
commands, LSPs, styles, caches, and credentials are not mirrored. Explicitly adopt
a self-contained portable skill or Claude-format MCP file with:

```sh
agent-sync-config --scope project --import-skill /path/to/portable-skill
agent-sync-config --scope project --import-mcp /path/to/mcp.json
```

Use `--scope global` instead to import into personal resources. Imports never
escalate scope automatically. Inspect dependencies first. Dependency symlinks
and recognizable plugin-root references block skill adoption; this is not a complete dependency analyzer.
Native plugin MCP servers may duplicate an explicitly imported server. Review
the clients' loaded-server lists during adoption; setup does not scan plugin
caches or rewrite plugin configuration to hide duplicates.

## Testing and compatibility

```sh
python3 -m unittest discover -s tests -v
python3 tests/benchmark.py
python3 tests/provider_smoke.py
```

See [reproducible tests and compatibility](docs/testing.md) and
[future client support](docs/future-support.md). Cursor and Grok integrations
are not implemented. Desktop GUI and cloud behavior have not been verified.

## Provider references

- [Codex instructions](https://learn.chatgpt.com/docs/agent-configuration/agents-md),
  [skills](https://learn.chatgpt.com/docs/build-skills),
  [hooks](https://learn.chatgpt.com/docs/hooks),
  [MCP](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).
- [Claude instructions](https://code.claude.com/docs/en/memory),
  [skills](https://code.claude.com/docs/en/skills),
  [hooks](https://code.claude.com/docs/en/hooks),
  [MCP](https://code.claude.com/docs/en/mcp).

MIT licensed; the license also travels with the installed skill. The skill bundles
unmodified tomlkit 0.13.3 with its MIT license and notice in `scripts/vendor/`;
no runtime pip installation is required.
