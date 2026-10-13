#!/usr/bin/env python3
"""Check: for every crop with 2+ labels of the *same* `label_class` but
*different* `provenance` (both read from each label's own metadata, not
assumed from the directory name), compute each label's exact non-zero
voxel count and flag any pair that disagrees by more than 10x. This is the
automated version of the check that caught a real bug by hand: Jiefu's two
labels on one crop disagreeing 1.1 vs 310.6 Gvox, a
`gt_subboxes.json`-mistaken-for-`gt_regions.json` substitution bug.

Requiring different provenance (not just the same `label_class`) was added
after the real corpus run showed why same-class/same-provenance isn't
comparable at all: CellMap's convention bundles many *spatially distinct*
sub-crops under one literal class token (`manual_gt-all_organelles-crop266`,
`...-crop267`, ... -- each number is a different physical sub-region, not
a reprocessing of the same one), and Hydra's `vesicle` class bundles
genuinely different biological sub-types (`public_gt-vesicle-CV`/`-DCV`/
`-DCVH`/`-SCV`/`-SDCV`). Both naturally and correctly disagree by orders of
magnitude -- that's not a bug, it's different regions/structures sharing a
coarse class name. Requiring different provenance keeps the comparison to
its real intended meaning: the *same* annotated target, produced two
different ways (e.g. `manual_gt` vs `proofread`) -- exactly the shape of
the original Jiefu case and the only real finding on this corpus.

Needs real pixel data, not just metadata -- the only check in this repo
that does. Uses `common/voxel_count.py` (needs `zarr`/`numpy`, see
`pixi.toml`; run this one via `pixi run python3`, not bare `python3`).
Exact counts are only attempted within each label's *written*-chunk
bounding box (`common.zarr_meta.written_chunk_bounds()`), never the full
declared shape -- zarr never writes an all-empty chunk, so a label's
declared shape routinely spans the whole parent volume while only a small
sub-box carries real annotation. Even so, a label is skipped (not
guessed at) if it's too large on disk (>2GB), too large decompressed
(>800GB), or spans too many chunks (>200K) -- the same three gates
Emin's `measure_labels.py` uses, so this stays affordable even on a label
whose declared shape is huge. A whole group is skipped before any exact
counting if every label in it shares one provenance (no cross-provenance
pair is even possible) -- this is what makes CellMap's 18-label
`all_organelles` groups cheap to pass over instead of wastefully counted.

A label with 0 non-zero voxels in a pair where its sibling has a real
positive count is flagged regardless of the 10x threshold (any ratio
against zero is undefined, and "one of these two is empty" is itself
worth a look).

Real corpus run (Oct 12 2026): first pass (same-class only, no provenance
filter) found 657 findings across 53 groups -- 655 were the
same-provenance false positives above (CellMap `all_organelles`, Hydra
`vesicle`), confirmed by checking each flagged pair's real `provenance`
metadata directly. After adding the provenance-difference requirement: 2
real findings remain, both the same underlying pair on
`exm-mouse-liconn-ExPID82-1/crop-002_sub.zarr` (`manual_gt-cell-agglom-
JJ-paintera` vs two `proofread-cell-agglom-*` siblings) -- a genuine
~944x disagreement (4.8M vs 4.57B non-zero voxels) worth a human looking
at, not explained away by any naming/format convention found so far.
"""
import argparse
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.report import write_check_report
from common.vocab import NON_DATASET_DIRS
from common.voxel_count import exact_nonzero_count
from common.zarr_meta import read_group_attrs

CHECK_NAME = "divergent_voxel_counts"
RATIO_THRESHOLD = 10.0


def parse_label_class(label_name: str):
    parts = label_name.split("-", 2)
    if len(parts) < 3 or not parts[1]:
        return None
    return parts[1]


def iter_crop_label_groups(root: Path):
    """Yield (dataset_name, crop_dir, label_class, [label_dirs]) for every
    crop where 2+ labels share the same parsed label_class AND at least two
    of them have different real `provenance` metadata -- a group where
    every label shares one provenance is skipped before any exact counting,
    since no cross-provenance pair is even possible."""
    for dataset_dir in sorted(p for p in root.iterdir() if p.is_dir() and p.name not in NON_DATASET_DIRS):
        for crop_dir in sorted(p for p in dataset_dir.iterdir() if p.is_dir() and p.name.endswith(".zarr")):
            labels_dir = crop_dir / "labels"
            if not labels_dir.is_dir():
                continue
            by_class = {}
            for label_dir in sorted(p for p in labels_dir.iterdir() if p.is_dir()):
                label_class = parse_label_class(label_dir.name)
                if label_class is None:
                    continue
                by_class.setdefault(label_class, []).append(label_dir)
            for label_class, label_dirs in by_class.items():
                if len(label_dirs) < 2:
                    continue
                provenances = {(read_group_attrs(d) or {}).get("provenance") for d in label_dirs}
                if len(provenances - {None}) >= 2:
                    yield dataset_dir.name, crop_dir, label_class, label_dirs


def check_group(dataset: str, crop_dir: Path, label_class: str, label_dirs: list, root: Path) -> list[dict]:
    counts = {}
    provenance = {}
    for label_dir in label_dirs:
        s0 = label_dir / "s0"
        if not s0.is_dir():
            continue
        n = exact_nonzero_count(s0)
        if n is not None:
            counts[label_dir] = n
            provenance[label_dir] = (read_group_attrs(label_dir) or {}).get("provenance")

    findings = []
    names = sorted(counts)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            if provenance[a] == provenance[b]:
                continue  # same provenance -- not a "same target, two takes" comparison
            ca, cb = counts[a], counts[b]
            lo, hi = sorted((ca, cb))
            divergent = (lo == 0 and hi > 0) or (lo > 0 and hi / lo > RATIO_THRESHOLD)
            if divergent:
                findings.append({
                    "check": CHECK_NAME, "dataset": dataset,
                    "path": f"{crop_dir.relative_to(root)}/labels ({label_class})",
                    "field": "divergent_voxel_count",
                    "actual": f"{a.name}={ca}, {b.name}={cb}",
                    "expected": f"non-zero voxel counts within {RATIO_THRESHOLD}x of each other",
                    "severity": "error",
                    "suggested_fix": "verify both labels annotate the same region -- a wrong source file/region substitution is a known real cause",
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
    n_groups = 0
    for dataset_name, crop_dir, label_class, label_dirs in iter_crop_label_groups(root):
        n_groups += 1
        findings.extend(check_group(dataset_name, crop_dir, label_class, label_dirs, root))
        print(f"  [{n_groups}] {crop_dir.relative_to(root)} ({label_class}, {len(label_dirs)} labels)", flush=True)

    run_date = datetime.date.today().isoformat()
    write_check_report(CHECK_NAME, findings, reports_dir=Path(args.reports_dir), date=run_date)

    print(f"{CHECK_NAME}: {len(findings)} finding(s) across {n_groups} cross-provenance label group(s) under {root}")
    if findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
