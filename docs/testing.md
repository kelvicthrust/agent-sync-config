# Testing and compatibility

Use Python 3.9+ and disposable homes/projects. Do not copy credentials, change
personal configuration, or contact model providers. Focused tests run while editing;
run the full automated suite once after implementation settles.

## Automated verification

```sh
python3 -m unittest discover -s tests -v
python3 tests/benchmark.py
```

The suite validates these observable journeys:

| Journey | Acceptance |
| --- | --- |
| Fresh project | Only AGENTS.md and its CLAUDE.md import appear until skills/MCP are present |
| Scope choice | Interactive project/global selection works; cancellation and noninteractive refusal write nothing |
| Existing project | Every local marker selects project; malformed configuration never escalates scope |
| Scope isolation | Snapshots prove project operations leave personal files intact and global operations leave projects intact |
| Native sharing | Claude-only instructions/skills are adopted when compatible; references expose edits immediately |
| Claude-first setup | One sync migrates simple commands, adapts simple agents, and references rules/workflows/styles with limitations |
| Command retirement | Replacement and link are verified first; matching replacements and interrupted migrations are retryable; collisions/redirects preserve originals |
| Agent differences | Original prompts remain; controls, built-in collisions, changed sources, and edited destinations require review |
| Conditional references | Path-gated rules stay conditional; nested files/spaces/relocation work; missing resources remove only generated references |
| Unsupported resources | Provider execution controls remain intact; no scripts are executed or permission controls weakened |
| Conflicts | Differing instructions, skill copies, external dependencies, and MCP definitions are preserved |
| Context | Existing documents remain intact and referenced; no separate context store appears |
| Relocation/discovery | Relative links survive moving a project; nested Git/worktree discovery works; non-Git targets stay explicit |
| Check/preview/repeat | Read-only operations write nothing; settled repeat sync is idempotent |
| Installer boundaries | Installed synchronizer and metadata remain unchanged; explicit self-import is rejected |
| Removal | Complete source/entrypoint removal has no restoration source; partial link removal can be repaired explicitly |
| MCP | Native round trips, explicit source/import selection, credential boundaries, unrelated settings and comments are verified |
| Legacy | Existing sources, manifests, packages, hooks, aliases, and externally linked instructions are reported and preserved |
| Interrupted writes | Temporary files are removed; preflight detects intervening changes; inspection/retry succeeds without a recovery ledger |

Fresh-setup allowlists reject custom state, manifests, neutral MCP files, context
folders, launchers, hooks, copied tool packages, and duplicate Codex skill aliases.
No persistent locks, backups, registration, ownership history, or recovery state
are permitted. The benchmark inspects current files on every explicit check; no
metadata fast path is used. Timings include interpreter startup and are informational.

## Disposable manual check

```sh
sandbox=$(mktemp -d)
mkdir -p "$sandbox/home" "$sandbox/repo"
./bin/agent-sync-config --scope project --home "$sandbox/home" --project "$sandbox/repo"
./bin/agent-sync-config check --scope project --home "$sandbox/home" --project "$sandbox/repo"
./bin/agent-sync-config --scope global --home "$sandbox/home"
```

For a Claude-first journey, add `.claude/commands/review.md` with an instruction-only
body, `.claude/agents/reviewer.md` with name/description frontmatter, a path-gated
`.claude/rules/api.md`, and a `.claude/workflows/review.js` file. Run ordinary sync:
expect a shared review skill and Claude link, a native Codex reviewer TOML with
its unchanged instruction body, retained agent/rule/workflow originals, and
conditional reading guidance. Check the JSON `resources` dispositions. Add a
model override or permission field: the original must remain and adaptation must
require review. Edit either adapted agent file: both paths must be reported.
Repeat sync must make no changes after conflicts are resolved.

Expect only native instructions in fresh empty scopes. Add a self-contained skill
under `.agents/skills`, then sync and inspect its relative Claude link. Edit through
either path and verify shared contents. Add native MCP and verify native output,
then introduce a same-name difference and require explicit source selection.

## Installation and native discovery

```sh
python3 tests/provider_smoke.py
python3 tests/provider_smoke.py --skills-cli /path/to/skills/bin/cli.mjs --node /path/to/node
python3 tests/skills_lifecycle.py --skills-cli /path/to/skills/bin/cli.mjs --node /path/to/node
```

These use disposable homes and local Skills CLI installation; no model turn is
requested. Verify licenses, execution from the installed script, unchanged tool
files, native Codex skill/MCP discovery (including migrated commands), Claude
references and MCP loading, no synchronizer hooks, and continued native functionality after installer removal.
The installer script exercises no-op, partial-provider, complete, synchronizer
removal, and explicit reinstall. Removing only a provider link is ordinary drift;
there are no tombstones or pending historical-removal decisions.
Never run removal fixtures against the publisher checkout.

