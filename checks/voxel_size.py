#!/usr/bin/env python3
"""Check: (1) raw's voxel size isn't a placeholder (all spatial axes exactly
1.0 -- the documented Betzig incident, metadata sat at [1,1,1,1,1] nm instead
of the real value for months), and (2) each label's own declared voxel size,
axis by axis, matches some real resolution raw's own pyramid actually has for
that axis -- not necessarily all axes from the identical raw level (confirmed
on real data: H01's auto_pred-cell-c2_seg is [8,8,33] nm, matching raw's s1
exactly, not s0's [4,4,33], an identical-level match; but a genuinely
anisotropic label can validly mix axes from *different* raw levels -- see
below). A label axis matching *no* real raw value at all, on any level, is the
real FlyLICONN-style bug (#19, two separate incidents): a voxel size that
doesn't correspond to any real resolution at all.

Per-axis (not same-level) matching added Oct 20 2026, after investigating 15
real `voxel_size_mismatch` findings across 4 datasets (FANC-vnc, banc,
PYR-ca3-hippocampus, fish2) that turned out not to be bugs: TensorSwitch's
anisotropic pyramid rule (skip downsampling an axis once it's already >=2x
coarser than the others, until the ratio closes, only then downsample all
axes together -- `v2_downsampling_explained.md`) is applied independently
starting from each array's *own* native resolution. raw and a label built
from an already-downsampled input (e.g. a nucleus-detection network fed
XY-downsampled-but-Z-untouched data for speed) each hit their own
anisotropic-skip point at a different place, so the label's per-axis values
land on a different level index than raw's -- even though every individual
axis value is still real (confirmed via each array's own stored shape, not
just its declared scale: e.g. FANC-vnc's label has real Z=45nm data at a
genuinely-downsampled-to-level-4 XY resolution raw itself never materialized
in that exact combination). Requiring one shared level index for every axis
was stricter than reality -- fixed to match each axis independently against
the full set of real per-axis values anywhere in raw's own pyramid.

A label carrying its own `independent_resolution: true` is skipped entirely
-- added Oct 20 2026 for a separate, genuinely different real case: a label
that's deliberately *never* resampled onto raw's grid at all (not even
per-axis), because it's a not-yet-finalized stage of a prediction/proofreading
lifecycle (a raw segmentation-pipeline prediction, or a one-off "let me look
at progress" snapshot of an in-progress Paintera session) kept at its own
native acquisition resolution x this dataset's real expansion factor -- found
on 4 real labels (`em-mouse-liconn-DG/cortex/hippocampus`'s
`auto_pred-cell-LSD_snapshot_10142026`, FlyID49's
`auto_pred-neuron-LSD_sws_b4_msd20`) that all reduce to ~9nm native resolution
when divided by their own stated `expansion_microscopy.expansion_factor`, but
have no relationship to raw's pyramid at all since raw was never resampled
*from* that same native resolution either. Confirmed visually aligned in
Neuroglancer -- genuinely correct data, just outside what this check was ever
meant to validate. Deliberately a real metadata field (not a hardcoded
per-label exception list) so any future label of this same kind self-declares
it at ingest time instead of requiring another QC investigation -- the same
lifecycle-aware reasoning as `freshness.py`'s superseded-snapshot tracking:
expect this flag to come off (or the label to be superseded) once a final,
grid-resampled `manual_gt` export replaces it.

Same no-raw-subgroup layout handling as pyramid_consistency.py: some crops
keep pyramid levels directly under the crop root with no raw/ subgroup.

Checks zarr v2 crops/labels (`.zattrs`) as well as zarr v3 (`zarr.json`) --
retrofitted Oct 8 2026, see metadata_completeness.py's docstring for why.
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

CHECK_NAME = "voxel_size"


def _spatial_scale(multiscales_entry: dict, level_index: int) -> dict:
    """{axis_name: scale} for only the spatial axes of one pyramid level."""
    axes = multiscales_entry.get("axes", [])
    try:
        scale = multiscales_entry["datasets"][level_index]["coordinateTransformations"][0]["scale"]
    except (KeyError, IndexError):
        return {}
    return {ax["name"]: s for ax, s in zip(axes, scale) if ax.get("type") == "space"}


def _load_multiscales(group_dir: Path):
    return get_multiscale(read_group_attrs(group_dir))


def _per_axis_values(levels: list) -> dict:
    """{axis_name: set of every real scale value that axis takes across all
    given levels} -- the pool of individually-real values a label's own axis
    can be checked against, independent of which level index each came from.
    """
    values = {}
    for level in levels:
        for axis, v in level.items():
            values.setdefault(axis, set()).add(v)
    return values

def _axis_matches(value: float, candidates: set, rel_tol: float = 1e-6) -> bool:
    return any(math.isclose(value, c, rel_tol=rel_tol) for c in candidates)


def check_crop(crop_dir: Path, root: Path, dataset: str) -> list[dict]:
    findings = []

    raw_dir = crop_dir / "raw" if (crop_dir / "raw").is_dir() else crop_dir
    raw_ms = _load_multiscales(raw_dir)
    if raw_ms is None:
        return findings

    raw_levels = [_spatial_scale(raw_ms, i) for i in range(len(raw_ms.get("datasets", [])))]

    # A label can legitimately sit at a finer level than raw's own s0 that was
    # never materialized on disk -- confirmed on real CellMap source data
    # (jrc_fly-mb-1a's official groundtruth crops are natively 2nm, half of
    # the released full-volume EM pyramid's 4nm s0). Extrapolate one virtual
    # finer level using raw's own s0->s1 per-axis ratio and allow it as a
    # match too, rather than only ever matching materialized levels.
    if len(raw_levels) >= 2 and raw_levels[0] and raw_levels[1]:
        s0_, s1_ = raw_levels[0], raw_levels[1]
        common = set(s0_) & set(s1_)
        if common and all(s1_[k] != 0 for k in common):
            virtual_finer = {k: s0_[k] * s0_[k] / s1_[k] for k in common}
            raw_levels = raw_levels + [virtual_finer]

    s0 = raw_levels[0] if raw_levels else {}
    if s0 and all(math.isclose(v, 1.0, rel_tol=1e-9) for v in s0.values()):
        findings.append({
            "check": CHECK_NAME,
            "dataset": dataset,
            "path": str(raw_dir.relative_to(root)),
            "field": "voxel_size_placeholder",
            "actual": s0,
            "expected": "a real, non-1.0 voxel size",
            "severity": "error",
            "suggested_fix": "patch coordinateTransformations with the real voxel size",
        })

    raw_axis_values = _per_axis_values(raw_levels)

    labels_dir = crop_dir / "labels"
    if not labels_dir.is_dir():
        return findings

    for label_dir in sorted(p for p in labels_dir.iterdir() if p.is_dir()):
        label_attrs = read_group_attrs(label_dir)
        if label_attrs is not None and label_attrs.get("independent_resolution"):
            continue  # explicitly not resampled onto raw's grid -- not this check's concern
        label_ms = get_multiscale(label_attrs)
        if label_ms is None:
            continue
        label_s0 = _spatial_scale(label_ms, 0)
        if not label_s0:
            continue
        bad_axes = {
            axis: v for axis, v in label_s0.items()
            if axis not in raw_axis_values or not _axis_matches(v, raw_axis_values[axis])
        }
        if bad_axes:
            findings.append({
                "check": CHECK_NAME,
                "dataset": dataset,
                "path": str(label_dir.relative_to(root)),
                "field": "voxel_size_mismatch",
                "actual": label_s0,
                "expected": f"every axis matching a real raw value: {raw_axis_values}",
                "severity": "error",
                "suggested_fix": (
                    f"axis/axes {sorted(bad_axes)} don't match any real resolution raw's own "
                    "pyramid has for that axis at all -- verify against the original source "
                    "whether this label's declared voxel size is simply wrong (the documented "
                    "FlyLICONN-style bug class), not just on a different pyramid level than raw"
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
