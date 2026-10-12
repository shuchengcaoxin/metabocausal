"""Verify downloaded source records and inventory local source files; no network calls."""

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
LITERATURE = ROOT / "MVP2" / "literature"
EXPECTED = {"shin_2014", "chen_2023", "zoodsma_2025", "yin_2025", "ukb_mapping_2025"}


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def main():
    studies, problems = [], []
    records = sorted((LITERATURE / "seeds").glob("*/source_record.json"))
    actual = {p.parent.name for p in records}
    for missing in sorted(EXPECTED - actual):
        problems.append({"study_id": missing, "reason": "source_record_missing"})
    for path in records:
        folder = path.parent
        record = json.loads(path.read_text(encoding="utf-8"))
        identity = record.get("identity", record)
        downloads = record.get("successful_files", record.get("attempts", []))
        verified = 0
        for item in downloads:
            if item.get("status") != "downloaded":
                continue
            relative = item.get("filename", item.get("local_path"))
            if not relative:
                problems.append({"study_id": folder.name, "reason": "download_without_path"})
                continue
            target = (folder / relative).resolve()
            if not target.is_relative_to(folder.resolve()):
                problems.append({"study_id": folder.name, "reason": "path_outside_study"})
                continue
            if not target.is_file():
                problems.append({"study_id": folder.name, "path": relative, "reason": "file_missing"})
                continue
            expected_hash = item.get("sha256")
            expected_size = item.get("bytes", item.get("size_bytes"))
            if not expected_hash or expected_hash != digest(target):
                problems.append({"study_id": folder.name, "path": relative, "reason": "hash_missing_or_mismatch"})
                continue
            if expected_size is not None and expected_size != target.stat().st_size:
                problems.append({"study_id": folder.name, "path": relative, "reason": "size_mismatch"})
                continue
            verified += 1
        files = []
        for asset in sorted(folder.rglob("*")):
            if not asset.is_file():
                continue
            size = asset.stat().st_size
            if size >= 100 * 1024 * 1024:
                problems.append({"study_id": folder.name, "path": asset.relative_to(folder).as_posix(), "reason": "github_file_limit"})
            files.append({"path": asset.relative_to(ROOT).as_posix(), "bytes": size, "sha256": digest(asset)})
        studies.append({
            "study_id": folder.name,
            "title": identity.get("title"),
            "doi": identity.get("doi"),
            "source_record": path.relative_to(ROOT).as_posix(),
            "screening_status": "seed_not_screened",
            "new_mr_import_status": "not_imported",
            "verified_download_records": verified,
            "files": files,
            "bytes": sum(f["bytes"] for f in files),
        })
    by_hash = {}
    for study in studies:
        for item in study["files"]:
            by_hash.setdefault(item["sha256"], []).append(item["path"])
    inventory = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "purpose": "Downloaded reading/screening seeds; not accepted MR evidence or a completed literature search.",
        "status": "verified" if not problems else "needs_attention",
        "studies": studies,
        "same_bytes_at_multiple_paths": [paths for paths in by_hash.values() if len(paths) > 1],
        "problems": problems,
        "total_bytes": sum(s["bytes"] for s in studies),
    }
    destination = LITERATURE / "SOURCE_INVENTORY.json"
    destination.write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": inventory["status"], "studies": len(studies), "files": sum(len(s["files"]) for s in studies), "total_bytes": inventory["total_bytes"], "verified_download_records": sum(s["verified_download_records"] for s in studies), "problems": problems}, ensure_ascii=False))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
