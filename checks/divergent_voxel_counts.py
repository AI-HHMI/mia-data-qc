#!/usr/bin/env python3
"""Check: for every crop with 2+ labels of the *same* `label_class` but
*different* `provenance` (both read from each label's own metadata, not
assumed from the directory name) that also cover a *comparable physical
extent* (see EXTENT_RATIO_THRESHOLD below), compute each label's exact
non-zero voxel count and flag any pair that disagrees by more than 10x.
This is the automated version of the check that caught a real bug by hand:
Jiefu's two labels on one crop disagreeing 1.1 vs 310.6 Gvox, a
`gt_subboxes.json`-mistaken-for-`gt_regions.json` substitution bug -- two
labels that were *supposed* to cover the identical declared region ending
up with wildly different content because the wrong file's data landed in
one of them.

Extent-comparability precondition added Oct 20 2026, after every one of 6
real findings this check ever produced on this corpus turned out to be a
region-size mismatch, not a content bug: `exm-mouse-liconn-DG-.../crop-001`'s
`auto_pred-cell-LSD_snapshot_10142026` (a small sub-region snapshot of an
independent prediction pipeline) vs. its `manual_gt-cell-snap_*` siblings
(full-dataset-wide coverage, the legacy same-shape-as-raw pattern) -- a
23x extent ratio; and `exm-mouse-liconn-ExPID82-1/crop-002_sub`'s
`manual_gt-cell-agglom-JJ-paintera` (JJ's own notes: a "restricted"
hand-proofread patch) vs. `proofread-cell-agglom-*` (the full comprehensive
volume) -- a 975x extent ratio. Both are two independent, parallel
annotation efforts on the same raw crop (different tools/people/scope), not
two takes on the same target -- comparing raw voxel counts between
regions of such wildly different size was never a fair test, regardless of
provenance. Physical volume (shape x scale on spatial axes, not raw voxel
count, since cross-provenance pairs can also sit at different resolutions
-- see voxel_size.py's independent_resolution case) must be within
EXTENT_RATIO_THRESHOLD of each other before a pair is even considered;
real same-target pairs (e.g. ExPID82-1's own `proofread-cell-agglom-v20240123`
vs `-dense-v20240123`, identical shape) have a ratio of 1.0, nowhere near
either real case's 23x/975x, so a generous-but-real threshold cleanly
separates them without needing to be tuned close to either false positive.

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
the original Jiefu case.

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
`measure_labels.py` uses, so this stays affordable even on a label
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
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.report import write_check_report
from common.vocab import NON_DATASET_DIRS
from common.voxel_count import exact_nonzero_count
from common.zarr_meta import get_multiscale, read_array_meta, read_group_attrs

CHECK_NAME = "divergent_voxel_counts"
RATIO_THRESHOLD = 10.0

# How close two labels' physical ranges must be, per spatial axis, to be
# considered "the same declared region" -- a generous 5% relative tolerance
# (plus a small absolute floor) absorbs legitimate voxel-rounding/pixel-center
# differences between pipelines without accepting a genuinely different
# region. Real false positives on this corpus are 20-1000x off, nowhere near
# this threshold.
RANGE_REL_TOL = 0.05


def _spatial_range(label_dir: Path):
    """{axis_name: (start_nm, end_nm)} for a label's own s0 level, from its
    real shape + scale + translation -- not the (often absent/empty)
    `bbox` metadata field, which isn't populated on every label (e.g. the
    legacy same-shape-as-raw labels on this corpus carry no bbox at all).
    """
    attrs = read_group_attrs(label_dir)
    ms = get_multiscale(attrs)
    if ms is None:
        return None
    axes = ms.get("axes", [])
    datasets = ms.get("datasets", [])
    if not axes or not datasets:
        return None
    cts = datasets[0].get("coordinateTransformations", [])
    scale = next((ct["scale"] for ct in cts if ct["type"] == "scale"), None)
    translation = next((ct["translation"] for ct in cts if ct["type"] == "translation"), None)
    if scale is None:
        return None
    if translation is None:
        translation = [0.0] * len(scale)
    array_meta = read_array_meta(label_dir / datasets[0].get("path", "s0"))
    if array_meta is None or array_meta["shape"] is None:
        return None
    shape = array_meta["shape"]
    if len(shape) != len(axes):
        return None
    ranges = {}
    for ax, sh, sc, tr in zip(axes, shape, scale, translation):
        if ax.get("type") != "space":
            continue
        start = tr
        end = tr + sh * sc
        ranges[ax["name"]] = (start, end)
    return ranges


def _ranges_match(a: dict, b: dict) -> bool:
    common = set(a) & set(b)
    if not common or common != set(a) or common != set(b):
        return False  # different axis sets entirely -- not the same kind of region
    for axis in common:
        (a_start, a_end), (b_start, b_end) = a[axis], b[axis]
        extent = max(a_end - a_start, b_end - b_start, 1.0)
        tol = max(extent * RANGE_REL_TOL, 1.0)
        if abs(a_start - b_start) > tol or abs(a_end - b_end) > tol:
            return False
    return True


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
    provenance = {d: (read_group_attrs(d) or {}).get("provenance") for d in label_dirs}
    ranges = {d: _spatial_range(d) for d in label_dirs}

    # Only a pair with different provenance AND the same declared physical
    # region is even a candidate -- determine this from cheap metadata alone
    # before ever decoding pixel data, same spirit as the same-provenance
    # skip above (and the same real efficiency win: a group with no
    # comparable pair at all never touches exact_nonzero_count).
    comparable_pairs = []
    dirs = sorted(label_dirs)
    for i in range(len(dirs)):
        for j in range(i + 1, len(dirs)):
            a, b = dirs[i], dirs[j]
            if provenance[a] == provenance[b]:
                continue
            if ranges[a] is None or ranges[b] is None or not _ranges_match(ranges[a], ranges[b]):
                continue
            comparable_pairs.append((a, b))
    if not comparable_pairs:
        return []

    needed = {d for pair in comparable_pairs for d in pair}
    counts = {}
    for label_dir in needed:
        s0 = label_dir / "s0"
        if not s0.is_dir():
            continue
        n = exact_nonzero_count(s0)
        if n is not None:
            counts[label_dir] = n

    findings = []
    for a, b in comparable_pairs:
        if a not in counts or b not in counts:
            continue
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
