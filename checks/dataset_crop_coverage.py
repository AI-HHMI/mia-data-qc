#!/usr/bin/env python3
"""Check: every real crop in a *multi-crop* dataset has some `mia_pretraining`
representation -- either its own crop-specific issue, or a dataset-level
issue covering the whole dataset (one `HHMI_Path` with no specific crop
named, which `mia_pretraining` issues routinely use -- see
dataset_orphaned_ingest.py). A dataset with a blanket dataset-level issue
is never flagged here regardless of its crops -- that's exactly the
granularity dataset_orphaned_ingest.py already validates. This check only
fires for a multi-crop dataset tracked *entirely* through per-crop issues,
where one crop can silently have no issue at all while its siblings do.

Found as a TODO while building dataset_field_drift.py (Oct 12 2026), logged
as a separate follow-up, not folded into that check. The
`label_orphaned_ingest.py` pattern, one level finer for the
`mia_pretraining` side.

Resolution reuses dataset_orphaned_ingest.py's path-handling (strip a
trailing parenthetical/ellipsis annotation, treat `.../crop-NNN.zarr/raw`
as naming that crop) but keeps the crop name instead of collapsing to just
the dataset -- a path with no specific crop component (a bare dataset dir,
or dataset-level prose like "(198 crops: ...)") is treated as a blanket
dataset-level issue, same as that check's own resolver effectively does.

Real corpus survey (Oct 14 2026): 52 multi-crop real datasets. 51 have at
least one dataset-level blanket issue, so aren't this check's concern.
Exactly 1 does not -- `em-zebrafish-fish2` (6 real crops, only 1 named by
any issue, 5 missing) -- already independently flagged by `voxel_size.py`
(anisotropic voxel-size bug) and `bbox_sanity.py` (lowercase
`coordinate_order`) as a genuinely non-standard ingestion pipeline, so this
fits an established pattern on this one dataset, not new noise.
"""
import argparse
import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.github import fetch_project_items, MIA_PRETRAINING_PROJECT
from common.report import write_check_report
from common.vocab import NON_DATASET_DIRS
from common.zarr_meta import group_exists

CHECK_NAME = "dataset_crop_coverage"


def find_real_crops(root: Path) -> dict:
    """{dataset_name: [real crop dir names]} for every dataset with 2+ real crops."""
    real = {}
    for p in sorted(root.iterdir()):
        if not p.is_dir() or p.name in NON_DATASET_DIRS:
            continue
        crops = sorted(
            c.name for c in p.iterdir()
            if c.is_dir() and c.name.endswith(".zarr") and group_exists(c)
        )
        if len(crops) > 1:
            real[p.name] = crops
    return real


def _strip_prose(s: str) -> str:
    for sep in (" (", " …"):
        idx = s.find(sep)
        if idx != -1:
            s = s[:idx]
    return s.strip()


def resolve_dataset_and_crop(candidate: str, root: Path):
    """Return (dataset_name, crop_name_or_None). crop_name is None for a
    bare dataset-level path (or one followed only by prose, e.g. "(198
    crops: ...)") -- such a path is a blanket issue for the whole dataset.
    """
    p = Path(_strip_prose(candidate))
    crop_p = None
    if p.name == "raw" and p.parent.name.endswith(".zarr"):
        crop_p = p.parent
    elif p.name.endswith(".zarr"):
        crop_p = p
    try:
        rel = p.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return None, None
    dataset = rel.parts[0] if rel.parts else None
    crop = crop_p.name if crop_p else None
    return dataset, crop


def find_coverage(items: list, root: Path, real_crops: dict):
    """Return (dataset_level: set, crop_level: {dataset: set(crop names)})."""
    dataset_level = set()
    crop_level = {}
    for item in items:
        if item.get("content", {}).get("repository") != "AI-HHMI/mia_pretraining":
            continue
        hp = item.get("hHMI_Path")
        if not hp:
            continue
        for candidate in (c.strip() for c in hp.split(";")):
            dataset, crop = resolve_dataset_and_crop(candidate, root)
            if not dataset or dataset not in real_crops:
                continue
            if crop:
                crop_level.setdefault(dataset, set()).add(crop)
            else:
                dataset_level.add(dataset)
    return dataset_level, crop_level


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="data", help="Directory to scan (default: data)")
    parser.add_argument("--reports-dir", default="reports", help="Where to write dated reports (default: reports)")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    real_crops = find_real_crops(root)
    items = fetch_project_items(MIA_PRETRAINING_PROJECT["owner"], MIA_PRETRAINING_PROJECT["number"])
    dataset_level, crop_level = find_coverage(items, root, real_crops)

    findings = []
    for dataset, crops in sorted(real_crops.items()):
        if dataset in dataset_level:
            continue
        covered = crop_level.get(dataset, set())
        for crop in crops:
            if crop in covered:
                continue
            findings.append({
                "check": CHECK_NAME, "dataset": dataset, "path": f"{dataset}/{crop}",
                "field": "untracked_crop",
                "actual": "no mia_pretraining issue (dataset-level or crop-specific) references this crop",
                "expected": "a mia_pretraining issue tracking this crop, or a dataset-level issue covering the whole dataset",
                "severity": "error",
                "suggested_fix": "create or extend a mia_pretraining issue to cover this crop (not automated -- flag only)",
            })

    run_date = datetime.date.today().isoformat()
    write_check_report(CHECK_NAME, findings, reports_dir=Path(args.reports_dir), date=run_date)

    print(f"{CHECK_NAME}: {len(findings)} finding(s) across {len(real_crops)} multi-crop real dataset(s)")
    if findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
