"""Global lifecycle tests use only disposable homes, never real configuration."""
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

from test_sync import snapshot

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/agent-sync-config/scripts/agent_sync_config.py"
spec = importlib.util.spec_from_file_location("lifecycle_sync", SCRIPT)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.home = self.base / "home with spaces"
        self.home.mkdir()
        self.project = self.base / "project"
        self.project.mkdir()
        self.personal = self.home / "agent-config"
        self.lockfile = self.home / ".agents/.skill-lock.json"
        self.source = self.base / "review-code"
        self.source.mkdir()
        (self.source / "SKILL.md").write_text('---\nname: review-code\ndescription: Review a fixture.\n---\nReview changes.\n')

    def cli(self, *args, code=0, personal=None):
        command = [sys.executable, str(SCRIPT), *args, "--scope", "global", "--home", str(self.home), "--json"]
        if personal:
            command += ["--personal-root", str(personal)]
        result = subprocess.run(command, cwd=self.project, capture_output=True, text=True)
        self.assertEqual(result.returncode, code, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def setup(self, cli_record=True):
        if cli_record:
            self.lockfile.parent.mkdir(parents=True)
            self.lockfile.write_text(json.dumps({"version": 3, "extra": "preserve", "dismissed": {"findSkillsPrompt": True},
                                               "skills": {"review-code": {"source": "fixture/repo", "sourceType": "local"},
                                                          "unrelated": {"source": "other/repo"}}}))
        self.cli("--import-skill", str(self.source))

    def manifest(self):
        return json.loads((self.personal / ".agent-sync.json").read_text())

    def interactive(self, args, answers):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.object(sys.stdin, "isatty", return_value=True), \
                patch.object(sys.stdout, "isatty", return_value=True), patch("builtins.input", side_effect=answers):
            code = sync.main([*args, "--scope", "global", "--home", str(self.home)])
        return code, output.getvalue()

    def test_remove_preview_confirmation_tombstone_and_import(self):
        self.setup()
        before = snapshot(self.base)
        report = self.cli("remove-skill", "review-code", "--dry-run")
        self.assertTrue(report["changes"])
        self.assertEqual(snapshot(self.base), before)
        self.cli("remove-skill", "review-code", code=2)
        self.assertEqual(snapshot(self.base), before)
        self.cli("remove-skill", "review-code", "--yes")
        for directory in ("agent-config/skills", ".agents/skills", ".claude/skills"):
            self.assertFalse(os.path.lexists(self.home / directory / "review-code"))
        self.assertIn("review-code", self.manifest()["removed_skills"])
        lock = json.loads(self.lockfile.read_text())
        self.assertNotIn("review-code", lock["skills"])
        self.assertEqual(lock["extra"], "preserve")
        self.assertEqual(lock["dismissed"], {"findSkillsPrompt": True})
        self.assertIn("unrelated", lock["skills"])
        self.cli()
        self.assertFalse((self.personal / "skills/review-code").exists())
        self.cli("remove-skill", "review-code", "--yes")
        self.cli("--import-skill", str(self.source))
        self.assertNotIn("review-code", self.manifest()["removed_skills"])
        self.assertTrue((self.home / ".claude/skills/review-code").is_symlink())

    def test_changed_source_copy_link_and_lock_block_entire_removal(self):
        for kind in ("source", "copy", "link", "lock"):
            with self.subTest(kind=kind):
                # One setup per iteration avoids accepting deliberately changed content.
                if self.personal.exists():
                    shutil.rmtree(self.home)
                    self.home.mkdir()
                self.setup()
                if kind == "source":
                    (self.personal / "skills/review-code/SKILL.md").write_text("local edit")
                elif kind == "copy":
                    link = self.home / ".claude/skills/review-code"
                    link.unlink(); link.mkdir(); (link / "SKILL.md").write_text("provider edit")
                elif kind == "link":
                    link = self.home / ".claude/skills/review-code"
                    link.unlink(); link.symlink_to(self.source)
                else:
                    doc = json.loads(self.lockfile.read_text())
                    doc["skills"]["review-code"]["source"] = "different/repo"
                    self.lockfile.write_text(json.dumps(doc))
                before = snapshot(self.base)
                self.assertTrue(self.cli("remove-skill", "review-code", "--yes", code=1)["issues"])
                self.assertEqual(snapshot(self.base), before)

    def test_external_removal_check_hook_and_yes_do_not_restore(self):
        self.setup()
        (self.home / ".claude/skills/review-code").unlink()
        before = snapshot(self.base)
        report = self.cli("check", code=1)
        self.assertIn("review-code", report["pending_removals"])
        self.assertEqual(snapshot(self.base), before)
        payload = json.dumps({"cwd": str(self.project), "session_id": "fixture", "hook_event_name": "UserPromptSubmit"})
        result = subprocess.run([sys.executable, str(SCRIPT), "hook", "--scope", "global", "--provider", "claude", "--home", str(self.home)],
                                input=payload, capture_output=True, text=True, env={**os.environ, "AGENT_SYNC_READ_ONLY": "1"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Pending skill removal", result.stdout)
        self.assertEqual(snapshot(self.base), before)
        self.cli("--yes", code=1)
        self.assertFalse((self.home / ".claude/skills/review-code").exists())
        code, output = self.interactive([], ["q"])
        self.assertEqual(code, 0, output)
        self.assertFalse((self.home / ".claude/skills/review-code").exists())
        code, output = self.interactive([], ["2"])
        self.assertEqual(code, 0, output)
        self.assertTrue((self.home / ".claude/skills/review-code").is_symlink())

    def test_interactive_complete_removal_and_reinstallation(self):
        self.setup()
        (self.home / ".claude/skills/review-code").unlink()
        code, output = self.interactive([], ["1", "y"])
        self.assertEqual(code, 0, output)
        self.assertFalse((self.personal / "skills/review-code").exists())
        native = self.home / ".agents/skills/review-code"
        shutil.copytree(self.source, native)
        before = snapshot(self.base)
        self.assertEqual(self.cli("check", code=1)["pending_removals"]["review-code"]["kind"], "reinstall")
        self.assertEqual(snapshot(self.base), before)
        self.cli(code=1)
        self.assertFalse((self.personal / "skills/review-code").exists())
        code, output = self.interactive([], ["2"])
        self.assertEqual(code, 0, output)
        self.assertNotIn("review-code", self.manifest()["removed_skills"])
        self.assertTrue((self.personal / "skills/review-code").is_dir())

    def test_lock_disappearance_and_legacy_manifest_upgrade(self):
        self.setup()
        doc = json.loads(self.lockfile.read_text()); del doc["skills"]["review-code"]
        self.lockfile.write_text(json.dumps(doc))
        self.assertIn("review-code", self.cli(code=1)["pending_removals"])
        code, output = self.interactive([], ["2"])
        self.assertEqual(code, 0, output)
        self.assertIn("review-code", json.loads(self.lockfile.read_text())["skills"])
        manifest = self.manifest()
        for field in ("lifecycle_version", "skills", "removed_skills", "shared_files", "wrapper_digest"):
            manifest.pop(field, None)
        (self.personal / ".agent-sync.json").write_text(json.dumps(manifest))
        before = snapshot(self.base)
        self.cli("check")
        self.assertEqual(snapshot(self.base), before)
        self.cli()
        self.assertIn("review-code", self.manifest()["skills"])

    def test_malformed_cli_metadata_does_not_write(self):
        self.setup()
        for text in ('not json', '{"version": 3, "skills": []}', '{"version": 99, "skills": {}}'):
            self.lockfile.write_text(text)
            before = snapshot(self.base)
            self.cli("remove-skill", "review-code", "--yes", code=2)
            self.cli("uninstall", "--yes", code=2)
            self.assertEqual(snapshot(self.base), before)

    def test_uninstall_and_purge_preserve_native_data_and_project(self):
        self.setup()
        subprocess.run([sys.executable, str(SCRIPT), "--scope", "project", "--project", str(self.project), "--home", str(self.home)],
                       check=True, capture_output=True)
        before_project = snapshot(self.project)
        (self.personal / "keep-private.txt").write_text("unowned")
        (self.personal / "mcp.json").write_text('{"schema": 1, "servers": {"probe": {"transport": "stdio", "command": "python3"}}}')
        self.cli()
        native_mcp = (self.home / ".codex/config.toml").read_bytes()
        claude = self.home / ".claude/settings.json"
        doc = json.loads(claude.read_text()); doc["permissions"] = {"deny": ["Read(secret)"]}; doc["disableAllHooks"] = True
        doc["hooks"]["SessionStart"].append({"matcher": "startup", "hooks": [{"type": "command", "command": "unrelated"}]})
        claude.write_text(json.dumps(doc))
        instructions = (self.personal / "AGENTS.md").read_bytes()
        before = snapshot(self.base)
        self.cli("uninstall", "--purge-shared-sources", "--dry-run")
        self.assertEqual(snapshot(self.base), before)
        self.cli("uninstall", "--yes")
        self.assertTrue(self.manifest()["detached"])
        self.assertTrue((self.personal / "skills/review-code").is_dir())
        self.assertFalse((self.personal / "skills/agent-sync-config").exists())
        self.assertFalse((self.home / ".local/bin/agent-sync-config").exists())
        for relative in (".codex/AGENTS.md", ".claude/CLAUDE.md"):
            native = self.home / relative
            self.assertFalse(native.is_symlink())
            self.assertEqual(native.read_bytes(), instructions)
        self.assertFalse((self.home / ".agents/skills/review-code").is_symlink())
        self.assertTrue((self.home / ".claude/skills/review-code/SKILL.md").is_file())
        self.assertEqual((self.home / ".codex/config.toml").read_bytes(), native_mcp)
        doc = json.loads(claude.read_text())
        self.assertEqual(doc["permissions"], {"deny": ["Read(secret)"]})
        self.assertTrue(doc["disableAllHooks"])
        self.assertEqual(doc["hooks"]["SessionStart"], [{"matcher": "startup", "hooks": [{"type": "command", "command": "unrelated"}]}])
        self.assertEqual(snapshot(self.project), before_project)
        self.assertEqual(self.cli("uninstall", "--yes")["changes"], [])
        self.cli("uninstall", "--yes", "--purge-shared-sources")
        self.assertEqual(sorted(item.name for item in self.personal.iterdir()), ["keep-private.txt"])
        self.assertTrue((self.home / ".claude/skills/review-code/SKILL.md").is_file())
        self.assertEqual(snapshot(self.project), before_project)

    def test_setup_skill_external_removal_offers_uninstall(self):
        self.setup(False)
        (self.home / ".agents/skills/agent-sync-config").unlink()
        (self.home / ".claude/skills/agent-sync-config").unlink()
        self.assertIn("agent-sync-config", self.cli(code=1)["pending_removals"])
        code, output = self.interactive([], ["1", "y"])
        self.assertEqual(code, 0, output)
        self.assertIn("Uninstall synchronizer", output)
        self.assertFalse((self.home / ".local/bin/agent-sync-config").exists())
        self.assertTrue((self.home / ".agents/skills/review-code/SKILL.md").is_file())

    def test_modified_wrapper_or_runtime_blocks_all_uninstall_edits(self):
        self.setup()
        wrapper = self.home / ".local/bin/agent-sync-config"
        wrapper.write_text(wrapper.read_text() + "# edited\n")
        before = snapshot(self.base)
        self.cli("uninstall", "--yes", "--purge-shared-sources", code=1)
        self.assertEqual(snapshot(self.base), before)

    def test_uninstall_recovery_after_source_and_runtime_deletion(self):
        self.setup()
        operation = sync.Sync(self.home, None, True, scope="global")
        original = operation.delete_owned
        runtime = self.personal / "skills/agent-sync-config"
        def fail_once(path):
            original(path)
            if path == runtime:
                raise OSError("simulated interruption")
        with patch.object(operation, "delete_owned", side_effect=fail_once):
            with self.assertRaises(OSError):
                operation.uninstall(True)
        self.assertIn("global_uninstall", json.loads(operation.registry_path.read_text()))
        self.cli("uninstall", "--yes", "--purge-shared-sources")
        self.assertFalse(self.personal.exists())
        self.assertTrue((self.home / ".claude/skills/review-code/SKILL.md").is_file())
        self.assertNotIn("global_uninstall", json.loads(operation.registry_path.read_text()))

    def test_custom_root_and_xdg_lock(self):
        self.personal = self.base / "custom personal source"
        self.cli("--import-skill", str(self.source), personal=self.personal)
        self.cli("uninstall", "--yes", "--purge-shared-sources")
        self.assertFalse(self.personal.exists())
        xdg = self.base / "xdg state"
        with patch.dict(os.environ, {"HOME": str(self.home), "XDG_STATE_HOME": str(xdg)}):
            operation = sync.Sync(self.home, None, True, scope="global")
            self.assertEqual(operation.cli_lock_path(), xdg / "skills/.skill-lock.json")

    def test_purge_conflicting_mcp_and_owned_file_type_preserve_everything(self):
        self.setup()
        path = self.personal / "mcp.json"
        path.write_text('{"schema": 1, "servers": {"probe": {"transport": "stdio", "command": "python3"}}}')
        self.cli()
        path.write_text('{"schema": 1, "servers": {"probe": {"transport": "stdio", "command": "different"}}}')
        before = snapshot(self.base)
        self.cli("uninstall", "--yes", "--purge-shared-sources", code=1)
        self.assertEqual(snapshot(self.base), before)
        path.unlink(); path.mkdir(); (path / "private.txt").write_text("unowned")
        before = snapshot(self.base)
        self.cli("uninstall", "--yes", "--purge-shared-sources", code=1)
        self.assertEqual(snapshot(self.base), before)

    def test_dry_run_without_lock_and_pending_removal_leaves_other_skills_working(self):
        self.setup()
        before = snapshot(self.base)
        with sync.lock(self.home):
            self.cli("uninstall", "--dry-run")
        self.assertEqual(snapshot(self.base), before)
        (self.home / ".claude/skills/review-code").unlink()
        other = self.personal / "skills/other-skill"
        other.mkdir(); (other / "SKILL.md").write_text("Other skill")
        self.cli(code=1)
        self.assertTrue((self.home / ".claude/skills/other-skill").is_symlink())
        self.assertFalse((self.home / ".claude/skills/review-code").exists())

    def test_owned_native_alias_and_namespaced_cli_key(self):
        self.lockfile.parent.mkdir(parents=True)
        self.lockfile.write_text(json.dumps({"version": 3, "skills": {
            "review:code": {"source": "fixture/repo"}, "unrelated": {"source": "other/repo"}}}))
        self.cli("--import-skill", str(self.source))
        native = self.home / ".claude/skills/review-code"
        native.unlink(); native.symlink_to("../../.agents/skills/review-code")
        self.cli()
        record = self.manifest()["skills"]["review-code"]
        self.assertEqual(record["entrypoints"][".claude/skills/review-code"], "../../.agents/skills/review-code")
        self.assertEqual(record["cli"]["key"], "review:code")
        self.cli("remove-skill", "review-code", "--yes")
        self.assertNotIn("review:code", json.loads(self.lockfile.read_text())["skills"])
        self.assertIn("unrelated", json.loads(self.lockfile.read_text())["skills"])

    def test_publisher_tree_guard_and_runtime_edits_block_cleanup(self):
        self.setup()
        marker = self.personal / "bin/agent-sync-config"
        marker.parent.mkdir(); marker.write_text("publisher wrapper")
        before = snapshot(self.base)
        self.cli("remove-skill", "review-code", "--yes", code=1)
        self.cli("uninstall", "--yes", "--purge-shared-sources", code=1)
        self.assertEqual(snapshot(self.base), before)
        marker.unlink()
        runtime = self.personal / "skills/agent-sync-config/scripts/agent_sync_config.py"
        runtime.write_text(runtime.read_text() + "\n# edited\n")
        before = snapshot(self.base)
        self.cli("uninstall", "--yes", code=1)
        self.assertEqual(snapshot(self.base), before)

    def test_external_removal_cleanup_confirmation_can_cancel_without_writes(self):
        self.setup()
        (self.home / ".claude/skills/review-code").unlink()
        before = snapshot(self.base)
        code, output = self.interactive([], ["1", "n"])
        self.assertEqual(code, 0, output)
        self.assertIn(str(self.personal / "skills/review-code"), output)
        self.assertEqual(snapshot(self.base), before)

    def test_nested_vcs_blocks_purge_and_unrelated_empty_hook_groups_survive(self):
        self.setup()
        vcs = self.personal / "skills/review-code/.git"
        vcs.mkdir(); (vcs / "config").write_text("private history")
        self.cli()  # Accept the current skill, then verify VCS still cannot be purged.
        before = snapshot(self.base)
        self.cli("remove-skill", "review-code", "--yes", code=1)
        self.cli("uninstall", "--yes", "--purge-shared-sources", code=1)
        self.assertEqual(snapshot(self.base), before)
        shutil.rmtree(vcs)
        self.cli()
        path = self.home / ".claude/settings.json"
        doc = json.loads(path.read_text())
        doc["hooks"]["OtherEvent"] = [{"matcher": "anything", "hooks": [], "extra": "keep"}]
        path.write_text(json.dumps(doc))
        self.cli("uninstall", "--yes")
        self.assertEqual(json.loads(path.read_text())["hooks"]["OtherEvent"], doc["hooks"]["OtherEvent"])

    def test_reinstall_from_provider_copy_and_nonportable_uninstall(self):
        self.setup()
        self.cli("remove-skill", "review-code", "--yes")
        provider = self.home / ".claude/skills/review-code"
        shutil.copytree(self.source, provider)
        code, output = self.interactive([], ["2"])
        self.assertEqual(code, 0, output)
        self.assertTrue((self.home / ".agents/skills/review-code").is_symlink())
        (self.personal / "skills/review-code/dependency").symlink_to(self.source)
        self.cli()  # Source edits are accepted, but relocation would break dependencies.
        before = snapshot(self.base)
        self.cli("uninstall", "--yes", "--purge-shared-sources", code=1)
        self.assertEqual(snapshot(self.base), before)

    def test_malformed_personal_ownership_does_not_write(self):
        self.setup()
        original = self.manifest()
        path = self.personal / ".agent-sync.json"
        for change in ({"detached": "false"}, {"shared_files": {"AGENTS.md": "bad digest"}},
                       {"skills": {"review-code": {"digest": "bad digest", "entrypoints": {}}}}):
            path.write_text(json.dumps({**original, **change}))
            before = snapshot(self.base)
            self.cli("remove-skill", "review-code", "--yes", code=2)
            self.cli("uninstall", "--yes", code=2)
            self.assertEqual(snapshot(self.base), before)

    def test_conflicting_native_copy_does_not_grant_cli_record_ownership(self):
        canonical = self.personal / "skills/review-code"
        shutil.copytree(self.source, canonical)
        native = self.home / ".agents/skills/review-code"
        shutil.copytree(self.source, native)
        (native / "SKILL.md").write_text("Different installation")
        self.lockfile.write_text(json.dumps({"version": 3, "skills": {"review-code": {"source": "other/repo"}}}))
        self.cli(code=1)
        self.assertNotIn("cli", self.manifest()["skills"]["review-code"])
        before = snapshot(self.base)
        self.cli("remove-skill", "review-code", "--yes", code=1)
        self.assertEqual(snapshot(self.base), before)

    def test_missing_legacy_runtime_and_shared_sources_are_not_recreated(self):
        self.setup(False)
        manifest = self.manifest()
        for field in ("skills", "removed_skills", "lifecycle_version", "shared_files", "wrapper_digest"):
            manifest.pop(field, None)
        (self.personal / ".agent-sync.json").write_text(json.dumps(manifest))
        shutil.rmtree(self.personal / "skills/agent-sync-config")
        shutil.rmtree(self.personal / "skills/review-code")
        before = snapshot(self.base)
        report = self.cli("check", code=1)
        self.assertEqual(set(report["pending_removals"]), {"agent-sync-config", "review-code"})
        self.assertEqual(snapshot(self.base), before)
        self.cli(code=1)
        self.assertFalse((self.personal / "skills/agent-sync-config").exists())
        self.cli("remove-skill", "review-code", "--yes")
        self.assertIn("review-code", self.manifest()["removed_skills"])

    def test_arguments_cancel_and_empty_installation(self):
        before = snapshot(self.base)
        self.cli("uninstall", "--yes")
        self.assertEqual(snapshot(self.base), before)
        for args in (("remove-skill", "../escape", "--yes"), ("remove-skill", "agent-sync-config", "--yes"),
                     ("uninstall", "--project", str(self.project), "--yes"),
                     ("remove-skill", "review-code", "--import-skill", str(self.source), "--yes"),
                     ("--purge-shared-sources",)):
            self.cli(*args, code=2)
            self.assertEqual(snapshot(self.base), before)
        self.setup()
        before = snapshot(self.base)
        code, output = self.interactive(["remove-skill", "review-code"], ["n"])
        self.assertEqual(code, 0, output)
        self.assertEqual(snapshot(self.base), before)


if __name__ == "__main__":
    unittest.main()
