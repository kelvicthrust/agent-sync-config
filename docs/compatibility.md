# Provider compatibility and specification reviews

This is the maintained integration record. Repository working instructions live
in [AGENTS.md](../AGENTS.md); user sync is offline and inspects current files.

## Official sources

| Area | Official specification | Review focus |
| --- | --- | --- |
| Claude resources | [Directory](https://code.claude.com/docs/en/claude-directory) | Native project/personal paths, provider data versus authored resources |
| Instructions and rules | [Claude memory/rules](https://code.claude.com/docs/en/memory), [Codex AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md) | Import bases, precedence, nested instructions, rule conditions and loading triggers |
| Skills and commands | [Claude skills](https://code.claude.com/docs/en/skills), [Codex skills](https://learn.chatgpt.com/docs/build-skills), [Agent Skills standard](https://agentskills.io/specification) | Discovery, symlinks, metadata, invocation/arguments, supporting files, execution controls |
| Agents | [Claude subagents](https://code.claude.com/docs/en/sub-agents), [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents) | Required fields, inheritance, native catalogs, scope, controls and name collisions |
| Workflows and styles | [Claude workflows](https://code.claude.com/docs/en/workflows), [Claude output styles](https://code.claude.com/docs/en/output-styles) | Runtime APIs, orchestration, selection and system-prompt behavior |
| MCP | [Native MCP compatibility](mcp.md) | Supported transports, environment references, approvals and format differences |

Review affected sources when changing an integration and before release. Check
for changed paths, scope/precedence, metadata, arguments, dependency resolution,
execution controls, loading triggers, and deprecations. Record the meaningful
difference here, reproduce it in a disposable fixture, then implement the smallest
faithful change or document the limitation. Add focused tests and actual evidence.
Do not accumulate transcripts, speculative adapters, or a second instruction source.

## Reviewed behavior and decisions

Official specifications reviewed **2026-10-09**. Documentation is unversioned;
local native checks use **Codex CLI 0.162.0** and **Claude Code 2.1.295**.
Future client versions must be reviewed rather than inferred from this record.

- **Shared native skills:** `.agents/skills` is Codex's shared discovery standard.
  Claude discovers the same sources through `.claude/skills` links. Preserve
  supporting files; avoid duplicate `.codex/skills` entrypoints. Provider-specific
  skill metadata or substitution is not made portable by relocating a file.
- **Legacy commands:** instruction-only prompts can become standard skills.
  Claude legacy command invocation derives from the filename, so differing `name`
  metadata is left for review instead of silently changing invocation. Arguments,
  preprocessing, forked execution, and permissions have provider behavior; retain
  those commands. Only retire an unchanged original after verifying its replacement
  and discovery link. Current files support interruption recovery without a ledger.
- **Instructions:** project AGENTS.md remains shared through a CLAUDE.md import;
  personal instructions remain in native global files. Providers retain their
  different instruction precedence, loading boundaries, and limits. Do not flatten
  nested instructions or overrides. Relative project references survive relocation.
- **Rules:** retain `.claude/rules` and its exact path conditions. Generate Codex
  reading guidance, not a simulated loader. Support plain/quoted path strings and
  simple string lists. Complex/unknown conditions require review, never unconditional
  injection. This is model guidance rather than automatic enforcement.
- **Native reference agents:** `.codex/agents/*.toml` is the current native format;
  name, description, and developer_instructions are required. Keep the prompt in
  `.claude/agents` and use developer_instructions to direct source reading before
  acting. Omit `model: inherit` so Codex inherits its own settings. Ordinary source
  paths retain their original context; body edits require no regeneration. This
  is model-driven reading, not a native Markdown loader or automatic body injection.
  Flat `tools` metadata is allowed only after named acceptance that Codex's native
  permissions apply and Claude's allowlist is not translated/enforced. Other controls
  and complex YAML remain blocked; no MCP aliases, services, or permissions are inferred.
  Built-in `default`, `worker`, and `explorer` names are protected. Matching generated
  fields allow additional native settings; differing fields/tool declarations require
  reconciliation, never forced by approval. Exact three-field copied-body adapters
  can upgrade; edited or extended adapters remain conflicts. The generated usable
  definition records its source and reviewed declaration, without separate state.
- **Workflows/styles:** retain Claude resources and conditionally reference useful
  content. Reading JavaScript does not run Claude's orchestration API. Reading style
  instructions does not select a native style or replace Codex's system prompt.
  No substitute runtime or new shared resource format is introduced.
- **Provider data:** settings, hooks, plugins, memory, credentials, and client caches
  stay native. Inventory relevant paths without importing their contents as guidance.
  Never enable agents, weaken permissions, change trust, or traverse external links
  to infer portable behavior.

Discovery and scope differ between clients. Native custom agents need a client
that supports the reviewed standalone format and the user's existing agent/trust
controls. Global and project resources can coexist; the synchronizer does not
promise identical cross-scope precedence. Unsupported definitions remain intact
and are reported explicitly. No general YAML parser or additional dependency is
needed for the deliberately small conversion subset.

## Verification evidence

See [testing.md](testing.md) for fixture commands and measured results. Automated
journeys cover sharing, adaptation, conditions, conflicts, interruption/retry,
relocation, read-only behavior, native output allowlists, and scope snapshots.
Native tests must distinguish filesystem reconciliation, client catalog/loading,
and real-model compliance. Local protocol stubs can prove loading; they cannot
prove that a model will follow every referenced rule or reproduce orchestration.

The 0.7.0 review confirmed the native three-field agent format and Claude's distinct
tool controls against the official agent sources above. Tests on Codex 0.162.0 and
Claude 2.1.295 verified native catalog discovery, retained originals, and source
reference delivery to a scripted native spawn. Prompt reading remains model-driven;
the stub does not establish compliance or allowlist equivalence. See the measured
0.7.0 results in testing.md for Python 3.9, scope isolation, installation, and checks.

Before releasing an integration change, record the tested client/interpreter
versions, affected native loading evidence, relevant limitations, and suite/check
results. If specs introduce new runtime behavior, preserve it and document the
boundary until a faithful equivalent is explicitly implemented and tested.
