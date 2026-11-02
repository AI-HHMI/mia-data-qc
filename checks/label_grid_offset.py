#!/usr/bin/env python3
"""Check: every label's s0 translation carries the half-voxel grid offset
relative to its crop's raw, not just the pyramid shift
(`lmvd_structure_guideline.md` §21, found Oct 13 2026 by Emin Orhan on
`em-zebrafish-fish2`).

Coordinates in this corpus are voxel centres: raw s0 voxel 0 is centred at 0
(no translation). A label stored at a *different* voxel size than raw does
not start at 0 either -- its voxel 0 covers (or is covered by) part of a raw
voxel, so its centre sits `(label_scale - raw_scale)/2` away from raw voxel
0, per axis, on top of whatever sub-region origin shift the label also has
(the "no, I have a cute corpus" layout). Writing only the sub-region shift
or only the pyramid shift leaves the whole label displaced from the image by
a constant at every level, and nothing else catches this -- shapes, scales
and extents all look correct.

Rule, applied per spatial axis the label shares with raw:
`(label_s0_translation - raw_s0_translation - (label_s0_scale - raw_s0_scale) / 2) / raw_s0_scale`
must be a whole number (within 1e-3) -- zero for a label covering the full
raw crop, a non-zero whole number for a sub-region, negative for a
finer-than-raw label. This degenerates correctly to a plain sub-region-origin
check when label and raw share the same scale (the offset term is then 0),
so every spatial axis is checked uniformly with one formula, not just axes
where the scale actually differs.

This assumes the label's voxel edges sit on raw's voxel edges, true when the
label is a block-downsample of the same region (label shape = raw shape /
ratio, same bbox origin) -- a label produced on an independent grid needs its
offset *measured*, not derived from this formula; it would show up here as a
false `grid_offset_error` and needs a human to recognize that case, not a
code exception (see the `independent_resolution` skip below for the one
lifecycle state that's already a real metadata flag, not a guess).

Axis matching is by **name**, not position -- found necessary (not just
theoretical) for the 38 LICONN labels (DG/cortex/hippocampus) whose axes are
ordered differently from their raw. A label whose spatial axis *name set*
doesn't match raw's at all can't be aligned by this formula regardless of
order -- reported separately as `grid_offset_not_checkable` (warning), not
silently skipped and not treated as a pass.

A crop with no local `raw/` group (and no multiscale at its own root either)
is also `grid_offset_not_checkable` (warning), not a pass -- this corpus has
118 such crops (Betzig tile crops, FlyLICONN `normalized`/`raw`, Thayer)
whose real raw lives in a *different* crop or dataset; checking them needs a
raw-lookup table that doesn't exist yet. Listing them as not-checkable keeps
them visible as a known gap rather than silently counting as clean.

A label carrying `independent_resolution: true` is skipped entirely, same
flag and same reasoning as `voxel_size.py` -- a label deliberately kept at
its own native resolution, never resampled onto raw's grid at all, isn't a
grid-offset bug by definition.

Flag-only, matching this project's standing Phase 2 policy: no finding here
is auto-fixed. The existing one-off script, `scripts/lmvd/fix_label_grid_offset.py`
(dry run by default, idempotent -- reuses this exact formula), is the
suggested remediation, but a sample should be verified by hand before any
batch run, same discipline as every other fix on this corpus.

Checks zarr v2 crops/labels (`.zattrs`) as well as zarr v3 (`zarr.json`) via
`common.zarr_meta`, consistent with every other check here.

Real corpus history: the one-off survey (Oct 13 2026, 1,145 label/raw pairs)
found and fixed 70 arrays across 9 datasets before this check existed.
"""
import argparse
import datetime
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.report import write_check_report
from common.vocab import NON_DATASET_DIRS
from common.zarr_meta import get_multiscale, read_group_attrs

CHECK_NAME = "label_grid_offset"
REL_TOL = 1e-3


