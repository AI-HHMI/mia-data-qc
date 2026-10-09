#!/usr/bin/env python3
"""Check: every label whose zarr.json has a `parent_raw` field present (field
presence itself is `metadata_completeness.py`'s job, not this check's) has
a value that's an existing directory on disk -- the raw store it claims to
be derived from. Only checks existence of the directory, not that a
`zarr.json`/`.zgroup` lives inside it (both zarr v3 and legacy zarr v2
stores appear on this corpus, and this check isn't about format).

Real corpus survey (Oct 7 2026): 1097 of 1148 labels have `parent_raw`
present (the other 51 are `metadata_completeness.py`'s finding, not this
check's). Of those 1097, 68 point to a path that no longer exists -- all 68
are labels in `em-human-CellMap-jrc-ut21-1413-003/crop-001_fullvol_tissuecrop.zarr`
whose `parent_raw` still says `.../crop-001_fullvol.zarr/raw`, a crop
directory name that's since been renamed (to `..._tissuecrop.zarr`) without
updating this field -- a real, previously-undetected case of exactly the
kind of stale-path drift a rename can cause.

Checks zarr v2 labels (`.zattrs`) as well as zarr v3 (`zarr.json`) -- retrofitted
Oct 8 2026, see metadata_completeness.py's docstring for why.
"""
import argparse
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.report import write_check_report
from common.vocab import NON_DATASET_DIRS
from common.zarr_meta import group_exists, read_group_attrs

CHECK_NAME = "parent_raw_validity"


def check_label(label_dir: Path, root: Path, dataset: str) -> list[dict]:
    attrs = read_group_attrs(label_dir)
    if attrs is None:
        return []

    parent_raw = attrs.get("parent_raw")
    if not isinstance(parent_raw, str):
        return []  # missing/null -- metadata_completeness.py's job, not this check's

    if Path(parent_raw).is_dir():
        return []

    rel = str(label_dir.relative_to(root))
    return [{
        "check": CHECK_NAME,
        "dataset": dataset,
        "path": rel,
        "field": "parent_raw",
        "actual": parent_raw,
        "expected": "an existing directory",
        "severity": "error",
        "suggested_fix": "update parent_raw to the raw store's current path (likely renamed)",
    }]


def iter_label_dirs(root: Path):
    for dataset_dir in sorted(p for p in root.iterdir() if p.is_dir() and p.name not in NON_DATASET_DIRS):
        for crop_dir in sorted(p for p in dataset_dir.iterdir() if p.is_dir() and p.name.endswith(".zarr")):
            labels_dir = crop_dir / "labels"
            if not labels_dir.is_dir():
                continue
            for label_dir in sorted(p for p in labels_dir.iterdir() if p.is_dir()):
                if group_exists(label_dir):
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
