"""L01 - runtime coupling map for the MVP2 literature layer (PR #16).

Question: does ANY MVP2 artefact (module or data file) reach the card path
(pipeline / render / classify / validate_card / tools registry) on current main?

Deterministic, offline. Writes outputs/L01_coupling.txt and outputs/L01_coupling.json.
Run from the repository root:
    python docs/research/section9_adversarial/rerun_2026-09-17/new_probes/mvp2/probes/probe_L01_coupling.py
"""

from __future__ import annotations

import ast
import io
import json
import os
import re
import subprocess
import sys

def _find_repo_root(start: str) -> str:
    """Walk up until the directory holds the card path modules AND MVP2/."""
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


REPO = _find_repo_root(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "outputs"))

# Directories that are NOT the running product: teammate history and this study itself.
EXCLUDED_TOPS = {"archive", "docs", "MVP2", ".git", "__pycache__", ".github"}

MVP2_MODULE_NAMES = {
    "europepmc",
    "merge_pairs",
    "pair_screening",
    "search",
    "search_europeanpmc",
}


def runtime_python_files() -> list:
    found = []
    for root, dirs, files in os.walk(REPO):
        rel_root = os.path.relpath(root, REPO).replace("\\", "/")
        top = rel_root.split("/")[0]
        if top in EXCLUDED_TOPS:
            dirs[:] = []
            continue
        dirs[:] = [d for d in dirs if d not in EXCLUDED_TOPS]
        for name in sorted(files):
            if name.endswith(".py"):
                found.append(os.path.join(root, name))
    return sorted(found)


def imported_names(path: str) -> list:
    with io.open(path, "r", encoding="utf-8") as handle:
        source = handle.read()
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:  # recorded, never silently skipped
        return [("<syntaxerror>", str(exc))]
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            names.append((node.module or "", node.lineno))
    return names


# A real path into the MVP2 tree must name one of its actual subdirectories.
# "MVP2/MVP3" in prose is not a path and is counted separately below.
PATH_LITERAL = re.compile(
    r"MVP2[/\\](?:data|src|scripts|literature|logs|tests)[/\\][A-Za-z0-9_./\\-]+"
)
PROSE_MENTION = re.compile(r"MVP2")


def path_literals(path: str) -> tuple:
    with io.open(path, "r", encoding="utf-8") as handle:
        source = handle.read()
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return ([], [])
    hits = []
    prose = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            for match in PATH_LITERAL.findall(node.value):
                hits.append((match, node.lineno))
            if not PATH_LITERAL.search(node.value) and PROSE_MENTION.search(node.value):
                prose.append((node.value.strip()[:140], node.lineno))
    return (hits, prose)


