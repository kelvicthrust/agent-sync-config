import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/agent-sync-config/scripts/agent_sync_config.py"
spec = importlib.util.spec_from_file_location("agent_sync", SCRIPT)
sync = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync)


def snapshot(root):
    result = {}
    if not root.exists():
        return result
    for path in sorted(root.rglob("*")):
        if "__pycache__" in path.parts:
            continue
        key = str(path.relative_to(root))
        result[key] = (os.readlink(path) if path.is_symlink() else
                       path.read_bytes() if path.is_file() else "directory", sync.stamp(path))
    return result


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.home = self.base / "home with spaces"
        self.repo = self.base / "repo with spaces"
        self.home.mkdir()
        self.repo.mkdir()

    def write(self, relative, text, home=False):
        path = (self.home if home else self.repo) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def skill(self, relative, home=False, text=None):
        return self.write(relative + "/SKILL.md", text or "---\nname: review-code\ndescription: Review code.\n---\nReview changes.\n", home).parent

    def run_tool(self, *args, expected=0, project=None):
        command = [sys.executable, str(SCRIPT), *args, "--home", str(self.home),
                   "--project", str(project or self.repo), "--json"]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def hook(self, mode="default", provider="codex", event="UserPromptSubmit", session="test", extra=None):
        payload = {"cwd": str(self.repo), "session_id": session, "permission_mode": mode, "hook_event_name": event}
        payload.update(extra or {})
        result = subprocess.run([sys.executable, str(SCRIPT), "hook", "--home", str(self.home),
                                 "--provider", provider], input=json.dumps(payload), capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if result.stdout else {}

    def mcp(self, servers):
        return self.write(".agents/mcp.json", json.dumps({"schema": 1, "servers": servers}))

    def test_fresh_setup_repeat_and_terminal_wrapper(self):
        self.write("README.md", "existing")
        report = self.run_tool()
        self.assertTrue(report["changes"])
        self.assertEqual((self.repo / "README.md").read_text(), "existing")
        self.assertEqual((self.repo / "CLAUDE.md").read_text(), "@AGENTS.md\n")
        self.assertFalse((self.repo / ".codex").exists())
        self.assertFalse((self.repo / ".mcp.json").exists())
        for relative in (".agents/skills/agent-sync-config", ".claude/skills/agent-sync-config"):
            self.assertTrue((self.home / relative / "SKILL.md").is_file())
            self.assertTrue((self.home / relative).is_symlink())
            self.assertEqual((self.home / relative / "LICENSE").read_bytes(), (ROOT / "LICENSE").read_bytes())
            self.assertTrue((self.home / relative / "scripts/vendor/TOMLKIT-LICENSE").is_file())
            self.assertTrue((self.home / relative / "scripts/vendor/NOTICE").is_file())
        before = snapshot(self.base)
        self.assertEqual(self.run_tool()["changes"], [])
        self.assertEqual(snapshot(self.base), before)
        self.assertEqual(self.run_tool("check")["changes"], [])
        result = subprocess.run([str(self.home / ".local/bin/agent-sync-config"), "check", "--home", str(self.home),
                                 "--project", str(self.repo)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_adopt_claude_instructions_and_managed_section(self):
        original = "# Instructions\nUse the existing build command.\n"
        self.write("CLAUDE.md", original)
        self.run_tool()
        agents = self.repo / "AGENTS.md"
        self.assertIn(original.rstrip(), agents.read_text())
        self.assertEqual(agents.read_text().count(sync.BEGIN), 1)
        agents.write_text("Before\n" + agents.read_text() + "\nAfter\n")
        self.run_tool()
        self.assertTrue(agents.read_text().startswith("Before\n"))
        self.assertTrue(agents.read_text().endswith("\nAfter\n"))
        self.assertEqual(agents.read_text().count(sync.BEGIN), 1)

    def test_conflicting_project_instructions_preserved(self):
        self.write("AGENTS.md", "Codex instructions")
        other = self.write("CLAUDE.md", "Different Claude instructions")
        report = self.run_tool(expected=1)
        self.assertTrue(report["issues"])
        self.assertEqual(other.read_text(), "Different Claude instructions")

    def test_global_conflict_and_override_preserved(self):
        self.write(".codex/AGENTS.md", "Personal A", home=True)
        other = self.write(".claude/CLAUDE.md", "Personal B", home=True)
        override = self.write(".codex/AGENTS.override.md", "Override", home=True)
        self.run_tool(expected=1)
        self.assertEqual(other.read_text(), "Personal B")
        self.assertEqual(override.read_text(), "Override")
        self.assertTrue((self.home / ".codex/AGENTS.md").is_symlink())

    def test_matching_global_instructions_link_to_one_source(self):
        for relative in (".codex/AGENTS.md", ".claude/CLAUDE.md"):
            self.write(relative, "same", home=True)
        self.run_tool()
        self.assertEqual((self.home / ".codex/AGENTS.md").resolve(), (self.home / ".claude/CLAUDE.md").resolve())

    def test_project_skills_adoption_edit_and_removal(self):
        original = self.skill(".claude/skills/review-code")
        self.run_tool()
        canonical = self.repo / ".agents/skills/review-code"
        self.assertTrue(original.is_symlink())
        (original / "SKILL.md").write_text("updated shared skill")
        self.assertEqual((canonical / "SKILL.md").read_text(), "updated shared skill")
        self.run_tool()
        shutil.rmtree(canonical)
        self.run_tool()
        self.assertFalse(os.path.lexists(original))

    def test_legacy_global_skills_adopted_in_one_run(self):
        self.skill(".codex/skills/review-code", home=True)
        system = self.write(".codex/skills/.system/keep.txt", "system", home=True)
        self.run_tool()
        self.assertTrue((self.home / ".claude/skills/review-code").is_symlink())
        self.assertTrue((self.home / ".agents/skills/review-code").is_symlink())
        self.assertEqual(system.read_text(), "system")
        self.assertFalse(system.parent.is_symlink())

    def test_conflicting_skill_and_external_link_preserved(self):
        self.skill(".agents/skills/review-code")
        conflict = self.skill(".claude/skills/review-code", text="Different")
        external = self.base / "external/other-skill"
        external.mkdir(parents=True)
        (external / "SKILL.md").write_text("external")
        (conflict.parent / "other-skill").symlink_to(external)
        self.run_tool(expected=1)
        self.assertFalse(conflict.is_symlink())
        self.assertEqual((conflict / "SKILL.md").read_text(), "Different")
        self.assertTrue((conflict.parent / "other-skill").is_symlink())

    def test_curated_context_adoption_and_conflict(self):
        self.write(".claude/context/a.md", "A")
        self.write(".codex/context/b.md", "B")
        self.run_tool()
        self.assertTrue((self.repo / ".claude/context").is_symlink())
        self.assertTrue((self.repo / ".codex/context").is_symlink())
        self.assertEqual((self.repo / ".agents/context/a.md").read_text(), "A")
        self.assertEqual((self.repo / ".agents/context/b.md").read_text(), "B")
        (self.repo / ".claude/context").unlink()
        self.write(".claude/context/a.md", "Conflict")
        self.run_tool(expected=1)
        self.assertEqual((self.repo / ".claude/context/a.md").read_text(), "Conflict")

    def test_read_only_drift_never_changes_files(self):
        self.skill(".agents/skills/review-code")
        self.run_tool()
        (self.repo / ".claude/skills/review-code").unlink()
        before = snapshot(self.base)
        report = self.run_tool("check", expected=1)
        self.assertTrue(report["changes"])
        self.assertEqual(before, snapshot(self.base))

    def test_uninitialized_read_only_check(self):
        before = snapshot(self.base)
        self.run_tool("check", expected=1)
        self.assertEqual(before, snapshot(self.base))

    def test_mcp_roundtrip_environment_references_and_comments(self):
        self.write(".codex/config.toml", '# Keep this comment\nmodel = "existing"\n\n[other]\nvalue = 3 # inline\n')
        self.mcp({"local": {"transport": "stdio", "command": "python3", "args": ["server.py"],
                            "env": {"DEBUG": "1"}, "env_vars": ["SERVICE_TOKEN"]},
                  "remote": {"transport": "http", "url": "https://example.com/mcp",
                             "bearer_token_env_var": "SERVICE_TOKEN", "env_headers": {"X-User": "SERVICE_USER"}}})
        self.run_tool()
        claude = json.loads((self.repo / ".mcp.json").read_text())["mcpServers"]
        self.assertEqual(claude["local"]["env"]["SERVICE_TOKEN"], "${SERVICE_TOKEN}")
        self.assertEqual(claude["remote"]["headers"]["Authorization"], "Bearer ${SERVICE_TOKEN}")
        codex = (self.repo / ".codex/config.toml").read_text()
        self.assertIn('# Keep this comment\nmodel = "existing"', codex)
        self.assertIn('value = 3 # inline', codex)
        doc = sync.read_toml(self.repo / ".codex/config.toml")
        self.assertEqual(sync.import_server(doc["mcp_servers"]["remote"], "codex")["bearer_token_env_var"], "SERVICE_TOKEN")
        self.assertEqual(self.run_tool()["changes"], [])

    def test_mcp_adoption_omitted_stdio_type(self):
        self.write(".mcp.json", json.dumps({"mcpServers": {"local": {"command": "python3", "args": ["server.py"]}}}))
        self.run_tool()
        neutral = json.loads((self.repo / ".agents/mcp.json").read_text())
        self.assertEqual(neutral["servers"]["local"]["transport"], "stdio")
        self.assertEqual(self.run_tool()["changes"], [])

    def test_mcp_canonical_update_and_manual_conflict(self):
        self.mcp({"remote": {"transport": "http", "url": "https://one.example/mcp"}})
        self.run_tool()
        self.mcp({"remote": {"transport": "http", "url": "https://two.example/mcp"}})
        self.run_tool()
        self.assertEqual(json.loads((self.repo / ".mcp.json").read_text())["mcpServers"]["remote"]["url"], "https://two.example/mcp")
        path = self.repo / ".mcp.json"
        doc = json.loads(path.read_text()); doc["mcpServers"]["remote"]["url"] = "https://manual.example/mcp"
        path.write_text(json.dumps(doc))
        self.mcp({"remote": {"transport": "http", "url": "https://three.example/mcp"}})
        self.run_tool(expected=1)
        self.assertEqual(json.loads(path.read_text())["mcpServers"]["remote"]["url"], "https://manual.example/mcp")

    def test_managed_toml_comments_survive_canonical_update(self):
        self.write(".codex/config.toml", '[mcp_servers.local]\n# Preserve managed comments\ncommand = "python3" # interpreter\n')
        self.run_tool()
        self.mcp({"local": {"transport": "stdio", "command": "node"}})
        self.run_tool()
        text = (self.repo / ".codex/config.toml").read_text()
        self.assertIn("# Preserve managed comments", text)
        self.assertIn('command = "node" # interpreter', text)

    def test_disabled_hooks_are_reported_without_enabling_them(self):
        path = self.write(".codex/config.toml", "[features]\nhooks = false\n", home=True)
        settings = self.write(".claude/settings.local.json", '{"disableAllHooks": true}')
        self.run_tool(expected=1)
        self.assertIn("hooks = false", path.read_text())
        self.assertTrue(json.loads(settings.read_text())["disableAllHooks"])

    def test_global_skill_addition_and_removal_via_claude_hook(self):
        self.run_tool()
        skill = self.skill("agent-config/skills/review-code", home=True)
        self.hook(provider="claude")
        self.assertTrue((self.home / ".agents/skills/review-code").is_symlink())
        shutil.rmtree(skill)
        self.hook(provider="claude")
        self.assertFalse(os.path.lexists(self.home / ".agents/skills/review-code"))

    def test_mcp_removal_preserves_modified_and_unmanaged_servers(self):
        self.mcp({"one": {"transport": "stdio", "command": "python3"}, "two": {"transport": "stdio", "command": "python3"}})
        self.run_tool()
        path = self.repo / ".mcp.json"; doc = json.loads(path.read_text())
        doc["mcpServers"]["two"]["args"] = ["manual"]
        doc["mcpServers"]["unmanaged"] = {"command": "node"}
        path.write_text(json.dumps(doc)); self.mcp({})
        self.run_tool(expected=1)
        servers = json.loads(path.read_text())["mcpServers"]
        self.assertNotIn("one", servers)
        self.assertIn("two", servers)
        self.assertIn("unmanaged", servers)

    def test_global_mcp_preserves_private_project_and_other_settings(self):
        self.write(".claude.json", json.dumps({"theme": "dark", "projects": {"/other": {"private": True}},
                   "mcpServers": {"remote": {"type": "http", "url": "https://example.com/mcp"}}}), home=True)
        self.run_tool()
        doc = json.loads((self.home / ".claude.json").read_text())
        self.assertEqual(doc["theme"], "dark")
        self.assertEqual(doc["projects"], {"/other": {"private": True}})
        self.assertTrue((self.home / ".codex/config.toml").exists())
        self.assertFalse((self.repo / ".mcp.json").exists())

    def test_unsupported_and_literal_credentials_are_not_imported(self):
        path = self.write(".mcp.json", json.dumps({"mcpServers": {
            "unsupported": {"command": "node", "unknown": "preserve"},
            "secret": {"command": "node", "env": {"API_KEY": "do-not-copy-this"}}}}))
        before = path.read_bytes()
        report = self.run_tool(expected=1)
        self.assertEqual(path.read_bytes(), before)
        self.assertNotIn("do-not-copy-this", json.dumps(report))
        self.assertFalse((self.repo / ".agents/mcp.json").exists())

    def test_invalid_manifest_and_link_traversal_rejected(self):
        self.write(".agents/agent-sync.json", json.dumps({"schema": 1, "links": {".claude/skills/../../../outside": "anything"}, "mcp": {}}))
        before = snapshot(self.repo)
        self.run_tool(expected=2)
        # Only the external lock file can be initialized by a failed explicit sync.
        self.assertEqual(snapshot(self.repo), before)
        self.assertFalse((self.repo / "AGENTS.md").exists())

    def test_linked_configuration_directory_not_written_through(self):
        external = self.base / "external"; external.mkdir()
        (self.repo / ".agents").symlink_to(external)
        self.run_tool("--project-only", expected=2)
        self.assertEqual(list(external.iterdir()), [])

    def test_back_reference_cannot_turn_skill_into_symlink_cycle(self):
        provider = self.skill(".claude/skills/review-code")
        canonical = self.repo / ".agents/skills/review-code"; canonical.parent.mkdir(parents=True)
        canonical.symlink_to(provider)
        self.run_tool(expected=1)
        self.assertFalse(provider.is_symlink())
        self.assertTrue((provider / "SKILL.md").is_file())

    def test_personal_root_cannot_be_inside_project(self):
        self.run_tool("--personal-root", str(self.repo / "personal-defaults"), expected=2)
        self.assertFalse((self.repo / "personal-defaults/AGENTS.md").exists())

    def test_explicit_plugin_import_and_dependency_rejection(self):
        portable = self.base / "review-code"; portable.mkdir()
        (portable / "SKILL.md").write_text("Portable instructions")
        self.run_tool("--import-skill", str(portable))
        self.assertTrue((self.repo / ".agents/skills/review-code/SKILL.md").is_file())
        plugin = self.base / "plugin-only"; plugin.mkdir()
        (plugin / "SKILL.md").write_text("Run ${CLAUDE_PLUGIN_ROOT}/scripts/run.sh")
        self.run_tool("--import-skill", str(plugin), expected=2)
        self.assertFalse((self.repo / ".agents/skills/plugin-only").exists())

    def test_plugin_and_existing_hook_configuration_preserved(self):
        original = {"enabledPlugins": {"example@marketplace": True}, "hooks": {"SessionStart": [
            {"hooks": [{"type": "command", "command": "existing-hook"}]}]}}
        self.write(".claude/settings.json", json.dumps(original), home=True)
        project_plugin = self.write(".claude/settings.json", json.dumps({"enabledPlugins": {"project@example": True}}))
        self.run_tool()
        doc = json.loads((self.home / ".claude/settings.json").read_text())
        self.assertEqual(doc["enabledPlugins"], original["enabledPlugins"])
        self.assertEqual(doc["hooks"]["SessionStart"][0]["hooks"][0]["command"], "existing-hook")
        self.assertEqual(json.loads(project_plugin.read_text())["enabledPlugins"], {"project@example": True})
        self.assertEqual(self.run_tool()["changes"], [])

    def test_missing_skill_detected_and_hook_repairs_global_link(self):
        self.run_tool()
        (self.home / ".claude/skills/agent-sync-config").unlink()
        self.run_tool("check", expected=1)
        self.hook(provider="claude")
        self.assertTrue((self.home / ".claude/skills/agent-sync-config/SKILL.md").is_file())
        self.run_tool("check")

    def test_hooks_normal_plan_unknown_mode_and_read_only_sandbox(self):
        self.skill(".agents/skills/review-code")
        self.run_tool()
        link = self.repo / ".claude/skills/review-code"
        for mode, extra in (("plan", None), (None, None), ("default", {"sandbox_mode": "read-only"})):
            link.unlink(missing_ok=True)
            before = snapshot(self.repo)
            output = self.hook(mode=mode, extra=extra)
            self.assertTrue(output)
            self.assertFalse(link.exists())
            self.assertEqual(snapshot(self.repo), before)
        self.hook(provider="claude")
        self.assertTrue(link.is_symlink())
        self.assertEqual(self.hook(provider="claude"), {})
        self.assertTrue(self.hook(event="SessionStart", session="resumed"))
        self.assertTrue(self.hook(provider="claude", session="switched-client"))

    def test_codex_unknown_sandbox_is_audit_only_even_with_bypass_permissions(self):
        self.skill(".agents/skills/review-code"); self.run_tool()
        link = self.repo / ".claude/skills/review-code"; link.unlink()
        before = snapshot(self.repo)
        self.assertTrue(self.hook(mode="bypassPermissions"))
        self.assertEqual(snapshot(self.repo), before)
        self.assertFalse(link.exists())
        self.hook(mode="default", extra={"sandbox_mode": "workspace-write"})
        self.assertTrue(link.is_symlink())

    def test_hook_does_not_recreate_missing_instructions(self):
        self.run_tool(); (self.repo / "AGENTS.md").unlink()
        output = self.hook()
        self.assertIn("missing", json.dumps(output))
        self.assertFalse((self.repo / "AGENTS.md").exists())

    def test_instruction_refresh_and_file_replacement_cache_invalidation(self):
        self.run_tool(); self.hook(); self.assertEqual(self.hook(), {})
        path = self.repo / "AGENTS.md"
        content = path.read_text(); original_stat = path.stat()
        path.write_text(content + "\nNew instructions\n")
        self.assertIn("Read AGENTS.md", json.dumps(self.hook()))
        replacement = path.with_suffix(".tmp"); replacement.write_text(content)
        os.utime(replacement, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns)); replacement.replace(path)
        self.assertIn("Read AGENTS.md", json.dumps(self.hook()))

    def test_hook_noop_for_unregistered_project(self):
        before = snapshot(self.base)
        self.assertEqual(self.hook(), {})
        self.assertEqual(snapshot(self.base), before)

    def test_nested_directory_worktree_and_project_only(self):
        self.write(".git", "gitdir: /elsewhere/.git/worktrees/example\n")
        nested = self.repo / "src/nested"; nested.mkdir(parents=True)
        report = self.run_tool("--project-only", project=nested)
        self.assertEqual(report["project"], str(self.repo))
        self.assertFalse((nested / "AGENTS.md").exists())
        self.assertFalse((self.home / ".codex").exists())
        self.assertEqual(self.run_tool("--project-only")["changes"], [])

    def test_explicit_personal_root_is_reused_and_second_root_rejected(self):
        custom = self.home / "custom-personal"
        self.run_tool("--personal-root", str(custom))
        self.assertTrue((custom / "AGENTS.md").is_file())
        self.assertEqual(self.run_tool()["changes"], [])
        self.run_tool("--personal-root", str(self.home / "different"), expected=2)

    def test_invalid_mcp_manifest_error_has_no_secret_contents(self):
        path = self.write(".agents/mcp.json", '{"invalid": "do-not-log"}')
        result = self.run_tool(expected=2)
        self.assertNotIn("do-not-log", json.dumps(result))
        self.assertEqual(path.read_text(), '{"invalid": "do-not-log"}')

    def test_missing_or_invalid_import_does_not_create_shared_mcp(self):
        self.run_tool()
        imported = self.base / "plugin-mcp.json"
        before = snapshot(self.repo)
        self.run_tool("--import-mcp", str(imported), expected=2)
        self.assertEqual(snapshot(self.repo), before)
        imported.write_text('{"description": "not an MCP configuration"}')
        self.run_tool("--import-mcp", str(imported), expected=2)
        self.assertEqual(snapshot(self.repo), before)

    def test_strict_read_only_hook_does_not_cache_or_repair(self):
        self.skill(".agents/skills/review-code"); self.run_tool()
        (self.repo / ".claude/skills/review-code").unlink()
        before = snapshot(self.base)
        payload = {"cwd": str(self.repo), "permission_mode": "default", "session_id": "strict-read-only"}
        result = subprocess.run([sys.executable, str(SCRIPT), "hook", "--provider", "claude", "--home", str(self.home)],
                                input=json.dumps(payload), capture_output=True, text=True,
                                env={**os.environ, "AGENT_SYNC_READ_ONLY": "1"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Synchronization required", result.stdout)
        self.assertEqual(snapshot(self.base), before)


if __name__ == "__main__":
    unittest.main()
