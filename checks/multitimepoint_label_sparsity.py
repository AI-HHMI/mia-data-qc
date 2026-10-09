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
only the declared timepoint's chunk folder exists on disk. Retrofitting zarr
v2 support (below) surfaced 5 more real examples missed before -- 1 Betzig
zarr v2 label with `timepoint_index: null` (not applicable, correctly
skipped) and 4 genuine `manual_gt-cell-t0`/`t9`/`t31` timepoint-specific
labels across 2 more Betzig crops, all already compliant. This check mostly
validates the rule going forward, per the original proposal.

Checks zarr v2 crops/labels (`.zattrs`/`.zarray`) as well as zarr v3
(`zarr.json`) -- retrofitted Oct 8 2026, see metadata_completeness.py's
docstring for why. zarr v2 has no `c/` chunk-key prefix (chunks live as
`s0/<t_index>/...` directly); zarr v3's default chunk-key encoding prefixes
every chunk path with `c/`. Both are handled.
"""
import argparse
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.report import write_check_report
from common.vocab import NON_DATASET_DIRS
from common.zarr_meta import get_multiscale, group_exists, read_array_meta, read_group_attrs

CHECK_NAME = "multitimepoint_label_sparsity"


def _raw_t_count(crop_dir: Path):
    raw_dir = crop_dir / "raw" if (crop_dir / "raw").is_dir() else crop_dir
    attrs = read_group_attrs(raw_dir)
    multiscale = get_multiscale(attrs)
    if multiscale is None:
        return None
    axes = [a.get("name") for a in multiscale.get("axes", [])]
    datasets = multiscale.get("datasets", [])
    if not datasets or "t" not in axes:
        return None
    s0_path = datasets[0].get("path", "s0")
    array_meta = read_array_meta(raw_dir / s0_path)
    if array_meta is None:
        return None
    shape = array_meta["shape"]
    if shape is None or len(shape) != len(axes):
        return None
    return shape[axes.index("t")]


def check_label(label_dir: Path, root: Path, dataset: str, raw_t_count: int) -> list[dict]:
    attrs = read_group_attrs(label_dir)
    if attrs is None:
        return []

    timepoint_index = (attrs.get("bbox") or {}).get("timepoint_index")
    if timepoint_index is None:
        return []

    multiscale = get_multiscale(attrs)
    if multiscale is None:
        return []
    axes = [a.get("name") for a in multiscale.get("axes", [])]
    datasets = multiscale.get("datasets", [])
    if not datasets or not axes or axes[0] != "t":
        return []  # 't' not the first axis (or absent) -- not the shape this check handles

    s0_path = datasets[0].get("path", "s0")
    s0_dir = label_dir / s0_path
    array_meta = read_array_meta(s0_dir)
    if array_meta is None:
        return []

    shape = array_meta["shape"]
    if shape is None or len(shape) != len(axes):
        return []
    if array_meta["shard_shape"] is not None:
        return []  # sharded layout -- chunk-dir semantics differ, not handled here
    chunk_shape = array_meta["chunk_shape"]
    if not chunk_shape:
        return []

    is_zarr_v3 = (s0_dir / "zarr.json").is_file()
    if not is_zarr_v3 and array_meta.get("dimension_separator") != "/":
        return []  # flat chunk-key files (e.g. "0.0.1.2.3"), not nested dirs -- not handled here

    rel = str(label_dir.relative_to(root))
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

    # zarr v3's default chunk-key encoding prefixes every chunk path with "c/";
    # zarr v2 has no such prefix -- the t-chunk index is the array dir's own
    # first-level subdirectory.
    t_chunk_parent = (s0_dir / "c") if is_zarr_v3 else s0_dir
    present = set()
    if t_chunk_parent.is_dir():
        for p in t_chunk_parent.iterdir():
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
                if group_exists(label_dir):
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
