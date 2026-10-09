import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'skills/agent-sync-config/scripts/agent_sync_config.py'
spec = importlib.util.spec_from_file_location('agent_sync', SCRIPT)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def snapshot(root):
    return {str(p.relative_to(root)): (os.readlink(p) if p.is_symlink() else p.read_bytes() if p.is_file() else None,
            p.lstat().st_mode, p.lstat().st_mtime_ns) for p in sorted(root.rglob('*')) if '__pycache__' not in p.parts}


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.home, self.repo = self.base / 'home with spaces', self.base / 'repo with spaces'
        self.home.mkdir(); self.repo.mkdir()

    def write(self, relative, text, home=False):
        path = (self.home if home else self.repo) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def skill(self, relative, home=False, text=None):
        name = Path(relative).name
        return self.write(relative + '/SKILL.md', text or f'---\nname: {name}\ndescription: Fixture skill.\n---\nReview changes.\n', home).parent

    def run_tool(self, *args, expected=0, project=None, scope='project'):
        command = [sys.executable, str(SCRIPT), *args, '--home', str(self.home), '--json']
        if scope:
            command += ['--scope', scope]
        if scope != 'global':
            command += ['--project', str(project or self.repo)]
        result = subprocess.run(command, cwd=project or self.repo, capture_output=True, text=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def interactive(self, answer):
        with contextlib.redirect_stdout(io.StringIO()), patch.object(sys.stdin, 'isatty', return_value=True), \
                patch.object(sys.stdout, 'isatty', return_value=True), patch('builtins.input', side_effect=answer), \
                patch.object(Path, 'cwd', return_value=self.repo):
            return sync.main(['--home', str(self.home)])

    def test_fresh_native_layout_and_idempotence(self):
        self.run_tool()
        self.assertEqual(set(snapshot(self.repo)), {'AGENTS.md', 'CLAUDE.md'})
        self.assertEqual((self.repo / 'CLAUDE.md').read_text(), '@AGENTS.md\n')
        self.assertEqual(snapshot(self.home), {})
        before = snapshot(self.base)
        self.assertEqual(self.run_tool()['changes'], [])
        self.run_tool('check')
        self.assertEqual(snapshot(self.base), before)

    def test_project_snapshot_proves_global_isolation(self):
        self.skill('.agents/skills/global-skill', home=True)
        self.write('.codex/AGENTS.md', 'GLOBAL_SENTINEL', home=True)
        self.write('.claude/settings.json', '{"enabledPlugins":{"sample":true}}', home=True)
        before = snapshot(self.home)
        self.run_tool()
        self.assertEqual(snapshot(self.home), before)
        self.assertNotIn('GLOBAL_SENTINEL', (self.repo / 'AGENTS.md').read_text())
        self.assertFalse((self.repo / '.agents/skills/global-skill').exists())

    def test_global_native_layout_and_project_isolation(self):
        self.write('AGENTS.md', 'PROJECT_SENTINEL')
        self.write('.codex/AGENTS.md', 'PERSONAL_SENTINEL', home=True)
        self.skill('.agents/skills/global-skill', home=True)
        project_before = snapshot(self.repo)
        self.run_tool(scope='global')
        self.assertEqual(snapshot(self.repo), project_before)
        self.assertEqual((self.home / '.claude/CLAUDE.md').read_text(), 'PERSONAL_SENTINEL')
        self.assertEqual((self.home / '.claude/skills/global-skill').resolve(), self.home / '.agents/skills/global-skill')
        self.assertFalse((self.home / 'agent-config').exists())
        self.assertFalse((self.home / '.local').exists())
        self.assertFalse((self.home / '.codex/skills').exists())
        self.run_tool('check', scope='global')
        self.assertEqual(self.run_tool(scope='global')['changes'], [])

    def test_global_claude_only_adoption_and_immediate_sharing(self):
        self.write('.claude/CLAUDE.md', 'Personal instructions', home=True)
        self.skill('.claude/skills/review-code', home=True)
        self.run_tool(scope='global')
        agents = self.home / '.codex/AGENTS.md'
        agents.write_text('Updated personal instructions')
        self.assertEqual((self.home / '.claude/CLAUDE.md').read_text(), agents.read_text())
        canonical = self.home / '.agents/skills/review-code/SKILL.md'
        canonical.write_text('Updated skill')
        self.assertEqual((self.home / '.claude/skills/review-code/SKILL.md').read_text(), canonical.read_text())
        self.assertFalse((self.home / '.agents/skills/review-code').is_symlink())

    def test_fresh_scope_selection_refusal_and_cancel(self):
        before = snapshot(self.base)
        report = self.run_tool(scope=None, expected=2)
        self.assertTrue(report['selection_required'])
        for answers in (['q'], [''], [KeyboardInterrupt()], [EOFError()]):
            self.assertEqual(self.interactive(answers), 0)
            self.assertEqual(snapshot(self.base), before)

    def test_interactive_project_and_global_choice(self):
        self.assertEqual(self.interactive(['1']), 0)
        self.assertEqual(snapshot(self.home), {})
        self.assertTrue((self.repo / 'AGENTS.md').is_file())
        shutil.rmtree(self.repo); self.repo.mkdir()
        self.assertEqual(self.interactive(['2']), 0)
        self.assertEqual(snapshot(self.repo), {})
        self.assertTrue((self.home / '.codex/AGENTS.md').is_file())

    def test_each_local_marker_selects_project(self):
        for marker in ('.agents', '.claude', '.codex', 'AGENTS.md', 'AGENTS.override.md', 'CLAUDE.md', '.mcp.json'):
            with self.subTest(marker=marker):
                shutil.rmtree(self.repo); self.repo.mkdir()
                path = self.repo / marker
                if marker in ('.agents', '.claude', '.codex'):
                    path.mkdir()
                else:
                    path.write_text('{}' if marker == '.mcp.json' else 'Local instructions')
                report = self.run_tool(scope=None, expected=1 if marker == 'AGENTS.override.md' else 0)
                self.assertEqual(report['scope'], 'project')
                self.assertEqual(snapshot(self.home), {})

    def test_check_and_dry_run_are_read_only(self):
        before = snapshot(self.base)
        self.run_tool('check', expected=1, scope=None)
        self.run_tool('--dry-run')
        self.run_tool('check', expected=1, scope='global')
        self.run_tool('--dry-run', scope='global')
        self.assertEqual(snapshot(self.base), before)

    def test_existing_claude_instructions_and_context_reference(self):
        self.write('docs/context.md', 'CURATED_CONTEXT_SENTINEL')
        self.write('.claude/CLAUDE.md', '# Existing\nRead docs/context.md when planning.\n')
        self.run_tool()
        self.assertIn('Read docs/context.md', (self.repo / 'AGENTS.md').read_text())
        self.assertEqual((self.repo / '.claude/CLAUDE.md').read_text(), '@../AGENTS.md\n')
        self.assertEqual((self.repo / 'docs/context.md').read_text(), 'CURATED_CONTEXT_SENTINEL')
        self.assertFalse((self.repo / '.agents/context').exists())

    def test_differing_instructions_preserved_exactly(self):
        self.write('AGENTS.md', 'One')
        self.write('CLAUDE.md', 'Two')
        before = snapshot(self.repo)
        self.run_tool(expected=1)
        self.assertEqual(snapshot(self.repo), before)
        self.write('.codex/AGENTS.md', 'One', home=True)
        self.write('.claude/CLAUDE.md', 'Two', home=True)
        before = snapshot(self.home)
        self.run_tool(scope='global', expected=1)
        self.assertEqual(snapshot(self.home), before)

    def test_skill_adoption_links_and_native_allowlist(self):
        original = self.skill('.claude/skills/review-code')
        self.run_tool()
        canonical = self.repo / '.agents/skills/review-code'
        self.assertTrue(original.is_symlink())
        self.assertFalse(canonical.is_symlink())
        self.assertEqual(os.readlink(original), '../../.agents/skills/review-code')
        expected = {'AGENTS.md', 'CLAUDE.md', '.agents', '.agents/skills', '.agents/skills/review-code',
                    '.agents/skills/review-code/SKILL.md', '.claude', '.claude/skills', '.claude/skills/review-code'}
        self.assertEqual(set(snapshot(self.repo)), expected)
        self.assertEqual(snapshot(self.home), {})

    def test_immediate_skills_sharing_and_relocation(self):
        canonical = self.skill('.agents/skills/review-code')
        self.run_tool()
        (self.repo / '.claude/skills/review-code/SKILL.md').write_text('Shared edit')
        self.assertEqual((canonical / 'SKILL.md').read_text(), 'Shared edit')
        moved = self.base / 'relocated project'; self.repo.rename(moved)
        self.assertEqual((moved / '.claude/skills/review-code/SKILL.md').read_text(), 'Shared edit')
        self.assertEqual(self.run_tool(project=moved)['changes'], [])

    def test_new_skill_adoption_and_conflicting_copies(self):
        self.run_tool()
        self.skill('.claude/skills/new-skill')
        self.run_tool()
        self.assertTrue((self.repo / '.claude/skills/new-skill').is_symlink())
        self.skill('.agents/skills/review-code', text='One')
        self.skill('.claude/skills/review-code', text='Two')
        before = snapshot(self.base)
        self.run_tool(expected=1)
        self.assertEqual(snapshot(self.base), before)

    def test_missing_link_check_then_explicit_repair(self):
        self.skill('.agents/skills/review-code')
        self.run_tool()
        link = self.repo / '.claude/skills/review-code'; link.unlink()
        before = snapshot(self.base)
        self.run_tool('check', expected=1)
        self.assertEqual(snapshot(self.base), before)
        self.run_tool()
        self.assertTrue(link.is_symlink())

    def test_import_and_external_dependency_preservation(self):
        external = self.base / 'review-code'; external.mkdir()
        (external / 'SKILL.md').write_text('Portable fixture')
        before = snapshot(external)
        self.run_tool('--import-skill', str(external))
        self.assertEqual(snapshot(external), before)
        self.assertEqual((self.repo / '.agents/skills/review-code/SKILL.md').read_text(), 'Portable fixture')
        (external / 'dependency').symlink_to(self.home)
        fixture = self.base / 'another'; fixture.mkdir()
        before = snapshot(self.base)
        self.run_tool('--import-skill', str(external), project=fixture, expected=2)
        self.assertEqual(snapshot(self.base), before)

    def test_installed_synchronizer_excluded_in_both_scopes(self):
        for home in (False, True):
            self.skill('.agents/skills/agent-sync-config', home=home)
            self.skill('.claude/skills/agent-sync-config', home=home, text='Separate installer-owned copy')
        installed = {str(p): snapshot(p) for p in (self.repo / '.agents/skills/agent-sync-config',
                     self.repo / '.claude/skills/agent-sync-config', self.home / '.agents/skills/agent-sync-config',
                     self.home / '.claude/skills/agent-sync-config')}
        self.run_tool(); self.run_tool(scope='global')
        for path, before in installed.items():
            self.assertEqual(snapshot(Path(path)), before)
        self.assertFalse((self.home / 'agent-config').exists())
        for scope in ('project', 'global'):
            self.run_tool('--import-skill', str(ROOT / 'skills/agent-sync-config'), scope=scope, expected=2)

    def test_symlinks_and_cycles_preserved_without_outside_writes(self):
        external = self.base / 'external'; external.mkdir()
        (self.repo / '.agents').symlink_to(external)
        before = snapshot(self.base)
        self.run_tool(expected=2)
        self.assertEqual(snapshot(self.base), before)
        (self.repo / '.agents').unlink()
        provider = self.skill('.claude/skills/review-code')
        target = self.repo / '.agents/skills/review-code'; target.parent.mkdir(parents=True)
        target.symlink_to(provider)
        self.run_tool(expected=1)
        self.assertFalse(provider.is_symlink())
        self.assertEqual(target.resolve(), provider)

    def test_nested_git_worktree_and_non_git_discovery(self):
        (self.repo / '.git').mkdir()
        self.run_tool()
        nested = self.repo / 'nested'; nested.mkdir()
        self.assertEqual(self.run_tool(project=nested)['project'], str(self.repo))
        worktree = self.base / 'worktree'; worktree.mkdir()
        (worktree / '.git').write_text('gitdir: /fixture/common/git/worktrees/example')
        self.assertEqual(self.run_tool(project=worktree)['project'], str(worktree))
        nongit = self.base / 'non-git'; nongit.mkdir()
        self.assertEqual(self.run_tool(project=nongit)['project'], str(nongit))

    def test_argument_and_protected_target_refusal_without_writes(self):
        for args in (('--scope', 'global'), ('--scope', 'global', '--project-only'),
                     ('--personal-root', str(self.base / 'custom')), ('--import-mcp', 'x', '--mcp-source', 'codex')):
            self.run_tool(*args, expected=2)
        for path in (self.home, self.home / '.agents', self.home / '.claude', self.home / '.codex', self.home / 'agent-config'):
            if not path.exists():
                path.mkdir()
            protected_before = snapshot(self.base)
            self.run_tool(project=path, expected=2)
            self.assertEqual(snapshot(self.base), protected_before)
        self.assertFalse((self.base / 'custom').exists())
        self.assertEqual(snapshot(self.repo), {})

    def test_malformed_native_settings_error_before_writes(self):
        self.write('.claude/settings.json', '{invalid')
        before = snapshot(self.base)
        self.run_tool(scope=None, expected=2)
        self.assertEqual(snapshot(self.base), before)

    def test_preflight_revalidates_changes_before_writing(self):
        path = self.write('AGENTS.md', 'Original')
        operation = sync.Sync(self.home, self.repo, False).run()
        path.write_text('Concurrent change')
        with self.assertRaises(sync.ConfigError):
            operation.commit()
        self.assertFalse((self.repo / 'CLAUDE.md').exists())

    def test_interrupted_write_leaves_no_temp_files_and_retry_succeeds(self):
        with patch.object(sync.os, 'replace', side_effect=OSError('fixture interruption')):
            with self.assertRaises(OSError):
                sync.Sync(self.home, self.repo, True).run()
        self.assertEqual(snapshot(self.repo), {})
        self.run_tool()
        self.run_tool('check')
