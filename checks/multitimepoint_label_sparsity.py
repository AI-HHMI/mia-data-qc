#!/usr/bin/env python3
"""Check: a label whose bbox.timepoint_index is set (not null) and whose
crop's raw array genuinely has more than one timepoint (real 't' axis, T>1 --
read from axes/shape, not assumed) must be stored as a full-T array matching
raw's own T dimension, with real data written only at that one timepoint and
nothing at any other -- read directly off which top-level chunk directories
actually exist on disk, not inferred from metadata alone. Only handles a
plain (unsharded), regular chunk-grid array with the default chunk-key
encoding and a 't' axis first (every real example on this corpus is shaped
this way); anything else is skipped rather than guessed at.

Real corpus survey (Oct 8 2026): 9 labels have bbox.timepoint_index set, but
6 of them (`em-zebrafish-fish2`, all 6 crops) have a timepoint_index despite
their own raw having no 't' axis at all -- a single-timepoint dataset, so
this check doesn't apply (the field looks vestigial there, already a known
oddity: this is the same dataset bbox_sanity.py separately flags for a
lowercase "xyz" coordinate_order bug). Only 3 real multi-timepoint examples
exist, all under `lm-zebrafish-Betzig-mosaic-example_annotations_Thayer
/crop-001_dsr_timeseries_48t_1c.zarr` (raw T=48) -- all 3 already comply:
full-T shape, chunk_shape's T-axis is 1 (one chunk folder per timepoint), and
only the declared timepoint's chunk folder exists on disk. This check mostly
validates the rule going forward, per the original proposal.
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.report import write_check_report
from common.vocab import NON_DATASET_DIRS

CHECK_NAME = "multitimepoint_label_sparsity"


def _raw_t_count(crop_dir: Path):
    raw_dir = crop_dir / "raw" if (crop_dir / "raw").is_dir() else crop_dir
    try:
        data = json.loads((raw_dir / "zarr.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None
    multiscales = data.get("attributes", {}).get("ome", {}).get("multiscales", [])
    if not multiscales:
        return None
    axes = [a.get("name") for a in multiscales[0].get("axes", [])]
    datasets = multiscales[0].get("datasets", [])
    if not datasets or "t" not in axes:
        return None
    s0_path = datasets[0].get("path", "s0")
    try:
        shape = json.loads((raw_dir / s0_path / "zarr.json").read_text()).get("shape")
    except (OSError, json.JSONDecodeError):
        return None
    if shape is None or len(shape) != len(axes):
        return None
    return shape[axes.index("t")]


def check_label(label_dir: Path, root: Path, dataset: str, raw_t_count: int) -> list[dict]:
    zarr_json_path = label_dir / "zarr.json"
    try:
        attrs = json.loads(zarr_json_path.read_text()).get("attributes", {})
    except (OSError, json.JSONDecodeError):
        return []

    timepoint_index = attrs.get("bbox", {}).get("timepoint_index")
    if timepoint_index is None:
        return []

    multiscales = attrs.get("ome", {}).get("multiscales", [])
    if not multiscales:
        return []
    axes = [a.get("name") for a in multiscales[0].get("axes", [])]
    datasets = multiscales[0].get("datasets", [])
    if not datasets or not axes or axes[0] != "t":
        return []  # 't' not the first axis (or absent) -- not the shape this check handles

    s0_path = datasets[0].get("path", "s0")
    s0_dir = label_dir / s0_path
    try:
        s0_attrs = json.loads((s0_dir / "zarr.json").read_text())
    except (OSError, json.JSONDecodeError):
        return []

    shape = s0_attrs.get("shape")
    if shape is None or len(shape) != len(axes):
        return []
    if any(c.get("name") == "sharding_indexed" for c in s0_attrs.get("codecs", [])):
        return []  # sharded layout -- chunk-dir semantics differ, not handled here
    chunk_shape = s0_attrs.get("chunk_grid", {}).get("configuration", {}).get("chunk_shape")
    if not chunk_shape:
        return []

    rel = str(zarr_json_path.relative_to(root))
    findings = []

    if shape[0] != raw_t_count:
        findings.append({
            "check": CHECK_NAME, "dataset": dataset, "path": rel,
            "field": "shape[t]",
            "actual": shape[0],
            "expected": f"{raw_t_count} (full-T, matching raw)",
            "severity": "error",
            "suggested_fix": "re-store this label as a full-T array matching raw's T dimension",
        })
        return findings  # chunk-directory semantics below assume a full-T shape

    chunk_t_size = chunk_shape[0]
    expected_chunk_idx = timepoint_index // chunk_t_size

    c_dir = s0_dir / "c"
    present = set()
    if c_dir.is_dir():
        for p in c_dir.iterdir():
            if p.is_dir() and p.name.isdigit():
                present.add(int(p.name))

    if expected_chunk_idx not in present:
        findings.append({
            "check": CHECK_NAME, "dataset": dataset, "path": rel,
            "field": "timepoint_data_present",
            "actual": "no chunk data stored at the declared timepoint_index",
            "expected": f"chunk data present at timepoint {timepoint_index}",
            "severity": "error",
            "suggested_fix": "write this label's data at its declared bbox.timepoint_index",
        })

    extra = sorted(present - {expected_chunk_idx})
    if extra:
        findings.append({
            "check": CHECK_NAME, "dataset": dataset, "path": rel,
            "field": "timepoint_data_present",
            "actual": f"chunk data also stored at timepoint chunk index(es) {extra}",
            "expected": f"data only at timepoint {timepoint_index} (zeros/no chunks elsewhere)",
            "severity": "error",
            "suggested_fix": "remove chunks written outside the declared timepoint_index, or correct the declared index",
        })

    return findings


def iter_label_dirs(root: Path):
    for dataset_dir in sorted(p for p in root.iterdir() if p.is_dir() and p.name not in NON_DATASET_DIRS):
        for crop_dir in sorted(p for p in dataset_dir.iterdir() if p.is_dir() and p.name.endswith(".zarr")):
            labels_dir = crop_dir / "labels"
            if not labels_dir.is_dir():
                continue
            for label_dir in sorted(p for p in labels_dir.iterdir() if p.is_dir()):
                if (label_dir / "zarr.json").is_file():
                    yield dataset_dir.name, crop_dir, label_dir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="data", help="Directory to scan (default: data)")
    parser.add_argument("--reports-dir", default="reports", help="Where to write dated reports (default: reports)")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    findings = []
    n_checked = 0
    raw_t_cache = {}
    for dataset_name, crop_dir, label_dir in iter_label_dirs(root):
        if crop_dir not in raw_t_cache:
            raw_t_cache[crop_dir] = _raw_t_count(crop_dir)
        raw_t_count = raw_t_cache[crop_dir]
        if raw_t_count is None or raw_t_count <= 1:
            continue
        n_checked += 1
        findings.extend(check_label(label_dir, root, dataset_name, raw_t_count))

    run_date = datetime.date.today().isoformat()
    write_check_report(CHECK_NAME, findings, reports_dir=Path(args.reports_dir), date=run_date)

    print(f"{CHECK_NAME}: {len(findings)} finding(s) across {n_checked} label(s) in multi-timepoint crops under {root}")
    if findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
