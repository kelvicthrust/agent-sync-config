# agent-sync-config

Share local agent instructions, skills, curated context, and MCP definitions
across Codex and Claude Code. One repeatable command initializes a new repository
or reconciles an existing one, while preserving conflicting content.

**v0.1.0 preview.** Initial support targets macOS/Linux with Python 3.11+ and
local Codex/Claude Code clients. See [testing and compatibility](docs/testing.md)
for verified capabilities and limits.

## Install and set up

Install the skill from GitHub using the [skills CLI](https://github.com/vercel-labs/skills)
(requires Node.js/npm):

```sh
npx skills add kelvicthrust/agent-sync-config \
  --skill agent-sync-config --global --agent codex claude-code
```

For a local checkout, replace `kelvicthrust/agent-sync-config` with its absolute
path. Installing the skill makes it discoverable; invoke it inside a project to
configure that project and the shared personal resources.

From a clone of this project, preview the changes for another repository:

```sh
./bin/agent-sync-config check --project /path/to/your-repo
```

Then initialize or synchronize it:

```sh
./bin/agent-sync-config --project /path/to/your-repo
```

The default operation configures the current machine **and** the selected
project. It installs the setup skill and `~/.local/bin/agent-sync-config`, and
merges session/prompt hooks into the providers' global configuration. Add
`~/.local/bin` to your shell's PATH if it is not already there. Restart an open
client so it can rediscover the skill and hooks. Review Codex hooks through
`/hooks`; setup does not bypass native trust or server-approval requirements.

To configure just a project without installing personal resources or hooks:

```sh
./bin/agent-sync-config --project /path/to/your-repo --project-only
```

To verify in a disposable home, see [testing](docs/testing.md).
The tool never stages files, commits, or pushes changes. Changes to individual
configuration files are atomic; the overall operation is not a transaction.
Nonconflicting changes may be applied even when another resource has a conflict.

## Everyday use

Once installed, open any repository and invoke the same setup skill:

| Client | Skill invocation |
| --- | --- |
| Claude Code | `/agent-sync-config` |
| Codex CLI/IDE | `$agent-sync-config` |
| Codex desktop | Type `@` and select `agent-sync-config` |

The skill runs its bundled Python script, so it also works before the terminal
command is on PATH. Its script and vendored TOML dependency travel with the skill.
There is no separate installation versus initialization workflow.

From a terminal inside the project:

```sh
agent-sync-config        # initialize or synchronize
agent-sync-config check  # read-only audit
```

`check` never changes managed files, installs resources, or writes runtime state.
Exit codes are `0` for success, `1` for conflicts or read-only drift, and `2` for
invalid configuration, an active synchronization lock, or a filesystem error.
Use `--json` for a structured report.

## What appears in a project

For a fresh repository without provider-specific files:

```text
your-project/
├── AGENTS.md                 # shared project instructions + managed guidance
├── CLAUDE.md                 # @AGENTS.md
├── .agents/
│   ├── agent-sync.json       # layout version, managed links, last rendered MCP
│   ├── context/              # curated project docs
│   └── skills/               # canonical project skills
└── .claude/
    └── skills/               # per-skill relative links
```

The context and skills folders stay empty until you add resources or setup adopts
existing ones. Git does not track empty folders. With a project skill:

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
links, and nonsecret generated MCP configuration. Personal defaults, credentials,
backups, and runtime cache remain outside the project.

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

Personal resources default to `~/agent-config/`; use `--personal-root /path` on
the first setup to adopt another location. Later runs reuse the registered root
and reject silently introducing a second source of truth.

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

## Automatic checks and limits

Global SessionStart and UserPromptSubmit hooks run the same engine. They are
silent for unregistered repositories and healthy warm prompt checks. New/resumed
sessions and changed instructions receive a reminder to read current guidance.

The warm path uses directory entries, stat/readlink metadata, and a cached
fingerprint. It does not traverse project source code, run git diff, download
packages, or contact providers. Changed MCP configuration is parsed semantically.

**Claude Code:** recognized writable prompt modes can repair missing managed
links, remove unchanged obsolete links, and render unambiguous shared MCP changes.
Planning mode and unknown permission modes only report required repairs.

**Codex:** tested versions 0.142.0 and 0.160.0 omit sandbox policy in the hook
payload. They can report `bypassPermissions` even with a read-only sandbox.
Hooks therefore audit and report drift by default. They repair only when a payload explicitly
identifies a writable sandbox. Run the skill/tool to reconcile drift when edits
are allowed; do not interpret a hook's permission mode alone as write access.

Hooks never install or upgrade the tool automatically, recreate missing shared
instructions, or overwrite conflicting content. Metadata caching outside the
repository is allowed during hook audits; set `AGENT_SYNC_READ_ONLY=1` for strict
no-cache/no-repair hook execution. CLI `check` is always read-only.

Native trust, disabled hooks, safe modes, managed policies, and client flags can
prevent hook execution. Setup preserves these controls and explains the native
trust step; file presence cannot prove hooks are enabled. MCP changes may require
server reconnection or a client restart. No hot-reload guarantee is made.

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
agent-sync-config --import-skill /path/to/portable-skill
agent-sync-config --import-mcp /path/to/mcp.json
```

Inspect dependencies first. Dependency symlinks and recognizable plugin-root
references block skill adoption; this is not a complete dependency analyzer.
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
