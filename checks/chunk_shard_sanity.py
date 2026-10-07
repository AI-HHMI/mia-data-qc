#!/usr/bin/env python3
"""Check: every sharded zarr array (raw and labels, every pyramid level) has a
shard shape that's an exact integer multiple of its own chunk shape, per axis
-- this is how the zarr3 sharding_indexed codec actually tiles a shard into
chunks, not a guessed convention. A real corpus survey (Oct 7 2026) found no
single universal chunk/shard shape in use (512/256/1024-cubed shards, 64/128/
32-cubed chunks all appear across different ingests), so this check doesn't
assert any particular value -- only that whatever values a given array uses
are internally self-consistent.

Only checks arrays using the sharding_indexed codec; a plain unsharded zarr
array has no chunk-vs-shard relationship to check.
"""
import argparse
import datetime
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.report import write_check_report
from common.vocab import NON_DATASET_DIRS

CHECK_NAME = "chunk_shard_sanity"
_RUNG_RE = re.compile(r"^s\d+$")


def _shard_and_chunk_shape(array_zarr_json: Path):
    try:
        data = json.loads(array_zarr_json.read_text())
    except (OSError, json.JSONDecodeError):
        return None, None
    shard = data.get("chunk_grid", {}).get("configuration", {}).get("chunk_shape")
    chunk = None
    for codec in data.get("codecs", []):
        if codec.get("name") == "sharding_indexed":
            chunk = codec.get("configuration", {}).get("chunk_shape")
    return shard, chunk


def check_array(array_zarr_json: Path, root: Path, dataset: str) -> list[dict]:
    shard, chunk = _shard_and_chunk_shape(array_zarr_json)
    if shard is None or chunk is None:
        return []  # not a sharded array -- nothing to cross-check

    rel = str(array_zarr_json.relative_to(root))
    findings = []

    if len(shard) != len(chunk):
        findings.append({
            "check": CHECK_NAME, "dataset": dataset, "path": rel,
            "field": "shard_chunk_dimension_mismatch",
            "actual": f"shard={shard}, chunk={chunk}",
            "expected": "shard and chunk shapes with the same number of dimensions",
            "severity": "error",
            "suggested_fix": "fix whichever shape has the wrong number of axes",
        })
        return findings

    bad_axes = [(s, c) for s, c in zip(shard, chunk) if c <= 0 or s <= 0 or s % c != 0]
    if bad_axes:
        findings.append({
            "check": CHECK_NAME, "dataset": dataset, "path": rel,
            "field": "shard_not_multiple_of_chunk",
            "actual": f"shard={shard}, chunk={chunk}",
            "expected": "every shard-shape axis an exact positive integer multiple of its chunk-shape axis",
            "severity": "error",
            "suggested_fix": "regenerate this array's pyramid level with a valid chunk/shard pair",
        })

    return findings


def iter_arrays(root: Path):
    """Yield (dataset_name, array_zarr_json) for every pyramid level of raw
    and every label, across every crop.
    """
    for dataset_dir in sorted(p for p in root.iterdir() if p.is_dir() and p.name not in NON_DATASET_DIRS):
        for crop_dir in sorted(p for p in dataset_dir.iterdir() if p.is_dir() and p.name.endswith(".zarr")):
            raw_dir = crop_dir / "raw" if (crop_dir / "raw").is_dir() else crop_dir
            for level_dir in sorted(p for p in raw_dir.iterdir() if p.is_dir() and _RUNG_RE.match(p.name)):
                zj = level_dir / "zarr.json"
                if zj.is_file():
                    yield dataset_dir.name, zj

            labels_dir = crop_dir / "labels"
            if not labels_dir.is_dir():
                continue
            for label_dir in sorted(p for p in labels_dir.iterdir() if p.is_dir()):
                for level_dir in sorted(p for p in label_dir.iterdir() if p.is_dir() and _RUNG_RE.match(p.name)):
                    zj = level_dir / "zarr.json"
                    if zj.is_file():
                        yield dataset_dir.name, zj


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="data", help="Directory to scan (default: data)")
    parser.add_argument("--reports-dir", default="reports", help="Where to write dated reports (default: reports)")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    findings = []
    n_arrays = 0
    for dataset_name, zj in iter_arrays(root):
        n_arrays += 1
        findings.extend(check_array(zj, root, dataset_name))

    run_date = datetime.date.today().isoformat()
    write_check_report(CHECK_NAME, findings, reports_dir=Path(args.reports_dir), date=run_date)

    print(f"{CHECK_NAME}: {len(findings)} finding(s) across {n_arrays} array(s) under {root}")
    if findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
