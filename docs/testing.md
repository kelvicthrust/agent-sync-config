# Testing and compatibility

Run these checks from a checkout of this repository. Python 3.11+ is required.
Use disposable projects and homes to review setup without installing shared
resources into your personal configuration.

## Automated checks

```sh
python3 -m unittest discover -s tests -v
python3 tests/benchmark.py
```

The suite covers initialization, existing-resource adoption, conflicts,
idempotence, installed licenses, instructions, skills, context, MCP rendering
and ownership, native settings/plugin preservation, malformed inputs, read-only
behavior, hooks, and cache invalidation. It does not use model credentials or
contact model providers.

The benchmark measures warm metadata checks, including Python startup. It reports
a 100 ms target without making scheduling-dependent timings a CI failure.
Results depend on the host and filesystem.

CI runs these commands on macOS and Linux with Python 3.11 and 3.13. A configured
matrix is not evidence of a successful run; inspect the workflow results for the
commit being evaluated. CI does not require model credentials.

## Disposable setup

```sh
AGENT_SYNC_DEMO=$(mktemp -d)
mkdir -p "$AGENT_SYNC_DEMO/home" "$AGENT_SYNC_DEMO/repo"
./bin/agent-sync-config --home "$AGENT_SYNC_DEMO/home" \
  --project "$AGENT_SYNC_DEMO/repo" --json
./bin/agent-sync-config check --home "$AGENT_SYNC_DEMO/home" \
  --project "$AGENT_SYNC_DEMO/repo" --json
./bin/agent-sync-config --home "$AGENT_SYNC_DEMO/home" \
  --project "$AGENT_SYNC_DEMO/repo" --json
```

The check should succeed, and the second sync should report no changes. Inspect
both directories to see the configuration footprint. Keep the explicit `--home`
argument on every test command; it controls the synchronizer's destination, not
the native clients' authentication or configuration directories.

For adoption tests, start a separate fixture with existing CLAUDE.md, provider
skills, or nonsecret MCP definitions. Conflicting instruction or skill contents
must remain preserved and be reported. Remove a managed skill link: `check`
should report drift without writing files, and explicit sync should restore it.
Keep an application file in the fixture and confirm it remains unchanged.

## Native discovery and installation

If native client binaries are available:

```sh
python3 tests/provider_smoke.py --codex /path/to/codex --claude /path/to/claude
```

The smoke test checks native skill discovery, hook parsing/trust status, and MCP
configuration loading. It uses a temporary HOME and labels absent clients
explicitly. No model turn is requested; native clients may independently make
background network requests.

To verify installation through an available official skills CLI:

```sh
python3 tests/provider_smoke.py \
  --codex /path/to/codex --claude /path/to/claude \
  --skills-cli /path/to/skills/bin/cli.mjs --node /path/to/node
```

This installs from the local checkout into the temporary home and checks both
client entrypoints, the project license, and bundled third-party notices.

## Native sessions with a local protocol stub

```sh
python3 tests/offline_sessions.py --codex /path/to/codex --claude /path/to/claude
```

This requires localhost socket access. Native clients load instructions and the
skill, execute hooks, connect to a local stdio MCP fixture, resume sessions, and
exercise read-only behavior. Claude also exercises safe repair in writable mode.
No real model credentials are supplied. The protocol stub returns fixed responses
and does not establish real model compliance.

Codex's hook-trust bypass in this test is confined to the vetted disposable
fixture hooks. Production setup and authenticated pilots use native hook review
and trust controls.

## Authenticated pilot checklist

Use a disposable Git project and synchronizer home. Preserve existing application
files and install the skill from the checkout. Specify the fixture `--home` and
`--project` in every skill request. Attach only the generated fixture hooks at the
native project scope (`.codex/hooks.json` for Codex, `.claude/settings.json` for
Claude); do not replace personal hook files. Review Codex's fixture hooks through
`/hooks`; restart Claude after attaching hooks.

An authenticated pilot can use the client's existing login without copying
credential files. Using normal client configuration also exposes its instructions,
skills, and MCP context to the model service. Obtain authorization for that scope
when running a pilot on someone else's behalf. Native clients can save test-session
and project/hook trust metadata in their real configuration/state directories.

Verify these behaviors:

1. Invoke the installed skill and initialize the fixture; verify adoption and an
   unchanged repeat run. Review any required native approval.
2. Remove a managed skill link and submit a normal prompt without manually
   running a check. Trusted hooks should supply drift information to the model.
3. In read-only/planning mode, confirm the missing link remains missing and
   managed files do not change. Hook metadata caching may occur outside the repo.
4. Request explicit skill sync with the fixture paths, verify the link is repaired,
   then request a read-only check and confirm it succeeds.
5. Change an instruction containing a recognizable response marker. Verify both
   resumed and fresh sessions use the updated instruction. Evaluate the final
   reply separately from progress commentary.
6. Connect a credential-free local MCP fixture and invoke its tool. Check the
   native approval/reconnection behavior and tool result.
7. Switch clients and repeat the check against the same canonical resources.
   Confirm application files and unrelated personal settings are preserved.

Do not treat file presence or a model's claimed success as proof of hook execution;
inspect native trust status, fixture hook logs/state, tool calls, and file changes.

## Verified capabilities and limits

| Environment | Verification |
| --- | --- |
| Codex 0.160.0 on macOS | Authenticated native CLI/app-server pilot: setup/adoption, explicit repair, checks, local MCP tool call, trusted hooks, drift reporting, and fresh/resumed instruction loading |
| Codex 0.142.0 on macOS | Native discovery/parsing and protocol-stub sessions; authenticated model compatibility is not established |
| Claude Code 2.1.295 on macOS | Native MCP loading and protocol-stub sessions, hooks, resume refresh, planning behavior, and writable repair; authenticated model compliance is not established |
| Python 3.14.8 on macOS | Local automated suite and benchmark |
| Python 3.11/3.13 on macOS/Linux | CI targets; consult actual workflow results |

These are tested versions, not minimum supported client versions. Desktop GUI,
cloud sessions, and additional client adapters are not verified.

The tested Codex hook payloads omit sandbox policy and may report
`bypassPermissions` even in read-only mode. Hooks therefore audit/report drift;
repair requires explicit skill sync unless a payload identifies a writable
sandbox. Claude planning/unknown modes also audit. Disabled or untrusted hooks
and native policies can prevent checks; model compliance is not guaranteed.
