"""L03 - run the MVP2 test suite as it stands on current main.

Step 1 records what the documented runner actually does in the measured environment.
Step 2 re-runs the same test functions under a minimal offline shim (_minipytest.py) so
that the behaviour of the code under test is still measured rather than left unknown.

Deterministic, offline, no credential.

Run from the repository root:
    python docs/research/section9_adversarial/rerun_2026-09-17/new_probes/mvp2/probes/probe_L03_tests.py
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys


def _find_repo_root(start: str) -> str:
    here = os.path.abspath(start)
    while True:
        if (
            os.path.isfile(os.path.join(here, "render.py"))
            and os.path.isfile(os.path.join(here, "classify.py"))
            and os.path.isdir(os.path.join(here, "MVP2"))
        ):
            return here
        parent = os.path.dirname(here)
        if parent == here:
            raise RuntimeError("repository root not found above %s" % start)
        here = parent


HERE = os.path.dirname(os.path.abspath(__file__))
REPO = _find_repo_root(HERE)
OUT_DIR = os.path.abspath(os.path.join(HERE, "..", "outputs"))
TESTS_DIR = os.path.join(REPO, "MVP2", "tests")
RUNNER = os.path.join(HERE, "_minipytest.py")


def run(cmd, cwd):
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", env=env
    )


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    lines = ["L03 - MVP2/tests on current main", ""]
    record = {}

    # -- step 1: the documented runner -------------------------------------------------
    lines.append("[1] documented runner: python -m pytest MVP2/tests -q   (cwd = repo root)")
    proc = run([sys.executable, "-m", "pytest", "MVP2/tests", "-q"], REPO)
    lines.append("    exit code: %d" % proc.returncode)
    for stream, label in ((proc.stdout, "stdout"), (proc.stderr, "stderr")):
        if stream.strip():
            lines.append("    %s:" % label)
            for line in stream.strip().splitlines():
                lines.append("      %s" % line)
    record["pytest"] = {
        "exit_code": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }

    probe = run(
        [sys.executable, "-c", "import importlib.util,sys; print(importlib.util.find_spec('pytest'))"],
        REPO,
    )
    lines.append("    importlib.util.find_spec('pytest') -> %s" % probe.stdout.strip())
    record["pytest_spec"] = probe.stdout.strip()

    req = os.path.join(REPO, "requirements.txt")
    with io.open(req, "r", encoding="utf-8") as handle:
        req_text = handle.read()
    lines.append(
        "    'pytest' appears in requirements.txt: %s" % ("pytest" in req_text)
    )
    record["pytest_in_requirements"] = "pytest" in req_text

    # -- step 2: same functions under the offline shim ---------------------------------
    lines.append("")
    lines.append("[2] same test functions under probes/_minipytest.py (offline shim;")
    lines.append("    supplies only pytest.raises and tmp_path - see that file's docstring)")
    lines.append("")
    files = sorted(
        os.path.join(TESTS_DIR, name)
        for name in os.listdir(TESTS_DIR)
        if name.startswith("test_") and name.endswith(".py")
    )
    per_file = []
    total = {"passed": 0, "failed": 0, "not_runnable": 0, "collection_error": 0}
    for path in files:
        proc = run([sys.executable, RUNNER, path], REPO)
        try:
            payload = json.loads(proc.stdout)
        except ValueError:
            payload = {
                "file": os.path.basename(path),
                "collection_error": proc.stdout + proc.stderr,
                "tests": [],
            }
        payload["exit_code"] = proc.returncode
        per_file.append(payload)
        lines.append("  %s" % payload["file"])
        if payload.get("collection_error"):
            total["collection_error"] += 1
            lines.append("    COLLECTION ERROR:")
            for line in str(payload["collection_error"]).strip().splitlines():
                lines.append("      %s" % line)
            continue
        for test in payload["tests"]:
            total[test["status"]] = total.get(test["status"], 0) + 1
            lines.append("    %-8s %s" % (test["status"], test["test"]))
            if test["detail"]:
                for line in test["detail"].strip().splitlines():
                    lines.append("        %s" % line)

    lines.append("")
    lines.append(
        "  totals: passed=%d failed=%d not_runnable=%d collection_errors=%d"
        % (
            total.get("passed", 0),
            total.get("failed", 0),
            total.get("not_runnable", 0),
            total.get("collection_error", 0),
        )
    )
    record["shim"] = {"per_file": per_file, "totals": total}

    text = "\n".join(lines) + "\n"
    with io.open(os.path.join(OUT_DIR, "L03_tests.txt"), "w", encoding="utf-8") as handle:
        handle.write(text)
    with io.open(os.path.join(OUT_DIR, "L03_tests.json"), "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, sort_keys=True)
        handle.write("\n")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
