"""Existing custom resources are inspected, never automatically migrated/deleted."""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
import test_sync as fixtures
from test_sync import SCRIPT, snapshot, sync


class CompatibilityTests(unittest.TestCase):
    setUp = fixtures.ConfigurationTests.setUp
    write = fixtures.ConfigurationTests.write
    skill = fixtures.ConfigurationTests.skill
    run_tool = fixtures.ConfigurationTests.run_tool

    def test_project_legacy_resources_and_hooks_preserved(self):
        self.write('AGENTS.md', 'Original project instructions')
        self.write('.agents/agent-sync.json', '{"schema":1,"tool_digest":"old"}')
        self.write('.agents/mcp.json', '{"schema":1,"servers":{}}')
        self.skill('.agents/skills/agent-sync-config')
        self.write('.claude/settings.json', json.dumps({'disableAllHooks': True, 'hooks': {'SessionStart': [
            {'hooks': [{'type': 'command', 'command': 'python3 agent_sync_config.py hook', 'timeout': 5},
                       {'type': 'command', 'command': 'unrelated'}]}]}}))
        before = snapshot(self.base)
        self.run_tool('check', expected=1)
        self.assertEqual(snapshot(self.base), before)
        self.run_tool(expected=1)
        for name in ('.agents/agent-sync.json', '.agents/mcp.json', '.agents/skills/agent-sync-config/SKILL.md', '.claude/settings.json'):
            self.assertEqual(snapshot(self.repo)[name], before[str(self.repo.relative_to(self.base)) + '/' + name])
        self.assertEqual(snapshot(self.home), {})

    def test_global_legacy_sources_and_aliases_preserved(self):
        self.write('agent-config/AGENTS.md', 'Legacy personal content', home=True)
        self.write('.local/state/agent-sync-config/registry.json', '{}', home=True)
        self.write('.local/bin/agent-sync-config', 'Legacy wrapper', home=True)
        self.run_tool(scope='global', expected=1)
        before = snapshot(self.base)
        self.run_tool('check', scope='global', expected=1)
        self.assertEqual(snapshot(self.base), before)
        self.assertEqual((self.home / 'agent-config/AGENTS.md').read_text(), 'Legacy personal content')
        self.assertEqual(snapshot(self.repo), {})

    def test_legacy_native_instruction_links_not_replaced(self):
        source = self.write('agent-config/AGENTS.md', 'Legacy personal', home=True)
        (self.home / '.codex').mkdir()
        (self.home / '.codex/AGENTS.md').symlink_to('../agent-config/AGENTS.md')
        before = snapshot(self.base)
        self.run_tool(scope='global', expected=1)
        self.assertEqual(snapshot(self.base), before)
        self.assertEqual(source.read_text(), 'Legacy personal')

    def test_old_codex_aliases_and_system_directory_preserved(self):
        self.skill('.agents/skills/review-code')
        self.run_tool()
        alias = self.repo / '.codex/skills/review-code'; alias.parent.mkdir(parents=True)
        alias.symlink_to('../../.agents/skills/review-code')
        self.write('.codex/skills/.system/sample/SKILL.md', 'System skill')
        before = snapshot(self.base)
        self.run_tool(expected=1)
        self.assertEqual(snapshot(self.base), before)
        self.assertEqual(os.readlink(alias), '../../.agents/skills/review-code')

    def test_existing_context_and_unrelated_hooks_are_untouched(self):
        self.write('.claude/context/example.md', 'Existing private context')
        settings = self.write('.claude/settings.json', '{"disableAllHooks":true,"hooks":{"SessionStart":[{"matcher":"startup","hooks":[{"type":"command","command":"unrelated"}]}]}}')
        before = settings.read_bytes()
        self.run_tool()
        self.assertEqual(settings.read_bytes(), before)
        self.assertEqual((self.repo / '.claude/context/example.md').read_text(), 'Existing private context')
        self.assertFalse((self.repo / '.agents/context').exists())

    def test_retired_hook_noop_even_with_legacy_arguments(self):
        before = snapshot(self.base)
        result = subprocess.run([sys.executable, str(SCRIPT), 'hook', '--scope', 'global', '--home', str(self.home), '--provider', 'claude'],
                                input=json.dumps({'cwd': str(self.repo)}), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, '')
        self.assertEqual(snapshot(self.base), before)
