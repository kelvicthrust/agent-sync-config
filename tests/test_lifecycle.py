"""Stateless installer boundaries and retired lifecycle commands."""
import json
import shutil
import unittest
import test_sync as fixtures
from test_sync import snapshot


class InstallerBoundaryTests(unittest.TestCase):
    setUp = fixtures.ConfigurationTests.setUp
    write = fixtures.ConfigurationTests.write
    skill = fixtures.ConfigurationTests.skill
    run_tool = fixtures.ConfigurationTests.run_tool

    def test_retired_commands_and_flags_never_write(self):
        self.skill('.agents/skills/review-code', home=True)
        before = snapshot(self.base)
        for args in (('remove-skill', 'review-code'), ('uninstall',), ('uninstall', '--yes'),
                     ('uninstall', '--purge-shared-sources'), ('--personal-root', str(self.base / 'custom'))):
            report = self.run_tool(*args, scope='global', expected=2)
            self.assertIn('retired', report['error'])
            self.assertEqual(snapshot(self.base), before)

    def test_full_skill_removal_has_no_restoration_source(self):
        source = self.skill('.agents/skills/review-code', home=True)
        self.run_tool(scope='global')
        (self.home / '.claude/skills/review-code').unlink()
        shutil.rmtree(source)
        self.run_tool(scope='global')
        self.assertFalse(source.exists())
        self.assertFalse((self.home / '.claude/skills/review-code').exists())

    def test_dangling_reference_is_reported_and_preserved(self):
        source = self.skill('.agents/skills/review-code', home=True)
        self.run_tool(scope='global')
        shutil.rmtree(source)
        report = self.run_tool(scope='global', expected=1)
        self.assertNotIn('pending_removals', report)
        self.assertTrue((self.home / '.claude/skills/review-code').is_symlink())
        self.assertFalse(source.exists())

    def test_synchronizer_removal_never_recreates_it(self):
        source = self.skill('.agents/skills/agent-sync-config', home=True)
        self.run_tool(scope='global')
        shutil.rmtree(source)
        report = self.run_tool(scope='global')
        self.assertNotIn('pending_removals', report)
        self.assertFalse(source.exists())

    def test_installer_metadata_is_untouched(self):
        lock = self.write('.agents/.skill-lock.json', json.dumps({'version': 3, 'skills': {'agent-sync-config': {'source': 'fixture'}}, 'extra': 'keep'}), home=True)
        before = lock.read_bytes()
        self.run_tool(scope='global')
        self.assertEqual(lock.read_bytes(), before)
        self.run_tool('check', scope='global')
        self.assertEqual(lock.read_bytes(), before)
