"""Optional offline smoke tests against installed provider binaries and skills CLI.

All configuration lives in a temporary HOME. No model turn is requested and no
credentials are copied. This verifies discovery/parsing, not model compliance.
"""
import argparse
import json
import os
from pathlib import Path
from test_sync import snapshot
import selectors
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/agent-sync-config/scripts/agent_sync_config.py"


def run(command, env, cwd, timeout=20):
    result = subprocess.run(command, env=env, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise AssertionError(f"{Path(command[0]).name} failed: {result.stdout[:1000]} {result.stderr[:1000]}")
    return result.stdout


def codex_discovery(binary, env, repo, global_installed=True):
    # Unbuffered binary stdout avoids TextIOWrapper read-ahead hiding RPC lines.
    process = subprocess.Popen([binary, "app-server", "--stdio"], env=env, cwd=repo,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               bufsize=0)
    selector = selectors.DefaultSelector()
    selector.register(process.stdout, selectors.EVENT_READ)
    pending = bytearray()

    def send(value):
        process.stdin.write((json.dumps(value) + "\n").encode())
        process.stdin.flush()

    def request(identifier, method, params):
        send({"id": identifier, "method": method, "params": params})
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            while b"\n" in pending:
                line, _, rest = pending.partition(b"\n")
                pending[:] = rest
                value = json.loads(line)
                if value.get("id") == identifier:
                    if "error" in value:
                        raise AssertionError(value["error"])
                    return value["result"]
            if not selector.select(max(0, deadline - time.monotonic())):
                break
            data = os.read(process.stdout.fileno(), 65536)
            if not data:
                break
            pending.extend(data)
        raise AssertionError(f"Codex did not respond to {method}")

    try:
        request(1, "initialize", {"clientInfo": {"name": "agent-sync-smoke", "version": "fixture"},
                                  "capabilities": {"experimentalApi": True}})
        send({"method": "initialized", "params": {}})
        skills = request(2, "skills/list", {"cwds": [str(repo)], "forceReload": True})
        entries = [skill for entry in skills["data"] for skill in entry["skills"]]
        assert sum(skill["name"] == "agent-sync-config" and skill["enabled"] for skill in entries) == int(global_installed), skills
        assert sum(skill["name"] == "review-code" and skill["enabled"] for skill in entries) == 1, skills
        assert not any(entry["errors"] for entry in skills["data"]), skills
        assert sum(skill["name"] == "command-review" and skill["enabled"] for skill in entries) == 1, skills
        assert sum(skill["name"] == "global-review" and skill["enabled"] for skill in entries) == 1, skills
        if not global_installed:
            assert not any(skill["name"] == "agent-sync-config" and str(skill.get("path", "")).startswith(env["HOME"]) for skill in entries), skills
        hooks = request(3, "hooks/list", {"cwds": [str(repo)]})
        assert not any(entry["errors"] for entry in hooks["data"]), hooks
        handlers = [hook for entry in hooks["data"] for hook in entry["hooks"]]
        assert handlers == [], hooks
        config = request(4, "config/read", {"cwd": str(repo), "includeLayers": True})
        assert "local-probe" in config["config"].get("mcp_servers", {}), config
        return {"skill_discovery": "passed", "synchronizer_hooks": "absent", "mcp_config_loading": "passed",
                "duplicate_managed_skills": "none",
                "model_turn": "not requested"}
    finally:
        selector.close()
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", default=shutil.which("codex"))
    parser.add_argument("--claude", default=shutil.which("claude"))
    parser.add_argument("--skills-cli", type=Path, help="Optional downloaded skills bin/cli.mjs")
    parser.add_argument("--node", default=shutil.which("node"))
    args = parser.parse_args()
    report = {}
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary).resolve()
        home, repo = base / "home", base / "repo"
        home.mkdir(); repo.mkdir()
        env = {**os.environ, "HOME": str(home), "CODEX_HOME": str(home / ".codex"), "DISABLE_TELEMETRY": "1",
               "DO_NOT_TRACK": "1", "DISABLE_AUTOUPDATER": "1"}
        for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "GITHUB_TOKEN", "GH_TOKEN", "CLAUDE_CONFIG_DIR", "XDG_STATE_HOME"):
            env.pop(key, None)
        run(["git", "init", "-q", str(repo)], env, repo)
        commands = repo / ".claude/commands"; commands.mkdir(parents=True)
        (commands / "command-review.md").write_text("Review a fixture command.\n")
        folder = repo / ".agents/skills/review-code"; folder.mkdir(parents=True)
        (folder / "SKILL.md").write_text("---\nname: review-code\ndescription: Review a fixture change.\n---\nReview the code.\n")
        (repo / ".mcp.json").write_text(json.dumps({"mcpServers": {
            "local-probe": {"type": "stdio", "command": sys.executable, "args": ["-V"]}}}))
        (home / ".claude.json").write_text(json.dumps({"mcpServers": {
            "global-probe": {"type": "stdio", "command": sys.executable, "args": ["-V"]}}}))
        if args.skills_cli:
            assert args.node, "--node is required for the skills CLI smoke test"
            run([args.node, str(args.skills_cli.resolve()), "add", str(ROOT), "--global", "--agent", "codex", "claude-code",
                 "--skill", "agent-sync-config", "--yes"], env, repo)
            assert (home / ".agents/skills/agent-sync-config/SKILL.md").is_file()
            assert (home / ".claude/skills/agent-sync-config/SKILL.md").is_file()
            for relative in (".agents/skills/agent-sync-config", ".claude/skills/agent-sync-config"):
                installed = home / relative
                assert (installed / "LICENSE").read_bytes() == (ROOT / "LICENSE").read_bytes()
                assert (installed / "scripts/vendor/TOMLKIT-LICENSE").is_file()
                assert (installed / "scripts/vendor/NOTICE").is_file()
            report["skills_cli_installation"] = "passed"
        (home / ".codex/skills/.system").mkdir(parents=True)
        global_skill = home / ".agents/skills/global-review"
        global_skill.mkdir(parents=True, exist_ok=True)
        (global_skill / "SKILL.md").write_text("---\nname: global-review\ndescription: Review a global fixture.\n---\nReview changes.\n")
        installed_before = snapshot(home / ".agents/skills/agent-sync-config")
        run([sys.executable, str(SCRIPT), "--scope", "global", "--home", str(home)], env, repo)
        assert snapshot(home / ".agents/skills/agent-sync-config") == installed_before
        assert not (home / "agent-config").exists()
        assert not (home / ".local/state/agent-sync-config").exists()
        run([sys.executable, str(SCRIPT), "--scope", "project", "--home", str(home), "--project", str(repo)], env, repo)
        # Trust only this disposable test project's config layer for native MCP discovery.
        assert not (repo / ".agents/skills/agent-sync-config").exists()
        assert not (home / ".codex/skills/global-review").exists()
        assert (repo / ".claude/skills/review-code").resolve() == repo / ".agents/skills/review-code"
        config = home / ".codex/config.toml"
        config.write_text((config.read_text() if config.exists() else "") +
                          "\n[projects." + json.dumps(str(repo)) + ']\ntrust_level = "trusted"\n')
        if args.codex:
            report["codex_version"] = run([args.codex, "--version"], env, repo).strip()
            report["codex"] = codex_discovery(args.codex, env, repo, global_installed=bool(args.skills_cli))
        else:
            report["codex"] = "not installed"
        if args.claude:
            report["claude_version"] = run([args.claude, "--version"], env, repo).strip()
            native = run([args.claude, "mcp", "get", "local-probe"], env, repo)
            assert "local-probe" in native and sys.executable in native, native
            global_native = run([args.claude, "mcp", "get", "global-probe"], env, repo)
            assert "global-probe" in global_native and sys.executable in global_native, global_native
            report["claude"] = {"project_and_global_mcp_config_loading": "passed", "claude_skill_references": "verified on disk",
                                "model_turn": "not requested"}
        else:
            report["claude"] = "not installed"
        if args.skills_cli:
            run([args.node, str(args.skills_cli.resolve()), "remove", "agent-sync-config", "--global", "--agent", "codex", "claude-code", "--yes"], env, repo)
            assert not (home / ".agents/skills/agent-sync-config").exists()
        run([sys.executable, str(SCRIPT), "check", "--scope", "global", "--home", str(home)], env, repo)
        run([sys.executable, str(SCRIPT), "check", "--scope", "project", "--home", str(home), "--project", str(repo)], env, repo)
        if args.codex:
            report["codex_after_installer_removal"] = codex_discovery(args.codex, env, repo, global_installed=False)
        if args.claude:
            native = run([args.claude, "mcp", "get", "global-probe"], env, repo)
            assert "global-probe" in native and sys.executable in native, native
        report["native_configuration_usable_without_synchronizer"] = "passed"
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
