"""Rebuild public API indices from public sources only."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import _traits


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", choices=("epigraphdb", "opengwas", "all"), default="epigraphdb")
    args = parser.parse_args()
    sources = ("epigraphdb", "opengwas") if args.source == "all" else (args.source,)
    report = []
    for source in sources:
        target = _traits.VOCABULARY_PATHS[source]
        temporary = target.with_suffix(".building.json")
        builder = getattr(_traits, f"build_{source}_vocabulary")
        try:
            count = builder(temporary)
            if not count:
                raise ValueError("Empty index: previous cache was preserved")
            temporary.replace(target)
            report.append({"source": source, "status": "ok", "rows": count})
        except Exception as exc:
            # Do not print request/header values: a key may be in transport exceptions.
            report.append({"source": source, "status": "error", "error_type": type(exc).__name__,
                           "action": "Check connectivity and OPENGWAS_JWT for OpenGWAS; previous cache preserved."})
            temporary.unlink(missing_ok=True)
    print(json.dumps(report, indent=2))
    return int(any(row["status"] == "error" for row in report))


if __name__ == "__main__":
    raise SystemExit(main())
