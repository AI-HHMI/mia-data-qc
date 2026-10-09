#!/usr/bin/env python3
"""Check: cross-reference every real label on disk against every
`mia_annotation` issue at a terminal ingested status
(`manual_gt_ingested`/`public_gt_ingested`/`proofread_ingested`/`auto_pred_ingested`),
in both directions, using the 3-component title convention
(`{dataset-dir}_{crop}_{label-name}`) as an exact-string index built directly
from real on-disk names -- not a board path field (those can be stale; see
`label_field_drift.py`'s own docstring for why this check uses title instead
of `source_Image_Path`, which turned out to resolve every case that
`source_Image_Path`-based matching previously missed).

Four distinct outcomes, flagged separately so each can be handled differently:
- `untracked_label` (error): a real label with no issue at all referencing it.
- `untracked_snapshot` (warning): a real label matching the superseded-snapshot
  naming pattern (`-snap_MMDDYYYY`) with no dedicated issue -- likely
  intentional (only the current/final snapshot in a weekly export series
  gets tracked), lower urgency, flagged for visibility only.
- `title_format_mismatch` (error): a terminal-status issue whose title uses
  the old slash-separated format (`dataset/crop/label`) instead of the
  current underscore-joined 3-component convention -- the issue does track a
  real label, it just needs a rename, not new tracking.
- `issue_no_matching_label` (error): a terminal-status issue whose title (in
  the current convention) doesn't correspond to any real directory on disk
  at all -- likely renamed or removed without updating/closing the issue.
  Category-tracker issues (one per label type on a >100-crop dataset, title
  has no `crop-NNN` token at all) are excluded from this -- they're not
  supposed to resolve to a single label.

Real corpus survey (Oct 9 2026): 1158 real labels, 1124 mia_annotation
items (1104 at a terminal status). 61 real labels have no matching terminal
issue title: 46 are superseded-snapshot history (expected), 15 are
genuinely untracked (2 known-pending inter-annotator assessments on
`exm-drosophila-rubinlab-30X_lobeTm1_...`, the Betzig `crop-010`
auto_pred-cell label the corpus owner flagged directly, and several Thayer
pipeline-intermediate labels). 7 terminal issues don't match the canonical
index: 5 are category trackers (correctly excluded), 2 are the known
slash-titled Thayer t10/t25 issues (title_format_mismatch) -- these 2 are
deliberately not also counted as `untracked_label` on the real-label side,
since they're tracked, just under the wrong title format.
"""
import argparse
import datetime
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.github import fetch_project_items, MIA_ANNOTATION_PROJECT
from common.report import write_check_report
from common.vocab import NON_DATASET_DIRS
from common.zarr_meta import group_exists

CHECK_NAME = "orphaned_ingest"

TERMINAL_STATUSES = {
    "manual_gt_ingested", "public_gt_ingested", "proofread_ingested", "auto_pred_ingested",
}
_SNAPSHOT_RE = re.compile(r"-snap_\d{8}$")
_CROP_TOKEN_RE = re.compile(r"crop-\d{3}")


def build_canonical_index(root: Path):
    """{canonical_title: label_dir} for every real label on disk."""
    index = {}
    for dataset_dir in sorted(p for p in root.iterdir() if p.is_dir() and p.name not in NON_DATASET_DIRS):
        for crop_dir in sorted(p for p in dataset_dir.iterdir() if p.is_dir() and p.name.endswith(".zarr")):
            labels_dir = crop_dir / "labels"
            if not labels_dir.is_dir():
                continue
            crop_name = crop_dir.name[:-len(".zarr")]
            for label_dir in sorted(p for p in labels_dir.iterdir() if p.is_dir()):
                if group_exists(label_dir):
                    index[f"{dataset_dir.name}_{crop_name}_{label_dir.name}"] = label_dir
    return index


def check_issues(terminal_items: list, canonical: dict, root: Path):
    """Reverse direction: every terminal issue should resolve to a real label."""
    findings = []
    format_mismatch_keys = set()  # (dataset_dir_name, label_name) already reported here

    for item in terminal_items:
        title = item.get("title") or ""
        if title in canonical:
            continue

        url = item.get("content", {}).get("url", "")

        if "/" in title:
            parts = title.split("/")
            format_mismatch_keys.add((parts[0], parts[-1]))
            findings.append({
                "check": CHECK_NAME, "dataset": parts[0], "path": f"mia_annotation issue {url}",
                "field": "title_format_mismatch",
                "actual": title,
                "expected": "the current {dataset-dir}_{crop}_{label-name} title convention",
                "severity": "error",
                "suggested_fix": "rename this issue's title to the current 3-component convention",
            })
            continue

        if not _CROP_TOKEN_RE.search(title):
            continue  # category-tracker issue -- not supposed to resolve to one label

        findings.append({
            "check": CHECK_NAME, "dataset": title.split("_")[0], "path": f"mia_annotation issue {url}",
            "field": "issue_no_matching_label",
            "actual": title,
            "expected": "a real label directory matching this title on disk",
            "severity": "error",
            "suggested_fix": "the dataset/crop/label this issue tracks may have been renamed or removed -- verify and update or close the issue",
        })

    return findings, format_mismatch_keys


def check_labels(canonical: dict, terminal_titles: set, format_mismatch_keys: set, root: Path):
    """Forward direction: every real label should have a tracking issue."""
    findings = []
    for title, label_dir in canonical.items():
        if title in terminal_titles:
            continue

        dataset_name = label_dir.parents[2].name
        if (dataset_name, label_dir.name) in format_mismatch_keys:
            continue  # tracked, just under the old title format -- already reported on the issue side

        rel = str(label_dir.relative_to(root))
        if _SNAPSHOT_RE.search(title):
            findings.append({
                "check": CHECK_NAME, "dataset": dataset_name, "path": rel,
                "field": "untracked_snapshot",
                "actual": "no mia_annotation issue references this label",
                "expected": "expected for a superseded snapshot in a weekly-export series (informational)",
                "severity": "warning",
                "suggested_fix": "no action needed unless this snapshot should have its own issue",
            })
        else:
            findings.append({
                "check": CHECK_NAME, "dataset": dataset_name, "path": rel,
                "field": "untracked_label",
                "actual": "no mia_annotation issue references this label",
                "expected": "a mia_annotation issue tracking this label",
                "severity": "error",
                "suggested_fix": "create a mia_annotation issue for this label (not automated -- flag only)",
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

    canonical = build_canonical_index(root)
    items = fetch_project_items(MIA_ANNOTATION_PROJECT["owner"], MIA_ANNOTATION_PROJECT["number"])
    terminal_items = [i for i in items if i.get("status") in TERMINAL_STATUSES]
    terminal_titles = {i.get("title") for i in terminal_items}

    issue_findings, format_mismatch_keys = check_issues(terminal_items, canonical, root)
    label_findings = check_labels(canonical, terminal_titles, format_mismatch_keys, root)
    findings = issue_findings + label_findings

    run_date = datetime.date.today().isoformat()
    write_check_report(CHECK_NAME, findings, reports_dir=Path(args.reports_dir), date=run_date)

    print(f"{CHECK_NAME}: {len(findings)} finding(s) across {len(canonical)} real label(s) "
          f"and {len(terminal_items)} terminal mia_annotation issue(s)")
    if findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
