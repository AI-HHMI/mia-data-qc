#!/usr/bin/env python3
"""Check: every dataset directory under --root (default data/) matches
{modality}-{organism}-{dataset} -- modality and organism against the canonical
vocab, plus the rule that any PyTC-bundle dataset must carry the exact-case
token 'PyTC' somewhere in its name. Crop naming (crop-NNN_descriptor.zarr) is
a separate check, not this one.
"""
import argparse
import datetime
import difflib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.report import write_check_report
from common.vocab import MODALITIES, NON_DATASET_DIRS, ORGANISMS, ORGANISM_PLACEHOLDER

CHECK_NAME = "dataset_naming"


def _close_match(value: str, vocab: set) -> bool:
    return bool(difflib.get_close_matches(value, vocab, n=1, cutoff=0.75))


def check_dataset(name: str) -> list[dict]:
    findings = []
    parts = name.split("-", 2)

    if len(parts) < 3 or not parts[1] or not parts[2]:
        findings.append({
            "check": CHECK_NAME,
            "dataset": name,
            "path": name,
            "field": "directory_name",
            "actual": name,
            "expected": "{modality}-{organism}-{dataset}",
            "severity": "error",
            "suggested_fix": "rename to match {modality}-{organism}-{dataset}",
        })
        return findings

    modality, organism, dataset = parts

    if modality not in MODALITIES:
        severity = "error" if _close_match(modality, MODALITIES) else "warning"
        findings.append({
            "check": CHECK_NAME,
            "dataset": name,
            "path": name,
            "field": "modality",
            "actual": modality,
            "expected": "/".join(sorted(MODALITIES)),
            "severity": severity,
            "suggested_fix": (
                f"rename {modality}- prefix to a known modality"
                if severity == "error" else
                "confirm this is a genuinely new modality family, not a typo"
            ),
        })

    if organism != ORGANISM_PLACEHOLDER and organism not in ORGANISMS:
        if organism.lower() in ORGANISMS or organism != organism.lower():
            severity = "error"
            fix = f"rename organism token to lowercase canonical form (closest: {organism.lower()})"
        elif _close_match(organism.lower(), ORGANISMS):
            severity = "error"
            close = difflib.get_close_matches(organism.lower(), ORGANISMS, n=1, cutoff=0.75)[0]
            fix = f"rename organism token to match existing '{close}' (looks like a spelling variant)"
        else:
            severity = "warning"
            fix = "confirm this is a genuinely new organism, not a typo/variant, then add to common/vocab.py"
        findings.append({
            "check": CHECK_NAME,
            "dataset": name,
            "path": name,
            "field": "organism",
            "actual": organism,
            "expected": "/".join(sorted(ORGANISMS)) + f"/{ORGANISM_PLACEHOLDER}",
            "severity": severity,
            "suggested_fix": fix,
        })

    if "pytc" in dataset.lower() and "PyTC" not in name:
        findings.append({
            "check": CHECK_NAME,
            "dataset": name,
            "path": name,
            "field": "pytc_casing",
            "actual": name,
            "expected": "exact-case 'PyTC' token somewhere in the name",
            "severity": "error",
            "suggested_fix": "fix casing to the exact token 'PyTC'",
        })

    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="data", help="Directory to scan (default: data)")
    parser.add_argument("--reports-dir", default="reports", help="Where to write dated reports (default: reports)")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    names = sorted(p.name for p in root.iterdir() if p.is_dir() and p.name not in NON_DATASET_DIRS)

    findings = []
    for name in names:
        findings.extend(check_dataset(name))

    run_date = datetime.date.today().isoformat()
    write_check_report(CHECK_NAME, findings, reports_dir=Path(args.reports_dir), date=run_date)

    print(f"{CHECK_NAME}: {len(findings)} finding(s) across {len(names)} dataset dir(s) under {root}")
    if findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