def _s0_scale_translation(ms: dict) -> dict:
    """{axis_name: (scale, translation)} for only the spatial axes of s0."""
    axes = ms.get("axes", [])
    try:
        cts = ms["datasets"][0]["coordinateTransformations"]
    except (KeyError, IndexError):
        return {}
    scale = next((c["scale"] for c in cts if c["type"] == "scale"), None)
    if scale is None:
        return {}
    translation = next((c["translation"] for c in cts if c["type"] == "translation"), [0.0] * len(scale))
    return {
        ax["name"]: (sc, tr)
        for ax, sc, tr in zip(axes, scale, translation)
        if ax.get("type") == "space"
    }


def check_crop(crop_dir: Path, root: Path, dataset: str) -> list[dict]:
    findings = []

    labels_dir = crop_dir / "labels"
    if not labels_dir.is_dir():
        return findings

    raw_dir = crop_dir / "raw" if (crop_dir / "raw").is_dir() else crop_dir
    raw_ms = get_multiscale(read_group_attrs(raw_dir))
    raw_st = _s0_scale_translation(raw_ms) if raw_ms is not None else {}
    if not raw_st:
        findings.append({
            "check": CHECK_NAME,
            "dataset": dataset,
            "path": str(crop_dir.relative_to(root)),
            "field": "grid_offset_not_checkable",
            "actual": "no local raw group with spatial voxel-size metadata found in this crop",
            "expected": "a local raw group to compare every label's grid offset against",
            "severity": "warning",
            "suggested_fix": (
                "this crop's real raw image likely lives in a different crop/dataset -- needs a "
                "raw-lookup table before grid offset can be checked here; see "
                "lmvd_quality_control.md's 2026-10-30 entry"
            ),
        })
        return findings

    for label_dir in sorted(p for p in labels_dir.iterdir() if p.is_dir()):
        label_attrs = read_group_attrs(label_dir)
        if label_attrs is not None and label_attrs.get("independent_resolution"):
            continue  # deliberately never resampled onto raw's grid -- not this check's concern

        label_ms = get_multiscale(label_attrs)
        if label_ms is None:
            continue
        label_st = _s0_scale_translation(label_ms)
        if not label_st:
            continue

        if set(label_st) != set(raw_st):
            findings.append({
                "check": CHECK_NAME,
                "dataset": dataset,
                "path": str(label_dir.relative_to(root)),
                "field": "grid_offset_not_checkable",
                "actual": f"label spatial axes {sorted(label_st)} vs raw spatial axes {sorted(raw_st)}",
                "expected": "the same spatial axis names as raw (any order)",
                "severity": "warning",
                "suggested_fix": (
                    "this label's axis names don't match raw's at all -- its offset needs to be "
                    "measured directly, not derived from this check's formula (lmvd_structure_guideline.md §21)"
                ),
            })
            continue

        bad_axes = {}
        for axis, (ls, lt) in label_st.items():
            rs, rt = raw_st[axis]
            if rs == 0:
                continue
            offset = (ls - rs) / 2
            voxels = (lt - rt - offset) / rs
            if abs(voxels - round(voxels)) > REL_TOL:
                bad_axes[axis] = {
                    "raw_scale": rs, "raw_translation": rt,
                    "label_scale": ls, "label_translation": lt,
                    "computed_voxel_offset": voxels,
                }
        if bad_axes:
            findings.append({
                "check": CHECK_NAME,
                "dataset": dataset,
                "path": str(label_dir.relative_to(root)),
                "field": "grid_offset_error",
                "actual": bad_axes,
                "expected": (
                    "(label_translation - raw_translation - (label_scale - raw_scale)/2) / raw_scale "
                    "must be a whole number on every axis"
                ),
                "severity": "error",
                "suggested_fix": (
                    "run scripts/lmvd/fix_label_grid_offset.py (dry run first, verify by hand before "
                    "--apply) -- or, if this is a genuine independent-grid label, confirm and set "
                    "independent_resolution: true instead of fixing"
                ),
            })

    return findings


def iter_crops(root: Path):
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
    for dataset_name, crop_dir in iter_crops(root):
        n_crops += 1
        findings.extend(check_crop(crop_dir, root, dataset_name))

    run_date = datetime.date.today().isoformat()
    write_check_report(CHECK_NAME, findings, reports_dir=Path(args.reports_dir), date=run_date)

    print(f"{CHECK_NAME}: {len(findings)} finding(s) across {n_crops} crop(s) under {root}")
    if findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
