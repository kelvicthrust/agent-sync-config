# Testing and compatibility

Use Python 3.11+ and disposable homes/projects. Do not copy credentials, change
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
files, native Codex skill/MCP discovery, Claude references and MCP loading, no
synchronizer hooks, and continued native functionality after installer removal.
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
resume, and absence of automatic reference repair. The stub returns no tool call:
these sessions verify loading and protocol behavior, not real model compliance or
actual skill execution. CLI tests separately exercise the installed runtime.
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
local macOS/Linux with Python 3.11+; CI uses Python 3.11 and 3.13. Cloud sessions,
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
