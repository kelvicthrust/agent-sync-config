# Repository guidance

This repository ships the `agent-sync-config` skill and its Python runtime.
Use Python 3.9+ on macOS/Linux. The shipped skill is in
`skills/agent-sync-config/`; `bin/agent-sync-config` invokes its runtime.

## Implementation and verification

- Keep runtime behavior, SKILL.md, CLI help, README, and testing docs consistent.
- Preserve project/global scope isolation, conflicting content, native trust,
  disabled-hook controls, licenses, and strictly read-only CLI checks.
- Test configuration changes in disposable homes/projects. Do not synchronize
  personal configuration or use authenticated model sessions without authorization.
- Run `python3 -m unittest discover -s tests -v` for runtime changes. Recheck
  `python3 tests/benchmark.py` when explicit check behavior changes. Native
  installation/session checks are documented in `docs/testing.md`.
- For documentation-only edits, check the diff and relevant commands/links;
  successful CI on the final commit is required before publishing a release.

## Compatibility and maintained context

- Read [docs/compatibility.md](docs/compatibility.md) when changing provider
  integrations and before releases. Review targeted official Codex/Claude specs;
  ordinary user sync must remain offline. Record review date/client versions,
  changed discovery or loading behavior, and actual verification evidence there.
- Compare native directories, instructions/rules, skills/commands, subagents, and
  workflows: paths, scopes/precedence, metadata, arguments, dependency paths,
  execution controls, loading behavior, and deprecations.
- For a meaningful spec change, record the difference, reproduce it in a fixture,
  then make the smallest faithful implementation change or document the limitation.
  Update focused tests. Keep concise decisions and rationale, not chat transcripts
  or a second project instruction source.
- Prefer established shared standards, then existing files, then faithful native
  adapters. Keep unsupported runtime/permission behavior explicit. Do not invent
  `.agents/rules`, `.agents/agents`, hooks, workflow runtimes, state infrastructure,
  dependencies, or new configuration roots to simulate parity.
- Use focused tests while editing; run the full suite once after the implementation
  settles. Separate native discovery/loading evidence from model compliance.

## Commits and pushes

- Commit, push, tag, and publish only when requested or already authorized in the
  current conversation. An explicit request to complete a release includes the
  necessary release documentation commit, push, tag, and GitHub release.
- Inspect status/diffs and stage only the intended files. Keep private notes,
  credentials, runtime caches, and unrelated changes out of commits.
- Do not change Git identity, signing configuration, or credentials as part of
  this workflow. Never force-push, rewrite published history, or move an existing
  release tag without explicit authorization.

## Releases

- Match the runtime VERSION and `vX.Y.Z` tag. Before 1.0,
  breaking workflow/default changes advance the minor version; fixes use patches.
- Publish regular releases by default, including versions below 1.0. Do not label
  commits, tag messages, or releases as previews, or mark a release as a prerelease,
  unless the user explicitly requests it. Preserve existing releases and tags.
- Keep the README independent of release versions. Update it only when usage or
  requirements change; do not edit it just to publish a release. Put versioned
  installation commands and release-specific migration steps in GitHub release
  notes. Do not create a separate release.md.
- Verify the working tree is clean, the final commit is on origin/main, and its
  required CI jobs pass. Create an annotated tag pointing to that exact commit
  and push only the intended tag.
- Publish a regular GitHub release from the existing remote tag (`--verify-tag`).
  Never silently replace an existing release.
- Explain changes, migration, tested behavior, and material limitations in the
  release notes. Verify installation from the tagged source in a disposable home.
- Skills.sh discovery uses installation telemetry, not a separate package publish.
  Keep the default installation source and pinned tag source clearly distinguished.

## Dogfooding

Run the skill explicitly in project scope to initialize this repository when
requested. Preserve these instructions outside its managed section. Edit the
shipped runtime in `skills/agent-sync-config/`. Projects contain shared
configuration and links, never a generated runtime or automatic sync hooks. Inspect generated project resources before
committing them, and never escalate dogfooding to global synchronization implicitly.
