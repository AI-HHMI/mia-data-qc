#!/usr/bin/env python3
"""Check: every label's zarr.json has all 12 required metadata fields present
(label_class, segmentation_type, provenance, proofreading_status, coverage,
bbox, source, created, parent_raw, dataset, publication, notes). Presence
only -- a field with an explicit null value (e.g. publication: null, meaning
"no publication") counts as present; this check is about fields that are
entirely missing, not about whether their values pass vocab/consistency
checks (label_naming.py, metadata_consistency.py, metadata_vocab.py,
voxel_size.py already cover that for the fields they're each scoped to).

Real corpus survey before building this (Oct 6 2026): every one of these 12
fields has real gaps on disk, from 10 to 102 missing labels -- no field was
dropped from scope for being already-clean.

Checks zarr v2 labels (`.zattrs`) as well as zarr v3 (`zarr.json`) -- retrofitted
Oct 8 2026 after discovering the 9 zarr v2 labels on this corpus had been
silently skipped by every check's `zarr.json`-only discovery filter, 4 of
them with real missing-field violations never surfaced.
"""
import argparse
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.report import write_check_report
from common.vocab import NON_DATASET_DIRS
from common.zarr_meta import group_exists, read_group_attrs

CHECK_NAME = "metadata_completeness"

REQUIRED_FIELDS = [
    "label_class", "segmentation_type", "provenance", "proofreading_status",
    "coverage", "bbox", "source", "created", "parent_raw", "dataset",
    "publication", "notes",
]


def check_label(label_dir: Path, root: Path, dataset: str) -> list[dict]:
    attrs = read_group_attrs(label_dir)
    if attrs is None:
        return []

    rel = str(label_dir.relative_to(root))
    findings = []

    for field in REQUIRED_FIELDS:
        if field not in attrs:
            findings.append({
                "check": CHECK_NAME,
                "dataset": dataset,
                "path": rel,
                "field": field,
                "actual": "missing",
                "expected": "present (value may be null, but the key must exist)",
                "severity": "error",
                "suggested_fix": f"add the '{field}' field to this label's zarr.json attributes",
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
