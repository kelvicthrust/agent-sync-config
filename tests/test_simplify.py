import json
import os
from pathlib import Path
import shutil
import unittest

import test_sync as fixtures
from test_sync import snapshot, sync, ROOT


class SimplificationTests(unittest.TestCase):
    setUp = fixtures.ConfigurationTests.setUp
    write = fixtures.ConfigurationTests.write
    skill = fixtures.ConfigurationTests.skill
    run_tool = fixtures.ConfigurationTests.run_tool
    hook = fixtures.ConfigurationTests.hook

    def legacy_hooks(self, base, records):
        records['hook_commands'] = {}
        for provider, relative in [('codex', '.codex/hooks.json'), ('claude', '.claude/settings.json')]:
            command = f'python3 {base}/.agents/skills/agent-sync-config/scripts/agent_sync_config.py hook --scope project --provider {provider}'
            handler = {'type': 'command', 'command': command, 'timeout': 5}
            path = base / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({'hooks': {event: [{'hooks': [handler]}] for event in ['SessionStart', 'UserPromptSubmit']}}))
            records['hook_commands'][provider] = [command]

    def legacy_project(self):
        self.run_tool()
        path = self.repo / '.agents/agent-sync.json'
        state = json.loads(path.read_text())
        package = self.repo / '.agents/skills/agent-sync-config'
        shutil.copytree(ROOT / 'skills/agent-sync-config', package, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        state['tool_digest'] = sync.tree_digest(package)
        link = self.repo / '.claude/skills/agent-sync-config'
        link.symlink_to('../../.agents/skills/agent-sync-config')
        state['links']['.claude/skills/agent-sync-config'] = os.readlink(link)
        self.legacy_hooks(self.repo, state)
        path.write_text(json.dumps(state))
        return package

    def legacy_global(self):
        self.skill('agent-config/skills/review-code', home=True)
        self.run_tool(scope='global')
        path = self.home / 'agent-config/.agent-sync.json'
        state = json.loads(path.read_text())
        folder = self.home / '.codex/skills'; folder.mkdir(parents=True)
        for name, record in state['skills'].items():
            link = folder / name
            link.symlink_to(f'../../agent-config/skills/{name}')
            key = str(link.relative_to(self.home))
            state['links'][key] = os.readlink(link)
            record['entrypoints'][key] = os.readlink(link)
        path.write_text(json.dumps(state))
        registry_path = self.home / '.local/state/agent-sync-config/registry.json'
        registry = json.loads(registry_path.read_text())
        self.legacy_hooks(self.home, registry)
        registry['global_hooks_audit_only'] = True
        registry_path.write_text(json.dumps(registry))

    def test_minimal_project_and_immediate_sharing_after_relocation(self):
        original = self.skill('.claude/skills/review-code')
        self.write('AGENTS.md', '# Existing project instructions\n')
        self.run_tool()
        self.assertTrue(original.is_symlink())
        original.joinpath('SKILL.md').write_text('new shared skill')
        self.assertEqual((self.repo / '.agents/skills/review-code/SKILL.md').read_text(), 'new shared skill')
        self.assertEqual((self.repo / 'CLAUDE.md').read_text(), '@AGENTS.md\n')
        self.assertFalse((self.repo / '.codex').exists())
        self.assertFalse((self.repo / '.claude/settings.json').exists())
        self.assertEqual([p.name for p in (self.repo / '.agents/skills').iterdir()], ['review-code'])
        moved = self.base / 'moved'; self.repo.rename(moved)
        self.assertEqual((moved / '.claude/skills/review-code/SKILL.md').read_text(), 'new shared skill')
        nested = moved / 'nested'; nested.mkdir()
        self.assertEqual(self.run_tool(project=nested)['project'], str(moved))
        self.assertEqual(self.run_tool(project=moved)['changes'], [])

    def test_project_migration_read_only_ownership_and_scope(self):
        self.run_tool(scope='global')
        package = self.legacy_project()
        before_home = snapshot(self.home / 'agent-config')
        before_codex = snapshot(self.home / '.codex')
        before = snapshot(self.base)
        self.run_tool('check', expected=1)
        self.assertEqual(snapshot(self.base), before)
        self.run_tool()
        self.assertFalse(package.exists())
        self.assertFalse((self.repo / '.claude/skills/agent-sync-config').exists())
        self.assertFalse((self.repo / '.codex/hooks.json').exists())
        self.assertFalse((self.repo / '.claude/settings.json').exists())
        state = json.loads((self.repo / '.agents/agent-sync.json').read_text())
        self.assertNotIn('tool_digest', state)
        self.assertNotIn('hook_commands', state)
        self.assertEqual(snapshot(self.home / 'agent-config'), before_home)
        self.assertEqual(snapshot(self.home / '.codex'), before_codex)
        self.assertTrue(any((self.home / '.local/state/agent-sync-config/backups').iterdir()))
        self.assertEqual(self.run_tool()['changes'], [])

    def test_modified_package_or_hook_or_link_blocks_runtime_deletion(self):
        for kind in ['package', 'hook', 'matcher', 'link']:
            with self.subTest(kind=kind):
                package = self.legacy_project()
                if kind == 'package':
                    (package / 'SKILL.md').write_text('local edits')
                elif kind in ['hook', 'matcher']:
                    path = self.repo / '.codex/hooks.json'
                    doc = json.loads(path.read_text())
                    if kind == 'hook':
                        doc['hooks']['SessionStart'][0]['hooks'][0]['timeout'] = 12
                    else:
                        doc['hooks']['SessionStart'][0]['matcher'] = 'startup'
                    path.write_text(json.dumps(doc))
                else:
                    link = self.repo / '.claude/skills/agent-sync-config'
                    link.unlink(); link.symlink_to('/unrelated')
                before = snapshot(package)
                self.run_tool(expected=1)
                self.assertEqual(snapshot(package), before)
                self.assertTrue((self.repo / '.codex/hooks.json').exists())
                shutil.rmtree(self.repo); self.repo.mkdir()

    def test_migration_preserves_unrelated_hooks_settings_and_disabled_controls(self):
        self.legacy_project()
        path = self.repo / '.claude/settings.json'
        doc = json.loads(path.read_text())
        unrelated = {'matcher': 'startup', 'hooks': [{'type': 'command', 'command': 'unrelated'}]}
        doc['hooks']['SessionStart'].append(unrelated)
        doc['disableAllHooks'] = True
        doc['permissions'] = {'deny': ['Read(secret)']}
        path.write_text(json.dumps(doc)); path.chmod(0o644)
        self.run_tool()
        result = json.loads(path.read_text())
        self.assertEqual(result, {'hooks': {'SessionStart': [unrelated]}, 'disableAllHooks': True, 'permissions': doc['permissions']})
        self.assertEqual(path.stat().st_mode & 0o777, 0o644)

    def test_global_migration_missing_legacy_alias_is_not_removal(self):
        self.run_tool()
        before_project = snapshot(self.repo)
        self.legacy_global()
        (self.home / '.codex/skills/review-code').unlink()
        self.write('.codex/skills/.system/keep', 'system', home=True)
        before = snapshot(self.base)
        report = self.run_tool('check', scope='global', expected=1)
        self.assertEqual(report['pending_removals'], {})
        self.assertEqual(snapshot(self.base), before)
        self.run_tool(scope='global')
        state = json.loads((self.home / 'agent-config/.agent-sync.json').read_text())
        self.assertFalse(any(key.startswith('.codex/skills/') for key in state['links']))
        self.assertFalse(any(key.startswith('.codex/skills/') for r in state['skills'].values() for key in r['entrypoints']))
        self.assertFalse((self.home / '.codex/hooks.json').exists())
        self.assertEqual((self.home / '.codex/skills/.system/keep').read_text(), 'system')
        self.assertEqual(snapshot(self.repo), before_project)
        self.assertEqual(self.run_tool(scope='global')['changes'], [])

    def test_modified_legacy_alias_and_unowned_files_preserved(self):
        self.legacy_global()
        link = self.home / '.codex/skills/review-code'
        link.unlink(); link.symlink_to('/unrelated')
        unowned = self.write('.codex/skills/unowned/SKILL.md', 'unowned', home=True)
        self.run_tool(scope='global', expected=1)
        self.assertEqual(os.readlink(link), '/unrelated')
        self.assertEqual(unowned.read_text(), 'unowned')
        state = json.loads((self.home / 'agent-config/.agent-sync.json').read_text())
        self.assertIn('.codex/skills/review-code', state['links'])

    def test_uninstall_old_aliases_without_recreation(self):
        self.legacy_global()
        self.run_tool('uninstall', '--yes', '--purge-shared-sources', scope='global')
        self.assertFalse((self.home / '.codex/skills/review-code').exists())
        self.assertTrue((self.home / '.agents/skills/review-code/SKILL.md').is_file())
        self.assertFalse((self.home / '.agents/skills/review-code').is_symlink())
        self.assertTrue((self.home / '.claude/skills/review-code/SKILL.md').is_file())

    def test_retired_hook_compatibility_never_repairs_or_writes(self):
        self.run_tool(); self.run_tool(scope='global')
        self.skill('.agents/skills/review-code')
        before = snapshot(self.base)
        with sync.lock(self.home):
            locked = snapshot(self.base)
            for scope in ['project', 'global']:
                self.assertEqual(self.hook(scope=scope, extra={'sandbox_mode': 'workspace-write'}), {})
            self.assertEqual(snapshot(self.base), locked)
        self.assertEqual(snapshot(self.base), before)


if __name__ == '__main__':
    unittest.main()
