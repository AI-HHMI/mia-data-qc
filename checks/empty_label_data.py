#!/usr/bin/env python3
"""Check: every label with complete metadata (passes group_exists, has a real
OME multiscale block) actually has chunk data written at its finest pyramid
level -- not just a declared shape with nothing behind it. Only checks
whether *any* chunk exists at the top level of the finest level's chunk
tree (zarr v3's `s0/c/` or zarr v2's bare `s0/`), not that every expected
chunk is present -- that would mean reading real pixel data, a different
cost class entirely (same reasoning `lmvd_quality_control.md`'s Phase 2
section gives for deferring `annotated_voxels <= declared shape` and
divergent-voxel-count checks, which need exactly that).

Real corpus survey (Oct 9 2026): 1158 labels, all have at least one chunk
present at their finest level -- 0 findings. A clean result, kept as a
standing check rather than discarded, since it protects against a real
failure mode (an ingest or label-write that completes metadata but is
killed before any chunk data lands) that hasn't happened yet on this
corpus, not just ones already found -- same reasoning as
`chunk_shard_sanity.py` and `multitimepoint_label_sparsity.py`.
"""
import argparse
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.report import write_check_report
from common.vocab import NON_DATASET_DIRS
from common.zarr_meta import get_multiscale, read_group_attrs

CHECK_NAME = "empty_label_data"


def check_label(label_dir: Path, root: Path, dataset: str) -> list[dict]:
    attrs = read_group_attrs(label_dir)
    if attrs is None:
        return []
    multiscale = get_multiscale(attrs)
    if multiscale is None:
        return []
    datasets = multiscale.get("datasets", [])
    if not datasets:
        return []

    s0_path = datasets[0].get("path", "s0")
    s0_dir = label_dir / s0_path
    if not s0_dir.is_dir():
        return []  # dangling pyramid-level reference -- pyramid_consistency.py's job

    is_zarr_v3 = (s0_dir / "zarr.json").is_file()
    chunk_root = (s0_dir / "c") if is_zarr_v3 and (s0_dir / "c").is_dir() else s0_dir
    has_any_chunk = chunk_root.is_dir() and any(chunk_root.iterdir())

    if has_any_chunk:
        return []

    rel = str(label_dir.relative_to(root))
    return [{
        "check": CHECK_NAME, "dataset": dataset, "path": rel,
        "field": "zero_chunk_data",
        "actual": "no chunk data found at this label's finest pyramid level",
        "expected": "at least one written chunk",
        "severity": "error",
        "suggested_fix": "this label's metadata is complete but no data was ever written -- re-export or remove it",
    }]


def iter_label_dirs(root: Path):
    for dataset_dir in sorted(p for p in root.iterdir() if p.is_dir() and p.name not in NON_DATASET_DIRS):
        for crop_dir in sorted(p for p in dataset_dir.iterdir() if p.is_dir() and p.name.endswith(".zarr")):
            labels_dir = crop_dir / "labels"
            if not labels_dir.is_dir():
                continue
            for label_dir in sorted(p for p in labels_dir.iterdir() if p.is_dir()):
                yield dataset_dir.name, label_dir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="data", help="Directory to scan (default: data)")
    parser.add_argument("--reports-dir", default="reports", help="Where to write dated reports (default: reports)")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    findings = []
    n_labels = 0
    for dataset_name, label_dir in iter_label_dirs(root):
        n_labels += 1
        findings.extend(check_label(label_dir, root, dataset_name))

    run_date = datetime.date.today().isoformat()
    write_check_report(CHECK_NAME, findings, reports_dir=Path(args.reports_dir), date=run_date)

    print(f"{CHECK_NAME}: {len(findings)} finding(s) across {n_labels} label dir(s) under {root}")
    if findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
