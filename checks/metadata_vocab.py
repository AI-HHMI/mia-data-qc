#!/usr/bin/env python3
"""Check: a label's stored segmentation_type/proofreading_status/coverage
metadata (lmvd_structure_guideline.md §4) match their canonical enums. Only
checks a field when it's present -- a label missing one entirely is a
different, not-yet-built check's job (metadata completeness).

label_class/provenance are checked elsewhere (label_naming.py for the
directory-name convention, metadata_consistency.py for directory-vs-metadata
agreement) -- this check covers the other 3 of the 5 controlled-vocab fields
from the original Goal 1 checklist.
"""
import argparse
import datetime
import difflib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.report import write_check_report
from common.vocab import COVERAGES, NON_DATASET_DIRS, PROOFREADING_STATUSES, SEGMENTATION_TYPES

CHECK_NAME = "metadata_vocab"

FIELDS = {
    "segmentation_type": SEGMENTATION_TYPES,
    "proofreading_status": PROOFREADING_STATUSES,
    "coverage": COVERAGES,
}


def _close_match(value: str, vocab: set):
    matches = difflib.get_close_matches(value, vocab, n=1, cutoff=0.75)
    return matches[0] if matches else None


def check_label(label_dir: Path, root: Path, dataset: str) -> list[dict]:
    zarr_json_path = label_dir / "zarr.json"
    try:
        attrs = json.loads(zarr_json_path.read_text()).get("attributes", {})
    except (OSError, json.JSONDecodeError):
        return []

    rel = str(zarr_json_path.relative_to(root))
    findings = []

    for field, vocab in FIELDS.items():
        value = attrs.get(field)
        if value is None or value in vocab:
            continue
        close = _close_match(value, vocab)
        severity = "error" if close else "warning"
        fix = (
            f"rename to match existing '{close}' (looks like a spelling variant)"
            if close else
            f"confirm '{value}' is a genuinely new {field}, not a typo, then add to common/vocab.py"
        )
        findings.append({
            "check": CHECK_NAME,
            "dataset": dataset,
            "path": rel,
            "field": field,
            "actual": value,
            "expected": "/".join(sorted(vocab)),
            "severity": severity,
            "suggested_fix": fix,
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
