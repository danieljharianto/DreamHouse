#!/usr/bin/env python3
"""Development runner for the local DreamHouse sandbox.

`dreamhouse run` always spawns its own server with DREAMHOUSE_TASKS_PACK
force-set to the (missing, Drive-gated) official pack, so it can't see the
`houses/` dev task or the dev validator installed in this repo's
`server/_private/`. This script talks directly to an already-running local
server instead (see README "Running the server locally"), loads an agent
function dynamically, and runs the same fetch -> generate -> execute ->
export -> submit -> poll loop.

Usage:
  export BLENDER_PATH=/path/to/blender
  uvicorn server.app:app --host 127.0.0.1 --port 8000   # in another shell

  python scripts/dev_run.py --task DEV_01_0001 \\
      --agent examples.dev_agent:generate \\
      --output-dir ./runs/DEV_01_0001
"""

from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_agent(spec: str):
    module_name, func_name = spec.split(":", 1)
    module = importlib.import_module(module_name)
    return getattr(module, func_name)


def fetch_task(server: str, task_id: str) -> dict:
    r = requests.get(f"{server}/v1/tasks/{task_id}")
    r.raise_for_status()
    return r.json()


def download_images(server: str, task: dict, dest_dir: Path) -> list[str]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for url in task.get("reference_images", []):
        view = url.rsplit("/", 1)[-1]
        r = requests.get(f"{server}{url}")
        r.raise_for_status()
        p = dest_dir / f"{view}.png"
        p.write_bytes(r.content)
        paths.append(str(p))
    return paths


def run_blender(blender: str, code: str, blend_file: Path) -> dict:
    save_stub = (
        "\n\nimport bpy as _bpy\n"
        f'_bpy.ops.wm.save_as_mainfile(filepath=r"{blend_file}")\n'
    )
    script = tempfile.NamedTemporaryFile(suffix=".py", mode="w", delete=False)
    script.write(code + save_stub)
    script.close()

    cmd = [blender, "--background"]
    if blend_file.exists():
        cmd.append(str(blend_file))
    cmd += ["--python", script.name]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    os.unlink(script.name)
    if result.returncode != 0:
        return {"success": False, "error": result.stderr[-1500:]}
    if not blend_file.exists():
        return {"success": False, "error": f"Blender exited 0 but {blend_file} was not written"}
    return {"success": True}


def export_geometry(blender: str, blend_file: Path, collection_name: str) -> dict | None:
    output_path = blend_file.parent / "submission.json"
    export_script = REPO_ROOT / "helpers" / "blender_export.py"
    subprocess.run(
        [
            blender, "--background", str(blend_file),
            "--python", str(export_script),
            "--", str(output_path), collection_name,
        ],
        capture_output=True, text=True, timeout=60,
    )
    if output_path.exists():
        return json.loads(output_path.read_text())
    return None


def create_session(server: str, task_id: str, model_id: str) -> str:
    r = requests.post(f"{server}/v1/sessions", json={
        "task_id": task_id, "model_id": model_id, "protocol": "stepwise",
    })
    r.raise_for_status()
    return r.json()["session_id"]


def submit_and_poll(server: str, session_id: str, members: list[dict], timeout: int = 60) -> dict | None:
    r = requests.post(f"{server}/v1/sessions/{session_id}/submit", json={"members": members})
    r.raise_for_status()
    job_id = r.json()["job_id"]

    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(1)
        r = requests.get(f"{server}/v1/sessions/{session_id}/results/{job_id}")
        data = r.json()
        if data["status"] == "complete":
            return data["results"]
        if data["status"] == "failed":
            print(f"  Validation error: {data.get('error')}")
            return None
    print("  Timed out waiting for results")
    return None


