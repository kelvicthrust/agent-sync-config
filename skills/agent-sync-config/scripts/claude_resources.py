"""Conservative, offline adapters for native Claude resources; no stored history."""
from __future__ import annotations

import ast
from collections import Counter
import json
from pathlib import Path
import re

BEGIN = '<!-- agent-sync-config:claude-references:start -->'
END = '<!-- agent-sync-config:claude-references:end -->'
NAME = re.compile(r'[a-z0-9]+(?:-[a-z0-9]+)*\Z')
BUILTINS = {'default', 'worker', 'explorer'}
AGENT_REFERENCE = 'agent-sync-config:claude-agent-reference'


def agent_source(instructions):
    if not isinstance(instructions, str) or not instructions.startswith(AGENT_REFERENCE + '\nSource: '):
        return None
    try:
        source = json.loads(instructions.splitlines()[1][8:])
        return source if isinstance(source, str) else None
    except (ValueError, IndexError):
        return None


def agent_instructions(display, scope, tools=None):
    lines = [AGENT_REFERENCE, 'Source: ' + json.dumps(display, ensure_ascii=False)]
    if scope == 'project':
        lines += ['Locate the repository/worktree root containing this .codex/agents definition,',
                  'even when the working directory is nested. Resolve Source from that root.']
    else:
        lines += ['Source is an absolute path within the selected personal scope.']
    lines += ['Before performing this task, read Source and follow its Markdown instruction body.',
              'Do not treat its YAML metadata as Codex configuration. If Source is missing or',
              'unreadable, report that limitation and ask for reconciliation before proceeding.',
              'Keep dependencies in their original context: resolve relative Markdown links and',
              'file-relative imports from the source directory; resolve repository context paths',
              'from the project root (personal context paths from the selected home).',
              'Reading the file does not activate Claude loaders, hooks, or execution controls.',
              'Report unavailable tools or capabilities; do not fabricate results, infer MCP',
              'mappings, or silently substitute capabilities. Native Codex permissions apply.']
    if tools is not None:
        lines += ['Reviewed Claude tools declaration: ' + json.dumps(tools, ensure_ascii=False),
                  'The user accepted this reference with Codex native permissions. The Claude',
                  'tools allowlist is NOT translated or enforced; this is not permission to',
                  'perform external actions or bypass native approvals.']
    return '\n'.join(lines) + '\n'
STANDARD_SKILL_FIELDS = {'name', 'description', 'license', 'compatibility', 'metadata', 'allowed-tools'}
# allowed-tools is optional in the open standard, but its enforcement is provider-specific.
CONTROLS = {'allowed-tools', 'tools', 'disallowedTools', 'model', 'context', 'agent',
            'disable-model-invocation', 'user-invocable', 'argument-hint', 'hooks',
            'permissionMode', 'maxTurns', 'skills', 'mcpServers', 'memory',
            'background', 'isolation', 'omitClaudeMd'}


def frontmatter(text):
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != '---':
        return '', text
    for index in range(1, len(lines)):
        if lines[index].strip() == '---':
            return ''.join(lines[1:index]), ''.join(lines[index + 1:])
    raise ValueError('Unclosed Claude frontmatter')


def string(value):
    value = value.strip()
    if not value or value.startswith(('|', '>', '[', '{', '&', '*', '!', '#')):
        raise ValueError('requires a flat plain or quoted string')
    if value.startswith('"'):
        parsed = json.loads(value)
        if not isinstance(parsed, str):
            raise ValueError('requires a string')
        return parsed
    if value.startswith("'"):
        if len(value) < 2 or not value.endswith("'") or re.search(r"(?<!')'(?!')", value[1:-1]):
            raise ValueError('invalid quoted string')
        return value[1:-1].replace("''", "'")
    if re.search(r'\s#|:\s', value) or value.lower() in {'true', 'false', 'null', '~'} or re.fullmatch(r'[+-]?\d+(?:\.\d+)?', value):
        raise ValueError('ambiguous YAML scalar; quote the string')
    return value


