"""User journeys for one-command Claude-first sharing and native adaptation."""
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

import test_sync as fixtures

sync = fixtures.sync


class ClaudeResourceTests(unittest.TestCase):
    setUp = fixtures.ConfigurationTests.setUp
    write = fixtures.ConfigurationTests.write
    skill = fixtures.ConfigurationTests.skill
    run_tool = fixtures.ConfigurationTests.run_tool

    def command(self, name='review-change', text='Review changes carefully.\n', home=False):
        return self.write(f'.claude/commands/{name}.md', text, home)

    def agent(self, name='code-reviewer', fields='', body='Review changes carefully.\n', home=False):
        return self.write(f'.claude/agents/{name}.md', f'---\nname: {name}\ndescription: Review code changes.\n{fields}---\n' + body, home)

    def test_claude_first_one_command_and_native_allowlist(self):
        original = self.agent(fields='model: inherit\n')
        command = self.command()
        self.skill('.claude/skills/portable-review')
        rule = self.write('.claude/rules/api.md', '---\npaths:\n  - "src/api/**/*.{ts,tsx}"\n---\nValidate inputs.\n')
        flow = self.write('.claude/workflows/review.js', 'throw new Error("must never execute");\n')
        style = self.write('.claude/output-styles/concise.md', 'Write concise reports.\n')
        settings = self.write('.claude/settings.json', '{"permissions":{"deny":["Bash(rm:*)"]},"enabledPlugins":{"x":true}}')
        before = {p: p.read_bytes() for p in (original, rule, flow, style, settings)}
        report = self.run_tool()
        self.assertFalse(command.exists())
        target = self.repo / '.agents/skills/review-change/SKILL.md'
        self.assertTrue(target.is_file())
        self.assertEqual((self.repo / '.claude/skills/review-change').resolve(), target.parent)
        agent = sync.read_toml(self.repo / '.codex/agents/code-reviewer.toml').unwrap()
        self.assertEqual(agent, {'name': 'code-reviewer', 'description': 'Review code changes.', 'developer_instructions': 'Review changes carefully.\n'})
        self.assertEqual({p: p.read_bytes() for p in before}, before)
        guidance = (self.repo / 'AGENTS.md').read_text()
        self.assertIn('Before reading or modifying a file matching Claude paths ["src/api/**/*.{ts,tsx}"]', guidance)
        self.assertIn('not reproduced', guidance)
        self.assertIn('scripts are not executed', guidance)
        self.assertNotIn(str(self.repo), guidance)
        self.assertEqual({'shared-native', 'native-adaptation', 'content-reference', 'provider-specific'}, {r['disposition'] for r in report['resources']})
        snapshot = fixtures.snapshot(self.base)
        self.assertEqual(self.run_tool()['changes'], [])
        self.run_tool('check')
        self.assertEqual(fixtures.snapshot(self.base), snapshot)
        roots = {p.parts[0] for p in (Path(name) for name in fixtures.snapshot(self.repo))}
        self.assertEqual(roots, {'.agents', '.claude', '.codex', 'AGENTS.md', 'CLAUDE.md'})
        self.assertEqual(set(fixtures.snapshot(self.repo / '.codex')), {'agents', 'agents/code-reviewer.toml'})
        target.write_text(target.read_text() + 'An edit.\n')
        self.assertIn('An edit.', (self.repo / '.claude/skills/review-change/SKILL.md').read_text())

    def test_command_metadata_body_and_matching_retry(self):
        source = self.command(text='---\nname: "review-change"\ndescription: \'Review: carefully\'\n---\n\n# Review\nKeep every instruction.\n')
        planned = sync.Sync(self.home, self.repo, False).run()
        # Simulate an interruption after all replacement writes but before retirement.
        planned.edits = [edit for edit in planned.edits if edit[0] != 'retire-command']
        planned.commit()
        self.assertTrue(source.exists())
        report = self.run_tool()
        self.assertFalse(source.exists())
        self.assertTrue(any(r['disposition'] == 'shared-native' for r in report['resources']))
        data = (self.repo / '.agents/skills/review-change/SKILL.md').read_text()
        self.assertTrue(data.endswith('\n# Review\nKeep every instruction.\n'))
        self.assertIn('description: "Review: carefully"', data)
        self.assertEqual(self.run_tool()['changes'], [])

    def test_matching_existing_skill_formatting_is_preserved(self):
        source = self.command(text='---\ndescription: Review changes.\n---\nReview.\n')
        skill = self.write('.agents/skills/review-change/SKILL.md', '---\ndescription: "Review changes."\nname: review-change\n---\nReview.\n')
        before = skill.read_bytes()
        self.run_tool()
        self.assertFalse(source.exists())
        self.assertEqual(skill.read_bytes(), before)

    def test_linked_shared_skill_body_cannot_authorize_command_removal(self):
        source = self.command()
        external = self.write('.agents/skills/review-change/SKILL.md', '---\nname: "review-change"\ndescription: "Run the review-change instructions."\n---\nReview changes carefully.\n', home=True)
        target = self.repo / '.agents/skills/review-change/SKILL.md'
        target.parent.mkdir(parents=True); target.symlink_to(external)
        before = fixtures.snapshot(self.home)
        self.run_tool(expected=1)
        self.assertTrue(source.exists())
        self.assertEqual(fixtures.snapshot(self.home), before)

    def test_interruption_after_skill_before_link(self):
        source = self.command()
        planned = sync.Sync(self.home, self.repo, False).run()
        write = next(e for e in planned.edits if e[0] == 'write' and e[1].name == 'SKILL.md')
        planned.edits = [write]
        planned.commit()
        self.run_tool()
        self.assertFalse(source.exists())
        self.assertTrue((self.repo / '.claude/skills/review-change').is_symlink())

    def test_command_collision_preserves_both(self):
        source = self.command()
        self.skill('.agents/skills/review-change', text='---\nname: review-change\ndescription: Existing.\n---\nDifferent.\n')
        before = source.read_bytes()
        report = self.run_tool(expected=1)
        self.assertEqual(source.read_bytes(), before)
        self.assertIn('Different.', (self.repo / '.agents/skills/review-change/SKILL.md').read_text())
        self.assertTrue(any(r['disposition'] == 'conflict' for r in report['resources']))

    def test_command_redirected_entry_and_duplicate_sources(self):
        self.command()
        other = self.repo / '.agents/skills/other'; other.mkdir(parents=True)
        entry = self.repo / '.claude/skills/review-change'; entry.parent.mkdir(parents=True)
        entry.symlink_to(other)
        self.run_tool(expected=1)
        self.assertTrue((self.repo / '.claude/commands/review-change.md').exists())
        self.assertEqual(entry.resolve(), other)
        entry.unlink()
        self.command('duplicate', '---\nname: review-change\n---\nOther.\n')
        self.run_tool(expected=1)
        self.assertFalse((self.repo / '.agents/skills/review-change').exists())

    def test_unsupported_commands_remain_in_place_without_failure(self):
        cases = {'arguments': '$ARGUMENTS[0]', 'position': '$1', 'shell': '!`git status`',
                 'plugin': '${CLAUDE_PLUGIN_ROOT}/tool', 'path': 'Read [guide](../guide.md).',
                 'model': '---\nmodel: sonnet\n---\nReview.', 'fork': '---\ncontext: fork\n---\nReview.',
                 'permissions': '---\nallowed-tools: Read\n---\nReview.', 'nested/name': 'Review.',
                 'Bad_Name': 'Review.', 'complex': '---\ndescription: |\n  Review\n---\nReview.'}
        paths = [self.command(name, text) for name, text in cases.items()]
        before = {p: p.read_bytes() for p in paths}
        report = self.run_tool()
        self.assertEqual({p: p.read_bytes() for p in paths}, before)
        self.assertFalse((self.repo / '.agents').exists())
        self.assertEqual(len([r for r in report['resources'] if r['disposition'] == 'content-reference']), len(paths))
        self.assertEqual(self.run_tool()['changes'], [])

    def test_supported_agent_changes_require_manual_source_selection(self):
        source = self.agent()
        self.run_tool()
        target = self.repo / '.codex/agents/code-reviewer.toml'
        original = target.read_bytes()
        source.write_text(source.read_text() + 'New instruction.\n')
        report = self.run_tool(expected=1)
        self.assertEqual(target.read_bytes(), original)
        issue = ' '.join(report['issues'])
        self.assertIn(str(source), issue); self.assertIn(str(target), issue)
        source.write_text(source.read_text().replace('New instruction.\n', ''))
        target.write_text(target.read_text() + '\nmodel = "custom"\n')
        changed = target.read_bytes()
        self.run_tool(expected=1)
        self.assertEqual(target.read_bytes(), changed)

    def test_agent_controls_complex_metadata_and_builtin_names_block_adaptation(self):
        cases = {'worker': '', 'with-model': 'model: sonnet\n', 'with-tools': 'tools: Read\n',
                 'permissions': 'permissionMode: bypassPermissions\n', 'memory': 'memory: project\n',
                 'complex': 'description: |\n  Complex\n', 'nested-hooks': 'hooks:\n  SessionStart: []\n',
                 'unknown': 'other: value\n', 'paths': ''}
        originals = [self.agent(name, fields, body='Read ../rules.md.\n' if name == 'paths' else 'Review.\n') for name, fields in cases.items()]
        before = {p: p.read_bytes() for p in originals}
        report = self.run_tool(expected=1)
        self.assertEqual({p: p.read_bytes() for p in originals}, before)
        self.assertFalse((self.repo / '.codex/agents').exists())
        self.assertEqual(len(report['issues']), len(cases))

    def test_existing_native_name_collision(self):
        source = self.agent()
        self.write('.codex/agents/other-file.toml', 'name="code-reviewer"\ndescription="existing"\ndeveloper_instructions="existing"\n')
        self.run_tool(expected=1)
        self.assertTrue(source.exists())
        self.assertFalse((self.repo / '.codex/agents/code-reviewer.toml').exists())

    def test_rules_keep_conditions_and_do_not_reference_unsupported_conditions(self):
        self.write('.claude/rules/nested/all.md', 'Use clear names.\n')
        self.write('.claude/rules/list.md', '---\npaths: ["src/**", "lib/**/*.{js,ts}"]\n---\nValidate.\n')
        self.write('.claude/rules/complex.md', '---\npaths: &shared ["src/**"]\n---\nRestricted.\n')
        self.run_tool(expected=1)
        guidance = (self.repo / 'AGENTS.md').read_text()
        self.assertIn('For work in this scope, consult ".claude/rules/nested/all.md"', guidance)
        self.assertIn('["src/**", "lib/**/*.{js,ts}"]', guidance)
        self.assertNotIn('.claude/rules/complex.md', guidance)

    def test_resources_readonly_and_scope_isolation(self):
        self.agent(); self.command()
        self.command('global-command', home=True)
        self.agent('global-agent', home=True)
        before = fixtures.snapshot(self.base)
        report = self.run_tool('check', expected=1)
        self.assertTrue(report['resources']); self.assertEqual(fixtures.snapshot(self.base), before)
        self.run_tool('--dry-run'); self.assertEqual(fixtures.snapshot(self.base), before)
        home_before = fixtures.snapshot(self.home)
        self.run_tool(); self.assertEqual(fixtures.snapshot(self.home), home_before)
        project_before = fixtures.snapshot(self.repo)
        self.run_tool(scope='global'); self.assertEqual(fixtures.snapshot(self.repo), project_before)
        self.assertFalse((self.home / '.claude/commands/global-command.md').exists())
        self.assertTrue((self.home / '.codex/agents/global-agent.toml').exists())
        self.assertEqual(self.run_tool(scope='global')['changes'], [])

    def test_global_references_point_only_to_selected_home(self):
        rule = self.write('.claude/rules/global.md', 'Be concise.\n', home=True)
        self.write('.claude/rules/project.md', 'Project only.\n')
        self.run_tool(scope='global')
        instructions = (self.home / '.codex/AGENTS.md').read_text()
        self.assertIn(str(rule), instructions)
        self.assertNotIn('project.md', instructions)
        self.assertEqual((self.home / '.claude/CLAUDE.md').read_text(), instructions)

    def test_relocation_nested_worktree_and_missing_reference_cleanup(self):
        self.command()
        self.write('.claude/rules/folder with spaces/rule.md', 'Use clear names.\n')
        self.write('.git', 'gitdir: elsewhere\n')
        self.run_tool()
        relocated = self.base / 'relocated repo'; shutil.move(str(self.repo), relocated); self.repo = relocated
        nested = self.repo / 'nested'; nested.mkdir()
        self.assertEqual(self.run_tool(project=nested)['changes'], [])
        self.assertTrue((self.repo / '.claude/skills/review-change/SKILL.md').is_file())
        (self.repo / '.claude/rules/folder with spaces/rule.md').unlink()
        before = fixtures.snapshot(self.base)
        self.run_tool('check', expected=1)
        self.assertEqual(fixtures.snapshot(self.base), before)
        self.run_tool()
        self.assertNotIn('folder with spaces', (self.repo / 'AGENTS.md').read_text())

    def test_outside_scope_resources_preserved(self):
        external = self.write('.claude/commands/external.md', 'Global private instructions.\n', home=True)
        path = self.repo / '.claude/commands/external.md'; path.parent.mkdir(parents=True); path.symlink_to(external)
        before = fixtures.snapshot(self.home)
        self.run_tool(expected=1)
        self.assertEqual(fixtures.snapshot(self.home), before)
        self.assertNotIn('Global private', (self.repo / 'AGENTS.md').read_text())
        self.assertFalse((self.repo / '.agents').exists())

    def test_modified_command_detected_before_any_write(self):
        command = self.command()
        planned = sync.Sync(self.home, self.repo, False).run()
        command.write_text('Edited during preflight.\n')
        with self.assertRaises(sync.ConfigError):
            planned.commit()
        self.assertFalse((self.repo / '.agents').exists())
        self.assertFalse((self.repo / 'AGENTS.md').exists())

    def test_modified_link_before_retirement_preserves_command(self):
        source = self.command()
        planned = sync.Sync(self.home, self.repo, False).run()
        original = Path.symlink_to
        def redirected(path, target, *args, **kwargs):
            if path.name == 'review-change':
                return original(path, 'redirected', *args, **kwargs)
            return original(path, target, *args, **kwargs)
        with patch.object(Path, 'symlink_to', redirected), self.assertRaises(sync.ConfigError):
            planned.commit()
        self.assertTrue(source.exists())

    def test_provider_specific_skill_preserved_and_referenced(self):
        path = self.skill('.claude/skills/controlled', text='---\nname: controlled\ndescription: Controlled review.\nallowed-tools: Read\n---\nReview.\n')
        before = fixtures.snapshot(path)
        report = self.run_tool()
        self.assertEqual(fixtures.snapshot(path), before)
        self.assertFalse((self.repo / '.agents/skills/controlled').exists())
        self.assertTrue(any('allowed-tools' in r['compatibility'] for r in report['resources']))

    def test_malformed_metadata_fails_without_writes(self):
        self.command(text='---\nname: never-closed\nReview.')
        before = fixtures.snapshot(self.base)
        report = self.run_tool(expected=2)
        self.assertIn('frontmatter', report['error'])
        self.assertEqual(fixtures.snapshot(self.base), before)


if __name__ == '__main__':
    unittest.main()
