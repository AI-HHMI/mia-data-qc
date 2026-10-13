#!/usr/bin/env python3
"""Check: every label's exact non-zero voxel count at its finest pyramid
level must not exceed its own declared array shape's total voxel count.
This is a mathematically impossible condition under correct measurement --
`np.count_nonzero` can never return more than the array's own size -- so a
finding here points at a bug in how the count or the shape was derived
(e.g. a stale/mismatched `zarr.json`, a corrupted sharding index producing
a bogus written-chunk bbox, or a declared shape that no longer matches what
was actually written), not a plausible real annotation.

One of the two still-open "data sanity" items from the original design
proposal (see `lmvd_quality_control.md`); the other
(same-class-divergent-voxel-counts) shipped as `divergent_voxel_counts.py`.
No per-label stored field carries a voxel count to compare against
(`n_instances` is an instance count, not a voxel count), so this is a real
decode, same infrastructure as `divergent_voxel_counts.py`:
`common/voxel_count.py`'s `exact_nonzero_count()`, itself gated by
`common/zarr_meta.py`'s `written_chunk_bounds()` so a label with a huge
declared shape but a small written region stays cheap. Needs `zarr`/`numpy`
(see `pixi.toml`); run via `pixi run python3`, not bare `python3`. Same
three cost gates as `divergent_voxel_counts.py` -- a label too large on
disk (>2GB), too large decompressed (>800GB), or spanning too many chunks
(>200K) is skipped entirely (count unavailable), never guessed at.
"""
import argparse
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.report import write_check_report
from common.vocab import NON_DATASET_DIRS
from common.voxel_count import exact_nonzero_count
from common.zarr_meta import get_multiscale, read_array_meta, read_group_attrs

CHECK_NAME = "annotated_voxels_sanity"


def iter_label_dirs(root: Path):
    for dataset_dir in sorted(p for p in root.iterdir() if p.is_dir() and p.name not in NON_DATASET_DIRS):
        for crop_dir in sorted(p for p in dataset_dir.iterdir() if p.is_dir() and p.name.endswith(".zarr")):
            labels_dir = crop_dir / "labels"
            if not labels_dir.is_dir():
                continue
            for label_dir in sorted(p for p in labels_dir.iterdir() if p.is_dir()):
                yield dataset_dir.name, crop_dir, label_dir


def check_label(dataset: str, crop_dir: Path, label_dir: Path, root: Path) -> list[dict]:
    attrs = read_group_attrs(label_dir)
    if attrs is None:
        return []
    multiscale = get_multiscale(attrs)
    if multiscale is None:
        return []
    datasets = multiscale.get("datasets", [])
    if not datasets:
        return []

    s0_dir = label_dir / datasets[0].get("path", "s0")
    if not s0_dir.is_dir():
        return []  # dangling pyramid-level reference -- pyramid_consistency.py's job

    meta = read_array_meta(s0_dir)
    if meta is None or not meta.get("shape"):
        return []

    declared_voxels = 1
    for dim in meta["shape"]:
        declared_voxels *= dim

    nonzero = exact_nonzero_count(s0_dir)
    if nonzero is None or nonzero <= declared_voxels:
        return []

    return [{
        "check": CHECK_NAME, "dataset": dataset,
        "path": str(label_dir.relative_to(root)),
        "field": "annotated_voxels",
        "actual": f"{nonzero} non-zero voxels",
        "expected": f"<= {declared_voxels} (the array's own declared shape {meta['shape']})",
        "severity": "error",
        "suggested_fix": "re-derive this label's shape/chunk metadata or data -- a count exceeding the declared array size means the shape or the written data is wrong",
    }]


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
    for dataset_name, crop_dir, label_dir in iter_label_dirs(root):
        n_labels += 1
        findings.extend(check_label(dataset_name, crop_dir, label_dir, root))
        print(f"  [{n_labels}] {label_dir.relative_to(root)}", flush=True)

    run_date = datetime.date.today().isoformat()
    write_check_report(CHECK_NAME, findings, reports_dir=Path(args.reports_dir), date=run_date)

    print(f"{CHECK_NAME}: {len(findings)} finding(s) across {n_labels} label(s) under {root}")
    if findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
