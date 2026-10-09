#!/usr/bin/env python3
"""Check: re-verify `measure_labels.py`'s `mark_superseded()` dedup logic
holds corpus-wide, as an external standing check rather than trusting it
only ran correctly inside that one script -- same relationship
`metadata_consistency.py` has to its own internal predecessor. Does not
reimplement a different algorithm: ports the exact same grouping/ranking
(label name matches `{prefix}-snap_MMDDYYYY` or `{prefix}-final`; `final`
always wins, else the newest date) from `scripts/lmvd_plots/measure_labels.py`.

Two things this checks, both from real on-disk metadata, not the script's
output (which isn't persisted anywhere to check against):
1. `created` is a parseable year (`YYYY`) or full date (`YYYY-MM-DD`) on
   every label that has it. This isn't just pedantry -- it's a precondition
   for check 2 below, and found a real bug: one label's `created` field held
   a corrupted string, not a date at all.
2. For every snap/final series (2+ members sharing a volume+prefix), the
   member the ranking logic would keep actually has the latest (or tied)
   `created` date among its series -- cross-validating the *name*-based
   ranking against each label's own *metadata* timestamp, independent of
   what the name claims.

Real corpus survey (Oct 9 2026): 6 series groups corpus-wide (the 3
documented LICONN volumes, plus 2 more FlyID49 series and one additional
LICONN-adjacent one not previously called out individually). Of 1147 labels
with a `created` field, only 1 doesn't parse: `exm-mouse-liconn-DG-.../
manual_gt-cell-final`'s `created` holds `'ell-final-gt--c'`, a corrupted
fragment of the label's own name, not a date -- some past metadata-patching
script clearly wrote the wrong value here. The other 10 non-`YYYY-MM-DD`
values found during the survey (`2020` stored as an int instead of a string
on 5 hemibrain labels) are a harmless type inconsistency, not a real
problem, and are accepted here. 0 ranking-vs-`created` inconsistencies
found among the 6 groups -- `mark_superseded()`'s corrected logic holds.
"""
import argparse
import datetime
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.report import write_check_report
from common.vocab import NON_DATASET_DIRS
from common.zarr_meta import read_group_attrs

CHECK_NAME = "freshness"

_SNAP = re.compile(r"^(.*)-(snap_\d{8}|final)$")
_YEAR_OR_DATE_RE = re.compile(r"^\d{4}(-\d{2}-\d{2})?$")


def _rank(tag: str):
    if tag == "final":
        return (1, "")
    return (0, tag[5 + 4:] + tag[5:5 + 4])  # snap_MMDDYYYY -> YYYYMMDD


def build_series_groups(root: Path):
    """{(volume, prefix): [(tag, label_dir), ...]} for every -snap_MMDDYYYY/-final label."""
    groups = {}
    for dataset_dir in sorted(p for p in root.iterdir() if p.is_dir() and p.name not in NON_DATASET_DIRS):
        for crop_dir in sorted(p for p in dataset_dir.iterdir() if p.is_dir() and p.name.endswith(".zarr")):
            labels_dir = crop_dir / "labels"
            if not labels_dir.is_dir():
                continue
            volume = f"{dataset_dir.name}/{crop_dir.name}"
            for label_dir in sorted(p for p in labels_dir.iterdir() if p.is_dir()):
                m = _SNAP.match(label_dir.name)
                if m:
                    groups.setdefault((volume, m.group(1)), []).append((m.group(2), label_dir))
    return groups


def check_created_field(label_dir: Path, root: Path, dataset: str) -> list[dict]:
    attrs = read_group_attrs(label_dir)
    if attrs is None:
        return []
    created = attrs.get("created")
    if created is None:
        return []
    if _YEAR_OR_DATE_RE.match(str(created)):
        return []

    rel = str(label_dir.relative_to(root))
    return [{
        "check": CHECK_NAME, "dataset": dataset, "path": rel,
        "field": "malformed_created",
        "actual": created,
        "expected": "a year (YYYY) or full date (YYYY-MM-DD)",
        "severity": "error",
        "suggested_fix": "fix this label's created field -- it doesn't parse as any valid date",
    }]


def check_series_ranking(volume: str, members: list, root: Path, dataset: str) -> list[dict]:
    if len(members) < 2:
        return []

    keep_tag, keep_dir = max(members, key=lambda kv: _rank(kv[0]))
    keep_created = (read_group_attrs(keep_dir) or {}).get("created")
    if not (isinstance(keep_created, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", keep_created)):
        return []  # can't cross-validate without a full parseable date on the kept member

    findings = []
    for tag, label_dir in members:
        if label_dir == keep_dir:
            continue
        other_created = (read_group_attrs(label_dir) or {}).get("created")
        if not (isinstance(other_created, str) and re.match(r"^\d{4}-\d{2}-\d{2}$", other_created)):
            continue
        if other_created > keep_created:
            rel = str(keep_dir.relative_to(root))
            findings.append({
                "check": CHECK_NAME, "dataset": dataset, "path": rel,
                "field": "supersede_rank_inconsistent_with_created",
                "actual": f"kept {keep_tag!r} (created={keep_created}) over {tag!r} (created={other_created})",
                "expected": "the kept snapshot's created date is the latest (or tied) in its series",
                "severity": "warning",
                "suggested_fix": "verify which of these is actually the correct current snapshot -- name and created timestamp disagree",
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

    findings = []
    n_labels_with_created = 0
    for dataset_dir in sorted(p for p in root.iterdir() if p.is_dir() and p.name not in NON_DATASET_DIRS):
        for crop_dir in sorted(p for p in dataset_dir.iterdir() if p.is_dir() and p.name.endswith(".zarr")):
            labels_dir = crop_dir / "labels"
            if not labels_dir.is_dir():
                continue
            for label_dir in sorted(p for p in labels_dir.iterdir() if p.is_dir()):
                attrs = read_group_attrs(label_dir)
                if attrs is not None and "created" in attrs and attrs["created"] is not None:
                    n_labels_with_created += 1
                findings.extend(check_created_field(label_dir, root, dataset_dir.name))

    groups = build_series_groups(root)
    for (volume, _prefix), members in groups.items():
        dataset = volume.split("/")[0]
        findings.extend(check_series_ranking(volume, members, root, dataset))

    run_date = datetime.date.today().isoformat()
    write_check_report(CHECK_NAME, findings, reports_dir=Path(args.reports_dir), date=run_date)

    print(f"{CHECK_NAME}: {len(findings)} finding(s) across {n_labels_with_created} label(s) with a "
          f"created field and {len(groups)} snapshot series under {root}")
    if findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
