# Testing and compatibility

Use Python 3.11+ and disposable homes/projects. Tests must not copy credentials,
change personal configuration, or contact model providers.

## Automated checks

```sh
python3 -m unittest discover -s tests -v
python3 tests/benchmark.py
```

The suite covers instructions, skills, context, MCP round trips, conflicts,
provider settings, project/global scope isolation, first-run scope selection,
read-only checks, imports, persistent removals, uninstall/purge, and recovery.
Simplification tests cover minimal project setup, immediate sharing, relocation,
legacy hook/runtime migration, modified artifacts, obsolete Codex aliases,
unrelated hooks, disabled controls, and idempotence.

The benchmark measures explicit project/global read-only checks with 30 skills,
including Python startup. No prompt hooks or warm metadata caches are installed;
timings are informational and depend on the host/filesystem.

## Manual project checks

From a checkout, point the runtime at disposable directories:

```sh
sandbox=$(mktemp -d)
mkdir -p "$sandbox/home" "$sandbox/repo"
./bin/agent-sync-config --scope project --home "$sandbox/home" --project "$sandbox/repo"
./bin/agent-sync-config check --scope project --home "$sandbox/home" --project "$sandbox/repo"
```

Expect AGENTS.md, a CLAUDE.md import wrapper, `.agents/agent-sync.json`, and empty
canonical skill/context directories. No setup-skill runtime, Python dependencies,
`.codex/hooks.json`, or Claude hook settings should be created.

Create a skill in `.agents/skills`, then sync. Claude's per-skill relative link
must reference it. Edit the shared skill through either path and verify the other
path sees the edit immediately. Move the fixture and verify the links still work.
Existing Claude instructions and skills should be adopted when compatible;
differing instructions or skill contents must be preserved and reported.

Removing a project skill link should produce drift in a strictly read-only check.
Only an explicit project sync repairs it. New resources do not trigger automatic
adoption, and no prompt should require trust for a synchronizer hook.

## Global checks and lifecycle

```sh
./bin/agent-sync-config --scope global --home "$sandbox/home"
./bin/agent-sync-config check --scope global --home "$sandbox/home"
./bin/agent-sync-config remove-skill review-code --scope global --home "$sandbox/home" --dry-run
./bin/agent-sync-config uninstall --scope global --home "$sandbox/home" --dry-run
./bin/agent-sync-config uninstall --scope global --home "$sandbox/home" --purge-shared-sources --yes
```

Global setup uses one personal source and supported native links, with no new
`.codex/skills` aliases or hooks. Instructions and skill edits are shared through
links. MCP requires explicit rendering. Snapshot all project files across global
operations and all personal/provider files across project operations.

A missing supported global skill entrypoint or observed Skills CLI record requires
an explicit removal/restoration decision. Checks and noninteractive sync never
silently reinstall it; `--yes` does not select that decision. Tombstones prevent
adoption of remaining provider copies. Dry runs, cancellation, and missing
confirmation must leave fixtures unchanged, including locks and caches.

Uninstall must preserve native instructions, skills and MCP; remove only owned
integration; and leave projects and unrelated settings/hooks intact. Purge must
verify native replacements before deleting owned shared sources. Do not recreate
legacy Codex aliases. Test custom roots, paths with spaces, malformed metadata,
modified artifacts, private VCS data, repeat execution, and interrupted cleanup.

## Migration fixtures

Seed a disposable pre-0.4 manifest with its recorded runtime digest, discovery
links, and native hook commands. A check must report required migration without
writes. Explicit sync must back up and retire only unchanged owned artifacts.
Modified packages, handlers, matcher groups, or redirected links must remain
preserved and reported. Preserve unrelated/empty hook groups and settings modes.

Verify canonical skill replacements before retiring owned legacy Codex aliases.
Migration updates both link and per-skill ownership so retired aliases are not
recreated or reported as pending removals. Missing supported entrypoints still
require a removal decision. Global and project migrations operate independently.

The observed existing-project setup can be reproduced by copying only its agent
configuration into a disposable Git repository. Keep private instructions out of
committed fixtures and never run migration against the original repository.

## Native discovery and installation

```sh
python3 tests/provider_smoke.py
python3 tests/provider_smoke.py --skills-cli /path/to/skills/bin/cli.mjs --node /path/to/node
python3 tests/skills_lifecycle.py --skills-cli /path/to/skills/bin/cli.mjs --node /path/to/node
```

These scripts use disposable homes, local skill installation and native discovery
without requesting a model turn. Verify one enabled entry per managed skill
within each scope, working Claude links/imports, no synchronizer hooks, and native
MCP loading before and after global uninstall. Global/project copies may coexist.
The Skills CLI lifecycle script exercises no-op, partial-provider, complete and
setup-skill removal, reinstall acceptance, and installed-runtime self-uninstall.
Never run removal tests against the publisher checkout itself.

## Optional offline sessions

```sh
python3 tests/offline_sessions.py
```

This uses a localhost protocol stub and dummy keys to exercise native instruction
loading, machine-installed skill invocation, MCP, planning/read-only behavior,
and resume. It does not use real inference or credentials. No hook-trust bypass
is needed. Prompts must not automatically repair references or create hook caches;
an explicit sync repairs a missing link afterward. Localhost access is required.

## Compatibility evidence

Initial support is local macOS/Linux with Python 3.11+. CI targets Python 3.11
and 3.13; inspect actual workflow results before publishing a release.

Historical 0.3.0 verification used Python 3.12.14, Codex 0.162.0, Claude Code
2.1.295, and Skills CLI 1.7.1. Its 76 tests, hook benchmarks and hook-session
results apply to that version's behavior, not the simplified 0.4.0 workflow.
Record current verification separately; authenticated model compliance, desktop
GUI workflows, and cloud behavior are not established by native discovery or a
protocol stub. Cursor and Grok integrations remain future work.

Current 0.4.0 local verification:

| Environment | Result |
| --- | --- |
| Python 3.12.14 on macOS | 75 automated tests passed |
| Codex 0.162.0 | One entry per managed skill, no synchronizer hooks, native MCP and offline stub sessions passed |
| Claude Code 2.1.295 | Native MCP, on-disk skill references, and offline stub sessions passed |
| Skills CLI 1.7.1 | Local installation, external removals, persistent removal, reinstall acceptance, and installed-runtime self-uninstall passed |
| Existing-project disposable copy | Owned package/hooks removed; original instructions and source repository preserved |
| Explicit checks, 30 skills | Project 86 ms median / 90 ms p95; global 113 ms median / 135 ms p95 in a concurrent local sample |

No authenticated model sessions were run. The full automated suite ran once after
implementation settled; focused migration/lifecycle tests ran during development.
