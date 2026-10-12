"""Minimal offline stand-in for the pytest features MVP2/tests actually uses.

Adapted from
docs/research/section9_adversarial/rerun_2026-09-17/new_probes/mvp2/probes/_minipytest.py
(same shim logic; the unused ``os`` import is dropped) so MVP2/tests stays
runnable in an environment with no pytest and no network (see M10 in
docs/research/section9_adversarial/rerun_2026-09-17/RESULTS.md). It supplies
exactly the three features MVP2/tests references -
`pytest.raises(..., match=...)`, the `tmp_path` fixture and a dotted-target
`monkeypatch.setattr` - and nothing else. It is a harness substitute, not a
claim that the suite "passes under pytest"; any behaviour that depends on a
pytest feature not implemented here is reported as `not_runnable`, never as
a pass.

Invoked as:  python _mvp2_pytest_shim.py <test_file.py>
Exit code 0 only when every collected test function returned without raising.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import re
import sys
import tempfile
import traceback
import types
from contextlib import contextmanager
from pathlib import Path


class Failed(AssertionError):
    pass


@contextmanager
def _raises(expected, match=None):
    try:
        yield
    except expected as exc:  # noqa: B902 - mirrors pytest.raises
        if match is not None and not re.search(match, str(exc)):
            raise Failed(
                "pytest.raises(match=%r) did not match %r" % (match, str(exc))
            ) from exc
        return
    raise Failed("pytest.raises(%s): no exception was raised" % getattr(expected, "__name__", expected))


class MiniMonkeyPatch:
    """setattr by dotted target only, with undo - the sole monkeypatch use in MVP2/tests."""

    def __init__(self):
        self._undo = []

    def setattr(self, target, value=None, raising=True):
        if not isinstance(target, str):
            raise NotImplementedError("this shim implements the dotted-string form only")
        module_name, _, attr = target.rpartition(".")
        module = importlib.import_module(module_name)
        if raising and not hasattr(module, attr):
            raise AttributeError("%s has no attribute %r" % (module_name, attr))
        self._undo.append((module, attr, getattr(module, attr, None), hasattr(module, attr)))
        setattr(module, attr, value)

    def undo(self):
        while self._undo:
            module, attr, old, existed = self._undo.pop()
            if existed:
                setattr(module, attr, old)
            else:
                delattr(module, attr)


def _install_pytest_shim() -> None:
    module = types.ModuleType("pytest")
    module.raises = _raises
    module.__mini_shim__ = True
    sys.modules["pytest"] = module


def main(argv) -> int:
    target = Path(argv[1]).resolve()
    _install_pytest_shim()

    spec = importlib.util.spec_from_file_location(target.stem, target)
    module = importlib.util.module_from_spec(spec)
    sys.modules[target.stem] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        print(json.dumps({
            "file": target.name,
            "collection_error": traceback.format_exc(),
            "tests": [],
        }, indent=2))
        return 2

    names = sorted(
        name for name, obj in vars(module).items()
        if name.startswith("test_") and inspect.isfunction(obj)
    )
    ok = True
    results = []
    for name in names:
        func = getattr(module, name)
        params = list(inspect.signature(func).parameters)
        kwargs = {}
        patcher = None
        unsupported = [p for p in params if p not in ("tmp_path", "monkeypatch")]
        if unsupported:
            results.append({
                "test": name,
                "status": "not_runnable",
                "detail": "uses pytest fixture(s) this shim does not provide: %s" % unsupported,
            })
            ok = False
            continue
        if "tmp_path" in params:
            kwargs["tmp_path"] = Path(tempfile.mkdtemp(prefix="minipytest_"))
        if "monkeypatch" in params:
            patcher = MiniMonkeyPatch()
            kwargs["monkeypatch"] = patcher
        try:
            func(**kwargs)
            results.append({"test": name, "status": "passed", "detail": ""})
        except Exception:
            ok = False
            results.append({
                "test": name,
                "status": "failed",
                "detail": traceback.format_exc(),
            })
        finally:
            if patcher is not None:
                patcher.undo()

    print(json.dumps({
        "file": target.name,
        "collection_error": None,
        "tests": results,
    }, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
