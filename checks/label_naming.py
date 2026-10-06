#!/usr/bin/env python3
"""Check: every label directory under data/{dataset}/crop-*.zarr/labels/ matches
{provenance}-{label_class}-{specific_info} -- provenance is one of the 4
controlled values (manual_gt/auto_pred/proofread/public_gt), label_class is
checked against the canonical set in common/vocab.py.

Only directories that look like real labels are checked (has a rung subdir like
s0/) -- a stray non-label file/dir in labels/ (leftover scripts, logs) is a
different, separate check's job, not this one's.
"""
import argparse
import datetime
import difflib
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.report import write_check_report
from common.vocab import LABEL_CLASSES, NON_DATASET_DIRS, PROVENANCE

CHECK_NAME = "label_naming"
_RUNG_RE = re.compile(r"^s\d+$")


def _looks_like_label(entry: Path) -> bool:
    try:
        return any(_RUNG_RE.match(p.name) for p in entry.iterdir() if p.is_dir())
    except OSError:
        return False


def check_label(name: str, dataset: str, rel_path: str) -> list[dict]:
    findings = []
    parts = name.split("-", 2)

    if len(parts) < 3 or not parts[1] or not parts[2]:
        findings.append({
            "check": CHECK_NAME,
            "dataset": dataset,
            "path": rel_path,
            "field": "label_name",
            "actual": name,
            "expected": "{provenance}-{label_class}-{specific_info}",
            "severity": "error",
            "suggested_fix": "rename to match {provenance}-{label_class}-{specific_info}",
        })
        return findings

    provenance, label_class, _specific_info = parts

    if provenance not in PROVENANCE:
        findings.append({
            "check": CHECK_NAME,
            "dataset": dataset,
            "path": rel_path,
            "field": "provenance",
            "actual": provenance,
            "expected": "/".join(sorted(PROVENANCE)),
            "severity": "error",
            "suggested_fix": "rename provenance prefix to one of the 4 controlled values",
        })

    if label_class not in LABEL_CLASSES:
        close = difflib.get_close_matches(label_class, LABEL_CLASSES, n=1, cutoff=0.75)
        severity = "error" if close else "warning"
        fix = (
            f"rename label_class to match existing '{close[0]}' (looks like a spelling variant)"
            if close else
            "confirm this is a genuinely new label_class, not a typo, then add to common/vocab.py"
        )
        findings.append({
            "check": CHECK_NAME,
            "dataset": dataset,
            "path": rel_path,
            "field": "label_class",
            "actual": label_class,
            "expected": "see common/vocab.py:LABEL_CLASSES",
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
                if _looks_like_label(label_dir):
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
        rel_path = str(label_dir.relative_to(root))
        findings.extend(check_label(label_dir.name, dataset_name, rel_path))

    run_date = datetime.date.today().isoformat()
    write_check_report(CHECK_NAME, findings, reports_dir=Path(args.reports_dir), date=run_date)

    print(f"{CHECK_NAME}: {len(findings)} finding(s) across {n_labels} label dir(s) under {root}")
    if findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
