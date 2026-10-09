#!/usr/bin/env python3
"""Check: a label's directory-name-derived provenance/label_class agrees with
what's actually stored in its own zarr.json attributes. Flags disagreement
either way -- never assumes the directory name or the stored metadata is the
one that's correct. Only compares when both sides are present; a label
missing the metadata field entirely is metadata_completeness.py's job, not
this one's.

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

CHECK_NAME = "metadata_consistency"


def check_label(label_dir: Path, root: Path, dataset: str) -> list[dict]:
    parts = label_dir.name.split("-", 2)
    if len(parts) < 3 or not parts[1] or not parts[2]:
        return []  # malformed name -- label_naming.py's job, nothing to compare here

    dir_provenance, dir_label_class, _ = parts
    attrs = read_group_attrs(label_dir)
    if attrs is None:
        return []

    rel = str(label_dir.relative_to(root))
    findings = []

    stored_provenance = attrs.get("provenance")
    if stored_provenance is not None and stored_provenance != dir_provenance:
        findings.append({
            "check": CHECK_NAME,
            "dataset": dataset,
            "path": rel,
            "field": "provenance_mismatch",
            "actual": f"dir={dir_provenance!r} vs metadata={stored_provenance!r}",
            "expected": "directory name and stored metadata agree",
            "severity": "error",
            "suggested_fix": "determine which is correct and fix the other (don't assume either side)",
        })

    stored_label_class = attrs.get("label_class")
    if stored_label_class is not None and stored_label_class != dir_label_class:
        findings.append({
            "check": CHECK_NAME,
            "dataset": dataset,
            "path": rel,
            "field": "label_class_mismatch",
            "actual": f"dir={dir_label_class!r} vs metadata={stored_label_class!r}",
            "expected": "directory name and stored metadata agree",
            "severity": "error",
            "suggested_fix": "determine which is correct and fix the other (don't assume either side)",
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
