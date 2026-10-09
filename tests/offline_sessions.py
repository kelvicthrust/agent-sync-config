"""Exercise native loaders/hooks with a localhost API stub, never a real model.

This script needs installed provider binaries and localhost socket access. It
creates all config in temporary homes. Its Codex hook-trust bypass applies only
to the two fixture hooks authored/generated here; production setup never uses it.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "skills/agent-sync-config/scripts/agent_sync_config.py"


class MockAPI(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"data":[]}')

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        self.requests.append((self.path, body))
        if "count_tokens" in self.path:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"input_tokens":100}')
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        if "messages" in self.path:
            self.anthropic(body)
        else:
            self.openai_stream(body)

    def event(self, name, data):
        self.wfile.write(("event: " + name + "\ndata: " + json.dumps(data) + "\n\n").encode())
        self.wfile.flush()

    def anthropic(self, body):
        message = {"id": "msg_fixture", "type": "message", "role": "assistant", "content": [],
                   "model": body.get("model", "fixture"), "stop_reason": None, "stop_sequence": None,
                   "usage": {"input_tokens": 100, "output_tokens": 0}}
        self.event("message_start", {"type": "message_start", "message": message})
        self.event("content_block_start", {"type": "content_block_start", "index": 0,
                                            "content_block": {"type": "text", "text": ""}})
        self.event("content_block_delta", {"type": "content_block_delta", "index": 0,
                                            "delta": {"type": "text_delta", "text": "fixture-success"}})
        self.event("content_block_stop", {"type": "content_block_stop", "index": 0})
        self.event("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                                      "usage": {"output_tokens": 2}})
        self.event("message_stop", {"type": "message_stop"})

    def openai_stream(self, body):
        response = {"id": "resp_fixture", "object": "response", "created_at": int(time.time()),
                    "model": body.get("model", "fixture"), "status": "in_progress", "output": [], "usage": None}
        item = {"id": "msg_fixture", "type": "message", "role": "assistant", "status": "in_progress", "content": []}
        part = {"type": "output_text", "text": "fixture-success", "annotations": []}
        fields = {"item_id": item["id"], "output_index": 0, "content_index": 0}
        self.event("response.created", {"type": "response.created", "response": response})
        self.event("response.output_item.added", {"type": "response.output_item.added", "output_index": 0, "item": item})
        self.event("response.content_part.added", {"type": "response.content_part.added", **fields, "part": {**part, "text": ""}})
        self.event("response.output_text.delta", {"type": "response.output_text.delta", **fields, "delta": "fixture-success"})
        self.event("response.output_text.done", {"type": "response.output_text.done", **fields, "text": "fixture-success"})
        self.event("response.content_part.done", {"type": "response.content_part.done", **fields, "part": part})
        item = {**item, "status": "completed", "content": [part]}
        self.event("response.output_item.done", {"type": "response.output_item.done", "output_index": 0, "item": item})
        response = {**response, "status": "completed", "output": [item],
                    "usage": {"input_tokens": 100, "output_tokens": 2, "total_tokens": 102}}
        self.event("response.completed", {"type": "response.completed", "response": response})


def session(command, env, repo):
    start = len(MockAPI.requests)
    result = subprocess.run(command, env=env, cwd=repo, capture_output=True, text=True, timeout=30)
    if result.returncode or "fixture-success" not in result.stdout:
        raise AssertionError(f"Native session failed: {result.stdout[-2000:]} {result.stderr[-2000:]}")
    sent = MockAPI.requests[start:]
    assert sent, "Native session did not use the local mock API"
    serialized = json.dumps(sent)
    assert "ad hoc copying" in serialized, "The invoked setup skill body was not loaded"
    return sent, result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", default=shutil.which("codex"))
    parser.add_argument("--claude", default=shutil.which("claude"))
    args = parser.parse_args()
    if not args.codex and not args.claude:
        parser.error("Install at least one provider binary")
    server = ThreadingHTTPServer(("127.0.0.1", 0), MockAPI)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    endpoint = f"http://127.0.0.1:{server.server_address[1]}"
    report = {}
    try:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory).resolve()
            home, repo = base / "home", base / "repo"
            home.mkdir(); repo.mkdir()
            env = {**os.environ, "HOME": str(home), "CODEX_HOME": str(home / ".codex"),
                   "DO_NOT_TRACK": "1", "DISABLE_TELEMETRY": "1", "DISABLE_AUTOUPDATER": "1",
                   "ANTHROPIC_API_KEY": "fixture-not-a-secret", "ANTHROPIC_BASE_URL": endpoint,
                   "AGENT_SYNC_FIXTURE_KEY": "fixture-not-a-secret"}
            for key in ("ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "CLAUDE_CONFIG_DIR"):
                env.pop(key, None)
            subprocess.run(["git", "init", "-q", str(repo)], check=True)
            (repo / "AGENTS.md").write_text("PROJECT_INSTRUCTIONS_SENTINEL\n")
            (home / "agent-config").mkdir()
            (home / "agent-config/AGENTS.md").write_text("PERSONAL_INSTRUCTIONS_SENTINEL\n")
            skill = repo / ".agents/skills/review-code"; skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: review-code\ndescription: Review a fixture.\n---\nFixture.\n")
            (repo / ".agents/mcp.json").write_text(json.dumps({"schema": 1, "servers": {
                "local-probe": {"transport": "stdio", "command": sys.executable,
                                "args": [str(ROOT / "tests/fixtures/mcp_server.py")]}}}))
            subprocess.run([sys.executable, str(SCRIPT), "--home", str(home), "--project", str(repo)],
                           env=env, check=True, stdout=subprocess.DEVNULL)
            config = home / ".codex/config.toml"
            config.write_text(f'model = "fixture"\nmodel_provider = "fixture"\n'
                              f'[model_providers.fixture]\nname="Fixture"\nbase_url="{endpoint}/v1"\n'
                              'wire_api="responses"\nenv_key="AGENT_SYNC_FIXTURE_KEY"\n'
                              'requires_openai_auth=false\nsupports_websockets=false\n'
                              f'[projects.{json.dumps(str(repo))}]\ntrust_level="trusted"\n')
            (repo / ".claude/settings.local.json").write_text(json.dumps({"enabledMcpjsonServers": ["local-probe"]}))
            link = repo / ".claude/skills/review-code"
            cache_dir = home / ".local/state/agent-sync-config/cache"
            if args.codex:
                link.unlink()
                command = [args.codex, "exec", "--dangerously-bypass-hook-trust", "--sandbox", "read-only", "--json"]
                sent, _ = session([*command, "$agent-sync-config check"], env, repo)
                serialized = json.dumps(sent)
                assert all(token in serialized for token in ("PROJECT_INSTRUCTIONS_SENTINEL", "PERSONAL_INSTRUCTIONS_SENTINEL"))
                assert "fixture_echo" in serialized, "Codex did not connect to the local MCP fixture"
                assert not link.exists(), "A Codex read-only session repaired managed resources"
                assert any(json.loads(path.read_text()).get("sessions") for path in cache_dir.glob("*.json")), "Native hooks did not cache session metadata"
                with (repo / "AGENTS.md").open("a") as stream:
                    stream.write("\nUPDATED_INSTRUCTIONS_SENTINEL\n")
                resumed, _ = session([*command, "resume", "--last", "$agent-sync-config check"], env, repo)
                assert "Read AGENTS.md" in json.dumps(resumed), "Resumed session did not receive the instruction refresh cue"
                assert not link.exists()
                report["codex"] = "instructions, skill invocation, native hooks, MCP connection, read-only behavior, and resume refresh passed"
            if args.claude:
                if link.is_symlink():
                    link.unlink()
                command = [args.claude, "--print", "--output-format", "stream-json", "--verbose"]
                sent, output = session([*command, "--permission-mode", "plan", "/agent-sync-config check"], env, repo)
                serialized = json.dumps(sent)
                assert all(token in serialized for token in ("PROJECT_INSTRUCTIONS_SENTINEL", "PERSONAL_INSTRUCTIONS_SENTINEL"))
                assert "fixture_echo" in serialized, "Claude did not connect to the local MCP fixture"
                assert not link.exists(), "A Claude planning session repaired managed resources"
                result = next(json.loads(line) for line in output.splitlines() if json.loads(line).get("type") == "result")
                with (repo / "AGENTS.md").open("a") as stream:
                    stream.write("\nCLAUDE_UPDATED_INSTRUCTIONS_SENTINEL\n")
                resumed, _ = session([*command, "--resume", result["session_id"], "--permission-mode", "plan",
                                      "/agent-sync-config check"], env, repo)
                assert "Read AGENTS.md" in json.dumps(resumed)
                assert not link.exists()
                session([*command, "--permission-mode", "default", "/agent-sync-config check"], env, repo)
                assert link.is_symlink(), "A writable Claude prompt did not repair the missing link"
                report["claude"] = "instructions, skill invocation, native hooks, MCP connection, planning behavior, resume refresh, and safe repair passed"
    finally:
        server.shutdown(); server.server_close()
    report["inference"] = "local protocol stub; no real model or credentials used"
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
