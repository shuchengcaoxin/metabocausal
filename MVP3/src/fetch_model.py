"""Explicit, checksum-locked source acquisition. Never called by the lookup tool."""

import argparse
import json
from pathlib import Path
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .common import asset_url, canonical_bytes, sha256, source_lock, utc_now, verify_sources, write_new

MAX_ASSET_BYTES = 32 * 1024 * 1024


def download(url):
    for attempt in (1, 2):
        try:
            request = Request(url, headers={"User-Agent": "MetaboCausal-HumanGEM/1"})
            with urlopen(request, timeout=30) as response:
                raw = response.read(MAX_ASSET_BYTES + 1)
            if len(raw) > MAX_ASSET_BYTES:
                raise ValueError("Source asset exceeds the download size limit")
            return raw
        except HTTPError as exc:
            code = exc.code
            exc.close()
            if attempt == 1 and 500 <= code < 600:
                continue
            raise


def fetch_model(output_dir):
    directory = Path(output_dir)
    lock = source_lock()
    receipt = {"source": lock, "started_at": utc_now(), "assets": [], "status": "error"}
    directory.mkdir(parents=True, exist_ok=True)
    try:
        for name, info in lock["files"].items():
            target = directory / name
            row = {"name": name, "url": asset_url(lock, name), "retrieved_at": utc_now()}
            receipt["assets"].append(row)
            if target.exists():
                raw = target.read_bytes()
                row["mode"] = "verified_existing"
            else:
                raw = download(row["url"])
                row["mode"] = "downloaded"
            row.update(sha256=sha256(raw), bytes=len(raw))
            if row["sha256"] != info["sha256"]:
                raise ValueError(f"Checksum mismatch for {name}; existing files will not be replaced")
            if row["mode"] == "downloaded":
                write_new(target, raw)
        verify_sources(directory, lock)
        receipt["status"] = "ok"
    except Exception as exc:
        receipt["error"] = f"{type(exc).__name__}: {exc}"
    receipt["finished_at"] = utc_now()
    write_new(directory / ("fetch-" + uuid.uuid4().hex + ".json"), canonical_bytes(receipt))
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    result = fetch_model(args.output_dir)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
