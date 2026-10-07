#!/usr/bin/env python3
"""Check: every crop has a `license` field present on both its root
zarr.json and its raw/zarr.json, checked independently (the two files don't
necessarily mirror each other). Presence only, not value content -- license
values here are free-text legal-research notes, not a short enum, so no
vocab/consistency check applies. A field with an explicit null value still
counts as present; this check is about the key being entirely missing.

Real corpus survey (Oct 7 2026): root zarr.json has the field present on 233
crops and missing on 727; raw/zarr.json has it present on 274 crops and
missing on 686 (counts don't need to add to the same total -- a crop can be
missing one or both files entirely). Some stored values are
themselves warnings about license status (e.g. explicit "DO NOT REDISTRIBUTE",
"RESTRICTED -- HOLD", "UNKNOWN -- NO LICENCE IS STATED ANYWHERE" notes) --
this check only flags the field missing outright, not those cases, since
distinguishing "stated as unknown" from "a real license string" is a human
judgment call, not a structural one.
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.report import write_check_report
from common.vocab import NON_DATASET_DIRS

CHECK_NAME = "license_fields"


def _check_zarr_json(zarr_json_path: Path, root: Path, dataset: str, label: str) -> list[dict]:
    try:
        attrs = json.loads(zarr_json_path.read_text()).get("attributes", {})
    except (OSError, json.JSONDecodeError):
        return []

    if "license" in attrs:
        return []

    rel = str(zarr_json_path.relative_to(root))
    return [{
        "check": CHECK_NAME,
        "dataset": dataset,
        "path": rel,
        "field": "license",
        "actual": "missing",
        "expected": f"present on {label} zarr.json (value may be null, but the key must exist)",
        "severity": "error",
        "suggested_fix": f"add the 'license' field to this crop's {label} zarr.json attributes",
    }]


def check_crop(crop_dir: Path, root: Path, dataset: str) -> list[dict]:
    findings = []

    root_zj = crop_dir / "zarr.json"
    if root_zj.is_file():
        findings.extend(_check_zarr_json(root_zj, root, dataset, "root"))

    raw_zj = crop_dir / "raw" / "zarr.json"
    if raw_zj.is_file():
        findings.extend(_check_zarr_json(raw_zj, root, dataset, "raw"))

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
