"""Strict JSON, immutable artifact writes and source identifiers."""

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re

SCHEMA_VERSION = 1
LOCK_PATH = Path(__file__).resolve().parents[1] / "data/model/source.lock.json"
SOURCE_URL = "https://github.com/SysBioChalmers/Human-GEM"
MAX_INDEX_BYTES = 128 * 1024 * 1024


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def canonical_bytes(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                       separators=(",", ":")) + "\n").encode("utf-8")


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def unique_dict(pairs):
    result = {}
    for key, value in pairs:
        if not isinstance(key, str) or key in result:
            raise ValueError(f"Duplicate or non-string key: {key!r}")
        result[key] = value
    return result


def strict_json(raw):
    def object_from_pairs(pairs):
        # The JSON decoder already guarantees string keys. Construct in C and
        # compare cardinality instead of repeating a Python loop for every key
        # of the full model. Duplicates (including escaped spellings) still fail;
        # no overwritten value can escape this hook. YAML keeps unique_dict's
        # additional non-string-key check.
        result = dict(pairs)
        if len(result) != len(pairs):
            raise ValueError("Duplicate JSON object key")
        return result

    def reject(value):
        raise ValueError(f"Non-finite JSON: {value}")

    def finite(value):
        number = float(value)
        if not math.isfinite(number):
            reject(value)
        return number

    return json.loads(raw, object_pairs_hook=object_from_pairs, parse_constant=reject,
                      parse_float=finite)


def normalise_chebi(value):
    if not isinstance(value, str):
        raise ValueError("chebi_id must be a string in CHEBI:123 or CHEBI_123 form")
    match = re.fullmatch(r"CHEBI[:_]([0-9]+)", value.strip(), flags=re.I)
    if not match or int(match[1]) <= 0:
        raise ValueError("Expected a positive CHEBI:123 or CHEBI_123 identifier; no name/fuzzy fallback")
    return "CHEBI:" + str(int(match[1]))


def source_lock():
    return strict_json(LOCK_PATH.read_bytes())


def asset_url(lock, name):
    return ("https://raw.githubusercontent.com/SysBioChalmers/Human-GEM/"
            + lock["commit"] + "/" + lock["files"][name]["path"])


def verify_sources(directory, lock=None):
    lock = lock or source_lock()
    directory = Path(directory)
    for name, info in lock["files"].items():
        if Path(name).name != name:
            raise ValueError("Source asset names must be basenames")
        if sha256((directory / name).read_bytes()) != info["sha256"]:
            raise ValueError(f"Source checksum mismatch: {name}")
    if (directory / "version.txt").read_text().strip() != lock["version"]:
        raise ValueError("Source version.txt does not match the pinned release")
    return lock


def write_new(path, raw):
    """Exclusive creation: never overwrite an existing source, index or receipt."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)