DYNAMIC_PROBE = r'''
import json, sys, os
sys.path.insert(0, os.getcwd())
loaded_before = set(sys.modules)
import pipeline, render, classify, validate_card, tools
report = {}
mvp2_root = os.path.abspath("MVP2")
leaked = []
for name, mod in list(sys.modules.items()):
    f = getattr(mod, "__file__", None)
    if f and os.path.abspath(f).startswith(mvp2_root + os.sep):
        leaked.append((name, f))
report["modules_loaded_from_MVP2"] = leaked
report["module_count_after_import"] = len(sys.modules)
report["TOOLS_names"] = [getattr(f, "__name__", repr(f)) for f in tools.TOOLS]
report["UNIMPLEMENTED_names"] = [getattr(f, "__name__", repr(f)) for f in tools.UNIMPLEMENTED]
report["get_literature_mr_in_TOOLS"] = any(
    getattr(f, "__name__", "") == "get_literature_mr" for f in tools.TOOLS
)
try:
    tools.get_literature_mr(["glycine"], ["coronary artery disease"])
    report["get_literature_mr_call"] = "returned without raising"
except NotImplementedError as exc:
    report["get_literature_mr_call"] = "NotImplementedError: %s" % exc
except Exception as exc:
    report["get_literature_mr_call"] = "%s: %s" % (type(exc).__name__, exc)
import inspect
sig = inspect.signature(classify.classify_state)
report["classify_state_signature"] = str(sig)
report["classify_lit_env_default"] = repr(sig.parameters["lit_env"].default)
print(json.dumps(report, indent=2, sort_keys=True))
'''


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    lines = []
    record = {"repo": REPO}

    files = runtime_python_files()
    lines.append("REPO ROOT: %s" % REPO)
    lines.append("runtime python files scanned (archive/, docs/, MVP2/ excluded): %d" % len(files))
    record["runtime_python_files_scanned"] = len(files)

    # --- static check 1: does any runtime module import an MVP2 module? ---
    import_hits = []
    for path in files:
        rel = os.path.relpath(path, REPO).replace("\\", "/")
        for name, lineno in imported_names(path):
            head = str(name).split(".")[0]
            if head in MVP2_MODULE_NAMES or str(name).startswith("MVP2"):
                import_hits.append({"file": rel, "line": lineno, "module": name})
    lines.append("")
    lines.append("[1] imports of an MVP2 module name from runtime code: %d" % len(import_hits))
    for hit in import_hits:
        lines.append("    %(file)s:%(line)s -> %(module)s" % hit)
    record["mvp2_module_imports"] = import_hits

    # --- static check 2: MVP2 path literals in runtime code ---
    literal_hits = []
    prose_hits = []
    for path in files:
        rel = os.path.relpath(path, REPO).replace("\\", "/")
        hits, prose = path_literals(path)
        for text, lineno in hits:
            literal_hits.append({"file": rel, "line": lineno, "literal": text})
        for text, lineno in prose:
            prose_hits.append({"file": rel, "line": lineno, "text": text})
    lines.append("")
    lines.append("[2] 'MVP2/<subdir>/...' path literals in runtime code: %d" % len(literal_hits))
    for hit in literal_hits:
        lines.append("    %(file)s:%(line)s -> %(literal)s" % hit)
    lines.append(
        "[2b] non-path 'MVP2' mentions in runtime string constants (prose only): %d"
        % len(prose_hits)
    )
    for hit in prose_hits:
        lines.append("    %(file)s:%(line)s -> %(text)s" % hit)
    record["mvp2_path_literals"] = literal_hits
    record["mvp2_prose_mentions"] = prose_hits

    # --- static check 3: sys.path insertion pointing at MVP2 ---
    syspath_hits = []
    for path in files:
        rel = os.path.relpath(path, REPO).replace("\\", "/")
        with io.open(path, "r", encoding="utf-8") as handle:
            for lineno, line in enumerate(handle, start=1):
                if "sys.path" in line and "MVP2" in line:
                    syspath_hits.append({"file": rel, "line": lineno, "text": line.strip()})
    lines.append("")
    lines.append("[3] sys.path manipulation naming MVP2 in runtime code: %d" % len(syspath_hits))
    for hit in syspath_hits:
        lines.append("    %(file)s:%(line)s -> %(text)s" % hit)
    record["mvp2_syspath_inserts"] = syspath_hits

    # --- static check 4: is MVP2 even an importable package? ---
    init_files = []
    for root, dirs, files_in in os.walk(os.path.join(REPO, "MVP2")):
        for name in files_in:
            if name == "__init__.py":
                init_files.append(
                    os.path.relpath(os.path.join(root, name), REPO).replace("\\", "/")
                )
    lines.append("")
    lines.append("[4] __init__.py files under MVP2/ (package markers): %d" % len(init_files))
    for name in init_files:
        lines.append("    %s" % name)
    record["mvp2_init_files"] = init_files

    # --- dynamic check: import the card path and look for MVP2 modules ---
    probe_path = os.path.join(OUT_DIR, "_L01_dynamic.py")
    with io.open(probe_path, "w", encoding="utf-8") as handle:
        handle.write(DYNAMIC_PROBE)
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, probe_path],
        cwd=REPO,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )
    lines.append("")
    lines.append("[5] dynamic import of pipeline/render/classify/validate_card/tools")
    lines.append("    exit code: %d" % proc.returncode)
    if proc.stderr.strip():
        lines.append("    stderr:")
        for line in proc.stderr.strip().splitlines():
            lines.append("      %s" % line)
    dynamic = None
    if proc.returncode == 0:
        dynamic = json.loads(proc.stdout)
        for line in proc.stdout.strip().splitlines():
            lines.append("    %s" % line)
    record["dynamic"] = dynamic
    record["dynamic_exit_code"] = proc.returncode
    try:
        os.remove(probe_path)
    except OSError:
        pass

    coupled = bool(import_hits or literal_hits or syspath_hits) or bool(
        (dynamic or {}).get("modules_loaded_from_MVP2")
    )
    record["runtime_coupling_detected"] = coupled
    lines.append("")
    lines.append("VERDICT: runtime coupling detected = %s" % coupled)

    text = "\n".join(lines) + "\n"
    with io.open(os.path.join(OUT_DIR, "L01_coupling.txt"), "w", encoding="utf-8") as handle:
        handle.write(text)
    with io.open(os.path.join(OUT_DIR, "L01_coupling.json"), "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, sort_keys=True)
        handle.write("\n")
    sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
