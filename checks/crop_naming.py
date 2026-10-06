#!/usr/bin/env python3
"""Check: every crop store directly under a dataset dir matches crop-NNN.zarr
or crop-NNN_descriptor.zarr (lmvd_structure_guideline.md §1) -- the descriptor
suffix is optional, either form is valid.
"""
import argparse
import datetime
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.report import write_check_report
from common.vocab import NON_DATASET_DIRS

CHECK_NAME = "crop_naming"

_CROP_RE = re.compile(r"^crop-(\d{3})(_.+)?\.zarr$")


def check_crop(name: str, dataset: str) -> list[dict]:
    if _CROP_RE.match(name):
        return []

    return [{
        "check": CHECK_NAME,
        "dataset": dataset,
        "path": f"{dataset}/{name}",
        "field": "crop_name",
        "actual": name,
        "expected": "crop-NNN.zarr or crop-NNN_descriptor.zarr",
        "severity": "error",
        "suggested_fix": "rename to match crop-NNN.zarr or crop-NNN_descriptor.zarr (3-digit number)",
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
    n_crops = 0
    for dataset_dir in sorted(p for p in root.iterdir() if p.is_dir() and p.name not in NON_DATASET_DIRS):
        for crop_dir in sorted(p for p in dataset_dir.iterdir() if p.is_dir() and p.name.endswith(".zarr")):
            n_crops += 1
            findings.extend(check_crop(crop_dir.name, dataset_dir.name))

    run_date = datetime.date.today().isoformat()
    write_check_report(CHECK_NAME, findings, reports_dir=Path(args.reports_dir), date=run_date)

    print(f"{CHECK_NAME}: {len(findings)} finding(s) across {n_crops} crop(s) under {root}")
    if findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
