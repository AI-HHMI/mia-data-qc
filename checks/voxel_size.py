#!/usr/bin/env python3
"""Check: (1) raw's voxel size isn't a placeholder (all spatial axes exactly
1.0 -- the documented Betzig incident, metadata sat at [1,1,1,1,1] nm instead
of the real value for months), and (2) each label's own declared voxel size
matches one of raw's actual pyramid levels (not necessarily raw's finest level
-- a label can legitimately be computed at a coarser resolution than raw's s0,
confirmed on real data: H01's auto_pred-cells-c2_seg is [8,8,33] nm, matching
raw's s1 exactly, not s0's [4,4,33]). A label's scale matching *none* of raw's
levels is the real FlyLICONN-style bug (#19, two separate incidents): a voxel
size that doesn't correspond to any real resolution at all.

Same no-raw-subgroup layout handling as pyramid_consistency.py: some crops
keep pyramid levels directly under the crop root with no raw/ subgroup.
"""
import argparse
import datetime
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.report import write_check_report
from common.vocab import NON_DATASET_DIRS

CHECK_NAME = "voxel_size"


def _spatial_scale(multiscales_entry: dict, level_index: int) -> dict:
    """{axis_name: scale} for only the spatial axes of one pyramid level."""
    axes = multiscales_entry.get("axes", [])
    try:
        scale = multiscales_entry["datasets"][level_index]["coordinateTransformations"][0]["scale"]
    except (KeyError, IndexError):
        return {}
    return {ax["name"]: s for ax, s in zip(axes, scale) if ax.get("type") == "space"}


def _load_multiscales(zarr_json_path: Path):
    try:
        data = json.loads(zarr_json_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    multiscales = data.get("attributes", {}).get("ome", {}).get("multiscales")
    return multiscales[0] if multiscales else None


def _matches(a: dict, b: dict, rel_tol: float = 1e-6) -> bool:
    if not a or not b:
        return False
    common = set(a) & set(b)
    if not common:
        return False
    return all(math.isclose(a[k], b[k], rel_tol=rel_tol) for k in common)


def check_crop(crop_dir: Path, root: Path, dataset: str) -> list[dict]:
    findings = []

    raw_zj = crop_dir / "raw" / "zarr.json" if (crop_dir / "raw").is_dir() else crop_dir / "zarr.json"
    raw_ms = _load_multiscales(raw_zj)
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
            "path": str(raw_zj.relative_to(root)),
            "field": "voxel_size_placeholder",
            "actual": s0,
            "expected": "a real, non-1.0 voxel size",
            "severity": "error",
            "suggested_fix": "patch coordinateTransformations with the real voxel size",
        })

    labels_dir = crop_dir / "labels"
    if not labels_dir.is_dir():
        return findings

    for label_dir in sorted(p for p in labels_dir.iterdir() if p.is_dir()):
        label_zj = label_dir / "zarr.json"
        label_ms = _load_multiscales(label_zj)
        if label_ms is None:
            continue
        label_s0 = _spatial_scale(label_ms, 0)
        if not label_s0:
            continue
        if not any(_matches(label_s0, raw_level) for raw_level in raw_levels):
            findings.append({
                "check": CHECK_NAME,
                "dataset": dataset,
                "path": str(label_zj.relative_to(root)),
                "field": "voxel_size_mismatch",
                "actual": label_s0,
                "expected": f"one of raw's pyramid levels: {raw_levels}",
                "severity": "error",
                "suggested_fix": (
                    "doesn't align with raw's pyramid on a consistent per-axis basis -- verify "
                    "against the original source whether this label's declared voxel size is "
                    "wrong, or different axes are drifting onto different pyramid levels "
                    "(the documented anisotropic-mismatch bug class)"
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
