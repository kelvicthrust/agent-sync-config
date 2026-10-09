"""Exercise the official Skills CLI in disposable homes using local fixtures."""
import argparse
import json
import os
from pathlib import Path
from test_sync import snapshot
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/agent-sync-config/scripts/agent_sync_config.py"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skills-cli", required=True, type=Path)
    parser.add_argument("--node", required=True)
    args = parser.parse_args()
    cli = [args.node, str(args.skills_cli.resolve())]
    results = {}
    with tempfile.TemporaryDirectory(prefix="agent-sync-skills-") as temporary:
        base = Path(temporary).resolve()
        home, project, source = base / "home", base / "consumer", base / "review-code"
        for directory in (home, project, source):
            directory.mkdir()
        (source / "SKILL.md").write_text('---\nname: review-code\ndescription: Review a disposable fixture.\n---\nReview changes.\n')
        env = {**os.environ, "HOME": str(home), "CODEX_HOME": str(home / ".codex"),
               "DISABLE_TELEMETRY": "1", "DO_NOT_TRACK": "1", "DISABLE_AUTOUPDATER": "1"}
        for key in list(env):
            if any(word in key.upper() for word in ("TOKEN", "API_KEY", "SECRET")) or key in {"CLAUDE_CONFIG_DIR", "XDG_STATE_HOME"}:
                env.pop(key, None)

        def command(argv, expected=0):
            result = subprocess.run(argv, env=env, cwd=project, capture_output=True, text=True, timeout=45)
            assert result.returncode == expected, (argv[:3], result.stdout[-3000:], result.stderr[-1000:])
            return result.stdout

        def tool(*argv, expected=0, script=SCRIPT):
            return json.loads(command([sys.executable, str(script), *argv, "--scope", "global", "--home", str(home), "--json"], expected))

        results["skills_cli_version"] = command([*cli, "--version"]).strip()
        command([*cli, "add", str(source), "--global", "--agent", "codex", "claude-code", "--yes"])
        command([*cli, "add", str(ROOT), "--global", "--agent", "codex", "claude-code", "--skill", "agent-sync-config", "--yes"])
        tool()
        command([*cli, "remove", "nonexistent-fixture", "--global", "--yes"])
        assert not tool("check")["issues"]
        results["no_op_removal"] = "passed"

        installed = home / ".agents/skills/agent-sync-config/scripts/agent_sync_config.py"
        installed_before = snapshot(installed.parent.parent)
        project_before = snapshot(project)
        tool(script=installed)
        assert snapshot(installed.parent.parent) == installed_before
        assert snapshot(project) == project_before
        results["installed_runtime_preservation"] = "passed"

        command([*cli, "remove", "review-code", "--global", "--agent", "claude-code", "--yes"])
        before = snapshot(base)
        report = tool("check", expected=1, script=installed)
        assert report["changes"] and not report["issues"]
        assert snapshot(base) == before
        tool(script=installed)
        assert (home / ".claude/skills/review-code").is_symlink()
        results["partial_provider_removal_and_explicit_repair"] = "passed"

        command([*cli, "remove", "review-code", "--global", "--agent", "codex", "claude-code", "--yes"])
        tool(script=installed)
        assert not (home / ".agents/skills/review-code").exists()
        assert not (home / ".claude/skills/review-code").exists()
        results["complete_removal_no_restoration_source"] = "passed"

        command([*cli, "add", str(source), "--global", "--agent", "codex", "claude-code", "--yes"])
        tool(script=installed)
        tool("check", script=installed)
        results["explicit_reinstallation"] = "passed"

        command([*cli, "remove", "agent-sync-config", "--global", "--agent", "codex", "claude-code", "--yes"])
        report = tool()
        assert "pending_removals" not in report
        assert not installed.exists()
        assert not (home / "agent-config").exists()
        assert not (home / ".local/bin/agent-sync-config").exists()
        assert not (home / ".local/state/agent-sync-config").exists()
        assert (home / ".agents/skills/review-code/SKILL.md").is_file()
        assert (home / ".claude/skills/review-code/SKILL.md").is_file()
        results["synchronizer_removal_without_recreation"] = "passed"
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
