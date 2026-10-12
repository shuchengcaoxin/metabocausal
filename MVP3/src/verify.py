"""Persist an offline test receipt with code hashes, interpreter and the actual log."""

import argparse
import importlib.metadata
import json
from pathlib import Path
import platform
import tempfile
import unittest

from .acceptance import REPO, code_identity
from .common import canonical_bytes, sha256, utc_now, write_new


def verify(output_root):
    Path(output_root).mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="gem-offline-", dir=output_root))
    code = code_identity()
    files = sorted((REPO / "MVP3").rglob("*.py")) + [REPO / "MVP3/tests/fixtures/gem/source_excerpt.json"]
    hashes = {str(path.relative_to(REPO)): sha256(path.read_bytes()) for path in files}
    suite = unittest.defaultTestLoader.loadTestsFromNames(["MVP3.tests.test_gem", "tests.test_1e"])
    with (directory / "tests.log").open("w", encoding="utf-8") as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    packages = {}
    try:
        packages["PyYAML"] = importlib.metadata.version("PyYAML")
    except importlib.metadata.PackageNotFoundError:
        packages["PyYAML"] = None
    summary = {"finished_at": utc_now(), "code": code, "code_file_sha256": hashes,
               "python": platform.python_version(), "packages": packages,
               "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
               "skipped": len(result.skipped), "passed": result.wasSuccessful(),
               "log_sha256": sha256((directory / "tests.log").read_bytes()),
               "scope": "Offline unit/fixture/CLI checks and original 1E tests; not live services or Slack",
               "artifact_directory": str(directory)}
    write_new(directory / "summary.json", canonical_bytes(summary))
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.output_root)
    print(json.dumps({key: result[key] for key in ("passed", "tests_run", "failures", "errors", "skipped", "artifact_directory")}, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
