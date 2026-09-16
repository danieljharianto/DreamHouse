#!/usr/bin/env python3
"""Baseline health check for the local DreamHouse dev sandbox.

Runs two known-outcome scenarios against the local server and asserts the
expected result. This catches regressions in the server/validator/Blender
setup itself (as opposed to problems in a particular agent under test):

  1. examples.dev_agent:generate   -> must pass all 10 tests
  2. examples/quickstart.py stub   -> must fail only `completeness`

Usage:
  uvicorn server.app:app --host 127.0.0.1 --port 8000   # in another shell
  set BLENDER_PATH=...
  python scripts/run_baselines.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")
SERVER = os.environ.get("DREAMHOUSE_SERVER", "http://127.0.0.1:8000")
BLENDER = os.environ.get("BLENDER_PATH")


def _check_server() -> None:
    try:
        r = requests.get(f"{SERVER}/healthz", timeout=5)
        r.raise_for_status()
    except Exception as exc:
        sys.exit(
            f"Server not reachable at {SERVER}: {exc}\n"
            "Start it first: uvicorn server.app:app --host 127.0.0.1 --port 8000"
        )


def _run(cmd: list[str], output_dir: Path) -> dict:
    if output_dir.exists():
        try:
            shutil.rmtree(output_dir)
        except OSError:
            # Stale lock (OneDrive sync / antivirus on a just-written .blend
            # file). Not fatal: dev_run.py / quickstart.py overwrite files
            # in place, so a leftover directory doesn't affect the result.
            pass
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    summary_path = output_dir / "summary.json"
    if not summary_path.exists():
        tail = (proc.stderr or proc.stdout or "")[-1500:]
        return {"error": "no summary.json produced", "output_tail": tail}
    return json.loads(summary_path.read_text())


def baseline_pass() -> tuple[bool, str]:
    output_dir = REPO_ROOT / "runs" / "_baseline_pass"
    summary = _run(
        [
            sys.executable, str(REPO_ROOT / "scripts" / "dev_run.py"),
            "--task", "DEV_01_0001",
            "--agent", "examples.dev_agent:generate",
            "--output-dir", str(output_dir),
        ],
        output_dir,
    )
    if "error" in summary:
        return False, f"{summary['error']}\n{summary.get('output_tail', '')}"
    if summary.get("all_passed") is True:
        return True, "all 10 tests passed, as expected"
    failed = (summary.get("final_results") or {}).get("tests", {})
    failed = [t for t, v in failed.items() if not v]
    return False, f"expected all_passed=True, got all_passed={summary.get('all_passed')} failed={failed}"


def baseline_fail() -> tuple[bool, str]:
    output_dir = REPO_ROOT / "runs" / "_baseline_fail"
    summary = _run(
        [
            sys.executable, str(REPO_ROOT / "examples" / "quickstart.py"),
            "--task", "DEV_01_0001",
            "--blender", BLENDER,
            "--output-dir", str(output_dir),
            "--max-retries", "1",
        ],
        output_dir,
    )
    if "error" in summary:
        return False, f"{summary['error']}\n{summary.get('output_tail', '')}"
    results = summary.get("final_results") or {}
    tests = results.get("tests", {})
    failed = [t for t, v in tests.items() if not v]
    if summary.get("all_passed") is False and failed == ["completeness"]:
        return True, "failed only `completeness`, as expected"
    return False, f"expected failure limited to [completeness], got all_passed={summary.get('all_passed')} failed={failed}"


def main() -> None:
    if not BLENDER:
        sys.exit("Set BLENDER_PATH before running baselines.")
    _check_server()

    checks = [
        ("Baseline PASS (dev_agent, 4 categories)", baseline_pass),
        ("Baseline FAIL (stub agent, foundation only)", baseline_fail),
    ]

    print(f"Server: {SERVER}\n")
    all_ok = True
    for name, fn in checks:
        print(f"Running: {name} ...")
        ok, detail = fn()
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {detail}\n")
        all_ok = all_ok and ok

    if all_ok:
        print("All baselines OK -- server/validator/Blender pipeline is healthy.")
        sys.exit(0)
    else:
        print("One or more baselines deviated from the expected outcome -- see above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