def metadata(text):
    header, body = frontmatter(text)
    fields = {}
    for line in header.splitlines():
        if not line.strip() or line.startswith('#'):
            continue
        match = re.fullmatch(r'([A-Za-z][A-Za-z0-9_-]*):\s*(.*)', line)
        if not match or match[1] in fields:
            return {}, body, 'Complex, duplicate, or invalid metadata requires review'
        try:
            fields[match[1]] = string(match[2])
        except ValueError:
            return {}, body, 'Complex or ambiguous metadata requires review'
    return fields, body, None


def dependency(body):
    if re.search(r'\$(?:ARGUMENTS|\d|\{?(?:CLAUDE_|PLUGIN_))|!`|(?m:^\s*@\S)', body):
        return 'Argument substitution, shell preprocessing, plugin variables, or imports require Claude behavior'
    if re.search(r'\]\((?!https?://|#)[^)]+\)|(?:\.{1,2}/|~/)|\b[\w.-]+/(?:[\w./*-]+)', body):
        return 'Resource paths need review to preserve their meaning after relocation'
    return None


def skill_limitation(text):
    header, body = frontmatter(text)
    fields = set(re.findall(r'^([A-Za-z][A-Za-z0-9_-]*):', header, re.M))
    unsupported = fields & CONTROLS | (fields - STANDARD_SKILL_FIELDS)
    if unsupported:
        return 'Provider-specific skill metadata: ' + ', '.join(sorted(unsupported))
    # Skills move with their supporting files, so ordinary relative dependencies stay intact.
    if re.search(r'\$(?:ARGUMENTS|\d|\{?(?:CLAUDE_|PLUGIN_))|!`', body):
        return 'Skill uses provider-specific substitution or execution behavior'
    fields, _, review = metadata(text)
    if not {'name', 'description'} <= set(fields) and not review:
        return 'Portable skills need name and description metadata'
    if review and not re.search(r'^metadata:\s*$', header, re.M):
        return review
    return None


def strip_references(text):
    if text.count(BEGIN) != text.count(END) or text.count(BEGIN) > 1:
        raise ValueError('Malformed Claude reference markers')
    if BEGIN not in text:
        return text
    start, end = text.index(BEGIN), text.index(END) + len(END)
    if end < start:
        raise ValueError('Reversed Claude reference markers')
    return text[:start].rstrip() + text[end:]


def add_references(text, references):
    clean = strip_references(text)
    if not references:
        return clean
    section = [BEGIN, '## Claude content references for Codex', '',
               'Consult these files only for the tasks or paths described below. Reading them',
               'does not activate Claude loaders, permissions, hooks, or orchestration.',
               'Read instruction content only; provider metadata remains inactive.',
               'Do not execute workflow scripts or emulate unsupported execution controls.', '']
    section.extend('- ' + entry for entry in sorted(set(references)))
    section.append(END)
    return clean.rstrip() + '\n\n' + '\n'.join(section) + '\n'