def format_feedback(results: dict) -> str:
    tests = results["tests"]
    failures = [t for t, v in tests.items() if not v]
    if not failures:
        return "[SUCCESS] All 10 structural tests passed."
    lines = ["[VALIDATION FAILED]", f"  Passed: {sum(tests.values())}/10", "  Failed tests:"]
    lines += [f"    - {t}" for t in failures]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--server", default=os.environ.get("DREAMHOUSE_SERVER", "http://127.0.0.1:8000"))
    parser.add_argument("--task", required=True)
    parser.add_argument("--agent", required=True, help="module:function, e.g. examples.dev_agent:generate")
    parser.add_argument("--blender", default=os.environ.get("BLENDER_PATH"))
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--max-retries", type=int, default=3)
    args = parser.parse_args()

    if not args.blender:
        sys.exit("Blender path required: pass --blender or set BLENDER_PATH")

    sys.path.insert(0, str(REPO_ROOT))
    generate = load_agent(args.agent)

    work_dir = Path(args.output_dir or tempfile.mkdtemp(prefix="dreamhouse_"))
    work_dir.mkdir(parents=True, exist_ok=True)
    attempts_dir = work_dir / "attempts"
    attempts_dir.mkdir(exist_ok=True)
    print(f"Working directory: {work_dir}")

    print(f"\n[1] Fetching task {args.task}...")
    task = fetch_task(args.server, args.task)
    print(f"    Style: {task['style']}")
    print(f"    Description: {task['description']}")
    images = download_images(args.server, task, work_dir / "images")
    print(f"    Got {len(images)} images")
    (work_dir / "task.json").write_text(json.dumps(task, indent=2))

    print("\n[2] Creating eval session...")
    session_id = create_session(args.server, args.task, model_id="dev-agent")
    print(f"    Session: {session_id}")

    collection_name = args.task
    blend_file = work_dir / "structure.blend"
    feedback_history: list[dict] = []
    final_results: dict | None = None
    final_status = "no_submission"

    for attempt in range(1, args.max_retries + 1):
        attempt_dir = attempts_dir / f"attempt_{attempt}"
        attempt_dir.mkdir(exist_ok=True)

        print(f"\n[3] Generating code (attempt {attempt})...")
        prompt = f"Build a {task['description']}"
        code = generate(prompt, images, feedback_history)
        code = code.replace("COLLECTION_NAME", collection_name)
        (attempt_dir / "code.py").write_text(code)

        print("[4] Executing in Blender...")
        result = run_blender(args.blender, code, blend_file)
        if not result["success"]:
            print(f"    Blender error: {result.get('error', '')[:200]}")
            feedback_history.append({"attempt": attempt, "status": "blender_error", "error": result.get("error")})
            continue

        print("[5] Exporting geometry...")
        submission = export_geometry(args.blender, blend_file, collection_name)
        if not submission or not submission.get("members"):
            print("    No members exported")
            feedback_history.append({"attempt": attempt, "status": "export_empty"})
            continue
        print(f"    {len(submission['members'])} members")
        (attempt_dir / "submission.json").write_text(json.dumps(submission, indent=2))

        print("[6] Submitting to eval server...")
        results = submit_and_poll(args.server, session_id, submission["members"])
        if results is None:
            feedback_history.append({"attempt": attempt, "status": "submit_failed"})
            continue
        (attempt_dir / "result.json").write_text(json.dumps(results, indent=2))

        fb = format_feedback(results)
        print(f"[7] Results:\n    {fb}")
        feedback_history.append({
            "attempt": attempt,
            "status": "passed" if results.get("all_passed") else "failed",
            "results": results,
            "feedback": fb,
        })
        final_results = results
        final_status = "passed" if results.get("all_passed") else "failed"

        if results.get("all_passed"):
            print(f"\n    All tests passed on attempt {attempt}!")
            break
        print("\n    Retrying with feedback...")
    else:
        print(f"\n    Exhausted {args.max_retries} retries")

    if final_results is not None:
        (work_dir / "results.json").write_text(json.dumps(final_results, indent=2))
    summary = {
        "task_id": args.task,
        "server": args.server,
        "session_id": session_id,
        "status": final_status,
        "all_passed": bool(final_results and final_results.get("all_passed")),
        "final_results": final_results,
        "history": feedback_history,
    }
    (work_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\nArtifacts in {work_dir}")
    print("Done.")


if __name__ == "__main__":
    main()
