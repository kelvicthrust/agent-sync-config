"""Measure the complete warm hook subprocess, including Python startup."""
import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time

SCRIPT = Path(__file__).resolve().parents[1] / "skills/agent-sync-config/scripts/agent_sync_config.py"


def main():
    with tempfile.TemporaryDirectory() as temporary:
        base = Path(temporary)
        home, repo = base / "home", base / "repo"
        home.mkdir(); repo.mkdir()
        for index in range(30):
            folder = repo / ".agents/skills" / f"sample-{index}"
            folder.mkdir(parents=True)
            (folder / "SKILL.md").write_text(f"---\nname: sample-{index}\ndescription: A fixture skill.\n---\nFixture.\n")
        subprocess.run([sys.executable, str(SCRIPT), "--home", str(home), "--project", str(repo)],
                       check=True, stdout=subprocess.DEVNULL)
        command = [sys.executable, str(SCRIPT), "hook", "--home", str(home), "--provider", "codex"]
        payload = json.dumps({"cwd": str(repo), "session_id": "benchmark", "permission_mode": "default",
                              "hook_event_name": "UserPromptSubmit"})
        subprocess.run(command, input=payload, text=True, capture_output=True, check=True)
        timings = []
        for _ in range(20):
            start = time.perf_counter()
            result = subprocess.run(command, input=payload, text=True, capture_output=True, check=True)
            timings.append((time.perf_counter() - start) * 1000)
            if result.stdout:
                raise AssertionError("Healthy warm hook should be silent")
        print(json.dumps({"skills": 30, "samples": len(timings), "median_ms": round(statistics.median(timings), 2),
                          "p95_ms": round(sorted(timings)[18], 2), "target_ms": 100}, indent=2))
        # Keep measurements portable: report the target, do not fail shared CI on host scheduling.


if __name__ == "__main__":
    main()