class Resources:
    def __init__(self, sync, error, exists, toml):
        self.sync, self.error, self.exists, self.toml = sync, error, exists, toml
        self.references = []

    def record(self, source, disposition, explanation, destination=None):
        entry = {'source': str(source), 'disposition': disposition, 'compatibility': explanation}
        if destination is not None:
            entry['destination'] = str(destination)
        self.sync.resources.append(entry)

    def reference(self, path, kind, explanation, condition=None, conflict=False, destination=None):
        self.record(path, 'conflict' if conflict else 'content-reference', explanation, destination)
        self.sync.notes.append(f'{kind}: {path}: {explanation}')
        if conflict:
            self.sync.issue(f'{explanation}: {path}' + (f', {destination}' if destination else ''))
        display = path.relative_to(self.sync.base).as_posix() if self.sync.scope == 'project' else str(path)
        when = condition or (f'To review the {path.stem} {kind.lower()} definition, consult' if conflict else f'When the user requests the {path.stem} {kind.lower()}, consult')
        self.references.append(f'{when} {json.dumps(display, ensure_ascii=False)}. {explanation}. Content reference only.')

    def files(self, category, suffixes):
        directory = self.sync.base / '.claude' / category
        if not self.exists(directory):
            return []
        if directory.is_symlink() or not directory.is_dir():
            self.record(directory, 'preserved', 'Linked or non-directory resource collection requires review')
            self.sync.issue(f'Cannot inventory Claude resource directory (preserved): {directory}')
            return []
        result = []
        # Do not traverse symlink directories or read resources outside the selected scope.
        for path in sorted(directory.rglob('*')):
            if any(parent.is_symlink() for parent in (path, *path.parents) if parent != self.sync.base):
                if path.is_symlink():
                    self.record(path, 'preserved', 'Linked resource requires explicit reconciliation')
                    self.sync.issue(f'Linked Claude resource (preserved): {path}')
                continue
            if path.is_file() and path.suffix in suffixes:
                self.sync.observe(path)
                result.append(path)
        return result

    def definitions(self, kind):
        paths = self.files(kind, {'.md'})
        parsed = []
        for path in paths:
            try:
                fields, body, reason = metadata(path.read_text())
            except ValueError as exc:
                raise self.error(f'{path}: {exc}') from exc
            name = fields.get('name', path.stem)
            parsed.append((path, fields, body, reason, name))
        if kind == 'agents':
            unknown = self.sync.accepted_agents - {entry[4] for entry in parsed}
            if unknown:
                raise self.error('Unknown --accept-agent-reference names: ' + ', '.join(sorted(unknown)))
        counts = Counter(entry[4] for entry in parsed)
        for path, fields, body, reason, name in parsed:
            if counts[name] > 1:
                self.reference(path, kind, 'Duplicate source names require source selection', conflict=True)
                continue
            if kind == 'commands':
                self.command(path, fields, body, reason, name)
            else:
                self.agent(path, fields, body, reason, name)

    def command(self, path, fields, body, reason, name):
        unknown = set(fields) - {'name', 'description'}
        reason = reason or (f'Unsupported command metadata: {", ".join(sorted(unknown))}' if unknown else None)
        reason = reason or (None if NAME.fullmatch(name) and len(name) <= 64 else 'Unsupported command name')
        reason = reason or ('Command name differs from its filename; migration would change Claude invocation' if name != path.stem else None)
        reason = reason or ('Nested command names are provider-specific' if path.parent != self.sync.base / '.claude/commands' else None)
        reason = reason or dependency(body) or ('Empty instruction body' if not body.strip() else None)
        if reason:
            self.reference(path, 'Command', reason)
            return
        if name == 'agent-sync-config':
            self.reference(path, 'Command', 'Synchronizer installation is owned by the skill installer', conflict=True)
            return
        description = fields.get('description', f'Run the {name} instructions.')
        if not description.strip() or len(description) > 1024:
            self.reference(path, 'Command', 'Skill description must be nonempty and at most 1024 characters')
            return
        content = f'---\nname: {json.dumps(name)}\ndescription: {json.dumps(description, ensure_ascii=False)}\n---\n' + body
        target = self.sync.base / '.agents/skills' / name
        entry = self.sync.base / '.claude/skills' / name
        self.sync.safe_parent(target / 'SKILL.md'); self.sync.safe_parent(entry)
        self.sync.observe(target); self.sync.observe(entry)
        if self.exists(target):
            skill = target / 'SKILL.md'
            matches = False
            if not target.is_symlink() and target.is_dir() and skill.is_file() and not skill.is_symlink():
                existing = skill.read_text()
                prior, prior_body, review = metadata(existing)
                matches = not review and prior == {'name': name, 'description': description} and prior_body == body
                if matches:
                    content = existing  # Preserve a compatible replacement's formatting.
            if not matches:
                self.reference(path, 'Command', 'Shared skill differs; choose the source explicitly', conflict=True, destination=skill)
                return
        if self.exists(entry) and (not entry.is_symlink() or entry.resolve() != target.resolve()):
            self.reference(path, 'Command', 'Claude skill entrypoint conflicts; preserve both resources', conflict=True, destination=entry)
            return
        self.sync.write(target / 'SKILL.md', content)
        if not self.exists(entry):
            self.sync.edit('link', entry, target, f'Link: {entry} -> {target}')
        # Retire only after the replacement and discovery reference have been verified.
        self.sync.edit('retire-command', path, (target / 'SKILL.md', entry, content, path.read_bytes()), f'Migrate command: {path} -> {target / "SKILL.md"}')
        self.record(path, 'shared-native', 'Instruction-only command becomes an Agent Skill; Claude invocation uses its skill discovery link', target / 'SKILL.md')

    def agent(self, path, fields, body, reason, name):
        unknown = set(fields) - {'name', 'description', 'model', 'tools'}
        reason = reason or (f'Unsupported agent controls: {", ".join(sorted(unknown))}' if unknown else None)
        reason = reason or ('Model override has no implemented equivalent' if fields.get('model', 'inherit') != 'inherit' else None)
        reason = reason or ('Agent needs name, description, and instructions' if not fields.get('name') or not fields.get('description') or not body.strip() else None)
        reason = reason or (None if NAME.fullmatch(name) and len(name) <= 64 else 'Unsupported agent name')
        tools = fields.get('tools')
        if tools is not None and not all(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.*-]*', tool.strip()) for tool in tools.split(',')):
            reason = reason or 'Agent tools require a flat comma-separated declaration'
        if reason:
            self.reference(path, 'Agent', reason, conflict=True)
            return
        target = self.sync.base / '.codex/agents' / (name + '.toml')
        prior_sources = self.agent_sources.get(path, [])
        if any(prior != target for prior in prior_sources):
            self.reference(path, 'Agent', 'Agent source name or destination changed; reconcile explicitly',
                           conflict=True, destination=next(prior for prior in prior_sources if prior != target))
            return
        if name in BUILTINS or name in self.sync.agent_names:
            self.reference(path, 'Agent', 'Codex agent name collision; choose the source explicitly', conflict=True, destination=target)
            return
        display = path.relative_to(self.sync.base).as_posix() if self.sync.scope == 'project' else str(path)
        wanted = {'name': name, 'description': fields['description'],
                  'developer_instructions': agent_instructions(display, self.sync.scope, tools)}
        self.sync.safe_parent(target); self.sync.observe(target)
        matching = False
        doc = self.toml().document()
        if self.exists(target):
            if target.is_symlink() or not target.is_file():
                self.reference(path, 'Agent', 'Codex agent target is linked or not a file', conflict=True, destination=target)
                return
            try:
                doc = self.toml().parse(target.read_text())
                current = doc.unwrap()
            except ValueError as exc:
                raise self.error(f'Malformed Codex agent configuration: {target}') from exc
            matching = all(current.get(key) == value for key, value in wanted.items())
            legacy = current == {'name': name, 'description': fields['description'], 'developer_instructions': body}
            if not matching and not legacy:
                self.reference(path, 'Agent', 'Agent definitions differ; select and reconcile the source explicitly', conflict=True, destination=target)
                return
        if tools is not None and not matching and name not in self.sync.accepted_agents:
            warning = 'Claude tools allowlist is not translated or enforced; Codex uses its existing native permissions'
            approved = self.sync.review_agent and self.sync.review_agent(name, path, target, tools, warning)
            if not approved:
                self.reference(path, 'Agent', warning + '; approve the named reference with --accept-agent-reference ' + name,
                               conflict=True, destination=target)
                return
        if not matching:
            for key, value in wanted.items():
                doc[key] = value
            self.sync.write(target, self.toml().dumps(doc))
        explanation = 'Native Codex agent reads the original Claude prompt; body edits are shared without regeneration; metadata changes require sync and reconciliation'
        if tools is not None:
            explanation += '; reviewed Claude tools allowlist is not translated or enforced; native Codex permissions apply'
        self.record(path, 'native-reference', explanation, target)
        self.references.append(f'When a task matches the {json.dumps(name)} agent ({json.dumps(fields["description"], ensure_ascii=False)}), use the native Codex agent {json.dumps(name)}. It reads {json.dumps(display, ensure_ascii=False)} before acting. Native Codex permissions apply; Claude execution controls are not activated.')

    def rules(self):
        for path in self.files('rules', {'.md'}):
            try:
                header, _ = frontmatter(path.read_text())
                paths = None
                if header.strip():
                    lines = [line for line in header.splitlines() if line.strip() and not line.lstrip().startswith('#')]
                    if not lines or not lines[0].startswith('paths:'):
                        raise ValueError('Rule metadata requires review; conditions will not be guessed')
                    inline = lines[0][6:].strip()
                    if inline and len(lines) != 1:
                        raise ValueError('Additional rule metadata requires review')
                    if inline.startswith('['):
                        paths = ast.literal_eval(inline)
                    elif inline:
                        paths = [string(inline)]  # Keep comma-separated/brace glob syntax exactly as written.
                    else:
                        paths = [string(re.fullmatch(r'\s+-\s+(.+)', line)[1]) for line in lines[1:]]
                    if not isinstance(paths, list) or not paths or not all(isinstance(p, str) and p for p in paths):
                        raise ValueError('Rule paths need a nonempty string list')
                condition = 'Before reading or modifying a file matching Claude paths ' + json.dumps(paths, ensure_ascii=False) + ', consult' if paths else 'For work in this scope, consult'
                self.reference(path, 'Rule', 'Codex uses reading guidance; Claude path-triggered loading is not reproduced', condition)
            except (ValueError, TypeError, SyntaxError) as exc:
                if 'Unclosed' in str(exc):
                    raise self.error(f'{path}: {exc}') from exc
                self.record(path, 'preserved', f'Rule conditions require review: {exc}')
                self.sync.issue(f'Rule conditions require review (preserved): {path}')

    def run(self):
        native = self.sync.base / '.codex/agents'
        self.sync.safe_parent(native / 'placeholder')
        self.sync.agent_names = set()
        self.agent_sources = {}
        config = self.sync.base / '.codex/config.toml'
        if config.is_file():
            agents = self.toml().parse(config.read_text()).get('agents', {})
            self.sync.agent_names.update(key for key, value in agents.items() if isinstance(value, dict))
        if native.is_dir():
            for path in sorted(native.glob('*.toml')):
                self.sync.observe(path)
                if path.is_symlink():
                    self.sync.issue(f'Linked native agent (preserved): {path}')
                    continue
                doc = self.toml().parse(path.read_text())
                source = agent_source(doc.get('developer_instructions'))
                if source is not None:
                    source = Path(source) if self.sync.scope == 'global' else self.sync.base / source
                    source = Path(source.absolute())
                    directory = self.sync.base / '.claude/agents'
                    if not source.is_relative_to(directory) or '..' in source.parts:
                        self.sync.issue(f'Agent reference outside selected Claude agents (preserved): {path}')
                    else:
                        self.agent_sources.setdefault(source, []).append(path)
                        if not source.is_file():
                            self.record(source, 'conflict', 'Native reference agent source is missing; definition preserved', path)
                            self.sync.issue(f'Missing Claude agent source (definition preserved): {source}, {path}')
                if doc.get('name') and path.stem != doc['name']:
                    self.sync.agent_names.add(doc['name'])
        self.definitions('commands')
        self.definitions('agents')
        self.rules()
        for category, suffixes, explanation in (
                ('workflows', {'.js', '.mjs', '.cjs', '.ts', '.md'}, 'Inspect steps when requested; Claude orchestration is unsupported and scripts are not executed'),
                ('output-styles', {'.md'}, 'Use useful writing conventions when requested; native output-style selection and system-prompt replacement are unsupported')):
            for path in self.files(category, suffixes):
                self.reference(path, category, explanation)
        for name in ('settings.json', 'settings.local.json', 'hooks', 'plugins', 'memory', 'agent-memory', 'projects', 'credentials.json', '.credentials.json'):
            path = self.sync.base / '.claude' / name
            if self.exists(path):
                self.record(path, 'provider-specific', 'Preserved; provider settings, execution controls, memory, and credentials are not portable instructions')
        return self.references
