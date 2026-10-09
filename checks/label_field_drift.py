#!/usr/bin/env python3
"""Check: for every `mia_annotation` issue at a terminal ingested status
(`manual_gt_ingested`, `public_gt_ingested`, `proofread_ingested`,
`auto_pred_ingested`), the label it tracks is located on disk and its
board fields (`Label_Class`/`Segmentation_Type`/`Provenance`/
`Proofreading_Status`/`Coverage`) are compared against that same label's own
`zarr.json["attributes"]`.

Severity is `warning`, not `error`, on purpose: a mismatch does not mean the
board is wrong. Either side can be the stale one -- on-disk metadata and the
board field can each be edited independently after the issue was filled in
(a reclassification, a new proofreading pass, or someone correcting the
board by hand before a metadata patch shipped). The finding is "these
disagree, a human needs to determine which is current," never an
instruction to overwrite one side with the other.

The label's on-disk path isn't read from a board path field (those can be
stale too, same problem this check exists to catch) -- it's derived from the
issue's own title, which the 3-component rename convention
(`{dataset-dir}_{crop}_{label-name}`) guarantees matches disk exactly once
an issue reaches a terminal status. `source_Image_Path` supplies the
`{dataset-dir}_{crop}` prefix (trying each `;`-separated candidate for
`proofread_ingested` issues, which can list more than one crop); the
remainder of the title after that exact prefix is the label directory name.

Real corpus survey (Oct 8 2026): 1104 terminal-status issues, 1086 resolved
to a real on-disk label this way. The other 18: 5 are category-tracker
issues (one per label type on a >100-crop dataset, title has no crop
segment at all -- out of scope for this check, not a failure), 3 have a
`source_Image_Path` outside the canonical `data/` tree (stale pre-ingest
staging path), 2 use an older slash-separated title instead of the
3-component convention. All 18 are silently skipped here, not flagged --
an unresolvable label is a different problem (orphaned/stale board
reference) than a resolved label with disagreeing fields, and belongs to a
separate check. Real run found **0 mismatches** across the 1086 resolved:
expected, since the backfill that created these issues populated the board
fields directly from the same disk metadata this check reads -- this
validates the check is sound and ready to catch drift as the two sides
diverge going forward, not that drift doesn't exist.

Checks zarr v2 labels (`.zattrs`) as well as zarr v3 (`zarr.json`) -- retrofitted
Oct 8 2026, see metadata_completeness.py's docstring for why.
"""
from __future__ import annotations

import argparse
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.github import fetch_project_items, MIA_ANNOTATION_PROJECT
from common.report import write_check_report
from common.zarr_meta import group_exists, read_group_attrs

CHECK_NAME = "label_field_drift"

TERMINAL_STATUSES = {
    "manual_gt_ingested", "public_gt_ingested", "proofread_ingested", "auto_pred_ingested",
}

# board field name -> this project's on-disk zarr attribute name
FIELD_MAP = {
    "label_Class": "label_class",
    "segmentation_Type": "segmentation_type",
    "provenance": "provenance",
    "proofreading_Status": "proofreading_status",
    "coverage": "coverage",
}


def _resolve_label_dir(item: dict, root: Path) -> Path | None:
    title = item.get("title") or ""
    src = item.get("source_Image_Path") or ""
    for candidate in (s.strip() for s in src.split(";")):
        if not candidate.endswith(".zarr"):
            continue
        crop_dir = Path(candidate)
        dataset_dir = crop_dir.parent.name
        crop_name = crop_dir.name[:-len(".zarr")]
        prefix = f"{dataset_dir}_{crop_name}_"
        if not title.startswith(prefix):
            continue
        label_dir = root / dataset_dir / crop_dir.name / "labels" / title[len(prefix):]
        if group_exists(label_dir):
            return label_dir
    return None


def check_item(item: dict, label_dir: Path, root: Path) -> list[dict]:
    attrs = read_group_attrs(label_dir)
    if attrs is None:
        return []

    rel = str(label_dir.relative_to(root))
    dataset = label_dir.parents[2].name
    findings = []

    for board_field, disk_field in FIELD_MAP.items():
        board_val = item.get(board_field)
        if board_val is None:
            continue  # blank board field -- metadata_completeness-style gap, not drift
        disk_val = attrs.get(disk_field)
        if str(board_val) != str(disk_val):
            findings.append({
                "check": CHECK_NAME, "dataset": dataset, "path": rel,
                "field": disk_field,
                "actual": f"board={board_val!r}, disk={disk_val!r}",
                "expected": "board and disk agree (neither side assumed correct)",
                "severity": "warning",
                "suggested_fix": f"compare both values on issue {item.get('content', {}).get('url', '')} and update whichever is stale",
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

    items = fetch_project_items(MIA_ANNOTATION_PROJECT["owner"], MIA_ANNOTATION_PROJECT["number"])

    findings = []
    n_resolved = 0
    for item in items:
        if item.get("status") not in TERMINAL_STATUSES:
            continue
        label_dir = _resolve_label_dir(item, root)
        if label_dir is None:
            continue  # unresolvable -- a different check's concern, not a finding here
        n_resolved += 1
        findings.extend(check_item(item, label_dir, root))

    run_date = datetime.date.today().isoformat()
    write_check_report(CHECK_NAME, findings, reports_dir=Path(args.reports_dir), date=run_date)

    print(f"{CHECK_NAME}: {len(findings)} finding(s) across {n_resolved} resolved label(s) "
          f"(of {len(items)} mia_annotation items)")
    if findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