## Offline sessions

```sh
python3 tests/offline_sessions.py
```

A localhost protocol stub with dummy keys exercises native project/personal
instruction loading, installed skill invocation, MCP, planning/read-only mode,
resume, and absence of automatic reference repair. It also verifies that migrated
commands load as skills in both clients,
Codex advertises project/global adapted agents in its native catalog, and Claude
still discovers original agents. Path-gated rule references reach Codex without
automatically injecting their bodies. The stub returns no tool call: these sessions
verify catalogs/loading and protocol behavior, not real model compliance, agent
execution, or actual skill execution. CLI tests separately exercise the installed runtime.
No hook-trust bypass or authenticated model session is needed. Localhost access
is required; native clients may create their own disposable session files.

## Existing setups

Copy only agent configuration into disposable fixtures. Never migrate the original
repository or copy credentials. Legacy custom sources/manifests/MCP/runtime/hooks
are preserved and reported, not consumed as ownership authority.

For an intentional manual transition: inspect current shared contents; establish
matching native instruction, skill, and MCP replacements; verify both clients;
then explicitly remove only the obsolete artifacts you chose. Remove exact old
synchronizer hook handlers while preserving unrelated groups, controls, and
settings. Preserve unknown/modified files and private version-control data.
The tool does not automatically uninstall old integrations or purge sources.

Native loading is verified separately from filesystem reconciliation. Support is
local macOS/Linux with Python 3.9+; CI includes Python 3.9, 3.11, and 3.13. Cloud sessions,
Windows, Cursor, Grok, and authenticated model compliance are not established by
these fixtures. Record current versions and measured verification results here
only after running the checks.

## Local 0.5.0 verification

Verified on macOS with Python 3.12.14, Skills CLI 1.7.1, Codex CLI 0.162.0,
and Claude Code 2.1.295:

- All 45 automated tests passed (6.354 seconds).
- Real local Skills CLI installation, partial/complete removal, explicit repair,
  reinstall, and synchronizer removal passed in disposable homes.
- Native Codex discovery showed one managed entry per skill, no synchronizer
  hooks, and working MCP before and after synchronizer removal.
- Claude project/global MCP loading and skill references passed.
- Offline Codex/Claude instruction, skill, MCP, read-only/planning, and resume
  scenarios passed using localhost protocol stubs and dummy keys.
- Skill metadata validation passed.
- Explicit checks with 30 skills and 20 samples measured project median 78.90 ms
  / p95 79.98 ms and global median 78.74 ms / p95 81.19 ms.

These are local verification results, not authenticated model-compliance tests
or results from the Linux/Python CI matrix. Personal configuration and other
projects were not modified.

## Local 0.5.1 Python compatibility verification

The minimum was lowered to Python 3.9 without changing the bundled dependencies.
All 45 automated tests passed with the existing Python 3.9.6 interpreter
(12.605 seconds), including native MCP round trips and filesystem scope isolation.
Skill metadata validation also passed. Explicit checks with 30 skills and 20
samples measured project median 135.53 ms / p95 182.66 ms and global median
129.35 ms / p95 132.45 ms. These timings used a different interpreter from the
0.5.0 run and are not a controlled performance comparison.

The macOS/Linux CI matrix includes Python 3.9, 3.11, and 3.13. CI results are
available in GitHub Actions. Python 3.11+ remains recommended for upstream support.


## Local 0.6.0 verification

Verified on macOS with Python 3.9.6, Skills CLI 1.7.1, Codex CLI 0.162.0,
and Claude Code 2.1.295:

- All 65 automated tests passed (13.718 seconds), including 20 Claude-resource
  journeys. An explicit-import regression found in the first full run was corrected
  without changing the existing import behavior; the repeated suite passed.
- Real local Skills CLI installation and synchronizer removal passed; native shared
  configuration remained usable afterward. Codex discovered one managed entry per
  skill, including a migrated command, with no synchronizer hooks.
- Local protocol stubs verified migrated command skill loading in both clients,
  adapted project/global agents in Codex's native catalog, retained Claude agents,
  conditional references without rule-body injection, native instructions/MCP,
  read-only/planning behavior, resume, and explicit reference repair.
- These checks establish catalog/loading behavior, not actual subagent execution,
  real-model compliance, or equivalence of provider execution controls.
- Skill metadata validation and diff whitespace checks passed.
- Explicit checks with 30 skills and 20 samples measured project median 134.28 ms
  / p95 140.84 ms and global median 130.72 ms / p95 134.96 ms.

Only disposable fixtures were synchronized. No personal configuration or existing
user projects were changed, and no authenticated model sessions were used.
Linux and the other CI interpreter versions have not been run for these local edits.
