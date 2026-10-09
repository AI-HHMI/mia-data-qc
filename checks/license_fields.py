#!/usr/bin/env python3
"""Check: every crop has a `license` field present on both its root
zarr.json and its raw/zarr.json, checked independently (the two files don't
necessarily mirror each other). Presence only, not value content -- license
values here are free-text legal-research notes, not a short enum, so no
vocab/consistency check applies. A field with an explicit null value still
counts as present; this check is about the key being entirely missing.

Real corpus survey (Oct 7 2026, zarr v3 only): root has the field present on
233 crops and missing on 727; raw has it present on 274 crops and missing on
686 (counts don't need to add to the same total -- a crop can be missing one
or both files entirely). Retrofitting zarr v2 support (Oct 8 2026) added 117
more crops, all missing `license` on both root and raw -- 844/802 missing
totals. Some stored values are
themselves warnings about license status (e.g. explicit "DO NOT REDISTRIBUTE",
"RESTRICTED -- HOLD", "UNKNOWN -- NO LICENCE IS STATED ANYWHERE" notes) --
this check only flags the field missing outright, not those cases, since
distinguishing "stated as unknown" from "a real license string" is a human
judgment call, not a structural one.

Checks zarr v2 crops (`.zattrs`) as well as zarr v3 (`zarr.json`) -- retrofitted
Oct 8 2026, see metadata_completeness.py's docstring for why (117 whole crops
on this corpus are zarr v2, previously entirely unscanned by this check).
"""
import argparse
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.report import write_check_report
from common.vocab import NON_DATASET_DIRS
from common.zarr_meta import group_exists, read_group_attrs

CHECK_NAME = "license_fields"


def _check_group(group_dir: Path, root: Path, dataset: str, label: str) -> list[dict]:
    attrs = read_group_attrs(group_dir)
    if attrs is None or "license" in attrs:
        return []

    rel = str(group_dir.relative_to(root))
    return [{
        "check": CHECK_NAME,
        "dataset": dataset,
        "path": rel,
        "field": "license",
        "actual": "missing",
        "expected": f"present on {label}'s own metadata (value may be null, but the key must exist)",
        "severity": "error",
        "suggested_fix": f"add the 'license' field to this crop's {label} metadata attributes",
    }]


def check_crop(crop_dir: Path, root: Path, dataset: str) -> list[dict]:
    findings = []

    if group_exists(crop_dir):
        findings.extend(_check_group(crop_dir, root, dataset, "root"))

    raw_dir = crop_dir / "raw"
    if group_exists(raw_dir):
        findings.extend(_check_group(raw_dir, root, dataset, "raw"))

    return findings


def iter_crop_dirs(root: Path):
    for dataset_dir in sorted(p for p in root.iterdir() if p.is_dir() and p.name not in NON_DATASET_DIRS):
        for crop_dir in sorted(p for p in dataset_dir.iterdir() if p.is_dir() and p.name.endswith(".zarr")):
            yield dataset_dir.name, crop_dir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="data", help="Directory to scan (default: data)")
    parser.add_argument("--reports-dir", default="reports", help="Where to write dated reports (default: reports)")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    findings = []
    n_crops = 0
    for dataset_name, crop_dir in iter_crop_dirs(root):
        n_crops += 1
        findings.extend(check_crop(crop_dir, root, dataset_name))

    run_date = datetime.date.today().isoformat()
    write_check_report(CHECK_NAME, findings, reports_dir=Path(args.reports_dir), date=run_date)

    print(f"{CHECK_NAME}: {len(findings)} finding(s) across {n_crops} crop(s) under {root}")
    if findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
