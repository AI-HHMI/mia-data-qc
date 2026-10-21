#!/usr/bin/env python3
"""Check: every real dataset directory under `data/` (one with at least one
real crop -- a `.tmp`-suffixed staging dir with only preview images doesn't
count) has at least one `mia_pretraining` issue whose `HHMI_Path` resolves
somewhere inside it. The `mia_pretraining`-side sibling of
`label_orphaned_ingest.py`, scoped to the *dataset* level on purpose
(Oct 12 2026) -- `mia_pretraining` issues routinely cover a whole multi-crop
dataset with one path, so per-crop coverage isn't the right granularity
here the way it is for `mia_annotation`'s per-label tracking.

Resolution, more forgiving than `dataset_field_drift.py`'s (that one needs
an exact crop to compare fields against; this one only needs to know which
*dataset* a path falls under): strips a trailing parenthetical/ellipsis
annotation some `HHMI_Path` values carry (`"... (198 crops: crop-001 ...
crop-198)"`), treats a path ending in `.../crop-NNN.zarr/raw` as naming that
crop's dataset, then takes the first path component relative to `--root`.
Only the forward direction is checked -- flagging *which* mia_pretraining
issues have an unresolvable `HHMI_Path` was considered and dropped: several
real entries intentionally point outside `data/` entirely (NISB's dev
fixtures), and this check has no way to tell that apart from a genuinely
stale reference using only `--root`-relative information, so guessing
either way risks a wrong call -- left to a human, or a narrower future
check if one is wanted.

Real corpus survey (Oct 12 2026): 139 directories under `data/` look like
datasets; 137 have at least one real crop (the other 2,
`exm-drosophila-flyliconn-FlyID30-mirrorscope-S5-20260326-unstitched.tmp`
and `...FlyID48-mirrorscope-20260630-unstitched.tmp`, hold only preview
images -- not-yet-ingested staging material, already tracked and documented
as on-hold on their own issues). All 137 real datasets resolve to
at least one `mia_pretraining` issue -- **0 findings**, validates going
forward.
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

CHECK_NAME = "dataset_orphaned_ingest"


def find_real_datasets(root: Path) -> set:
    real = set()
    for p in sorted(root.iterdir()):
        if not p.is_dir() or p.name in NON_DATASET_DIRS:
            continue
        has_real_crop = any(
            c.is_dir() and c.name.endswith(".zarr") and group_exists(c)
            for c in p.iterdir()
        )
        if has_real_crop:
            real.add(p.name)
    return real


def _strip_prose(s: str) -> str:
    for sep in (" (", " …"):
        idx = s.find(sep)
        if idx != -1:
            s = s[:idx]
    return s.strip()


def resolve_dataset_name(candidate: str, root: Path):
    p = Path(_strip_prose(candidate))
    if p.name == "raw" and p.parent.name.endswith(".zarr"):
        p = p.parent.parent
    elif p.name.endswith(".zarr"):
        p = p.parent
    try:
        rel = p.resolve().relative_to(root.resolve())
    except (OSError, ValueError):
        return None
    return rel.parts[0] if rel.parts else None


def find_covered_datasets(items: list, root: Path, real_datasets: set) -> set:
    covered = set()
    for item in items:
        if item.get("content", {}).get("repository") != "AI-HHMI/mia_pretraining":
            continue
        hp = item.get("hHMI_Path")
        if not hp:
            continue
        for candidate in (c.strip() for c in hp.split(";")):
            ds = resolve_dataset_name(candidate, root)
            if ds and ds in real_datasets:
                covered.add(ds)
    return covered


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="data", help="Directory to scan (default: data)")
    parser.add_argument("--reports-dir", default="reports", help="Where to write dated reports (default: reports)")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    real_datasets = find_real_datasets(root)
    items = fetch_project_items(MIA_PRETRAINING_PROJECT["owner"], MIA_PRETRAINING_PROJECT["number"])
    covered = find_covered_datasets(items, root, real_datasets)

    findings = []
    for dataset in sorted(real_datasets - covered):
        findings.append({
            "check": CHECK_NAME, "dataset": dataset, "path": dataset,
            "field": "untracked_dataset",
            "actual": "no mia_pretraining issue references this dataset",
            "expected": "a mia_pretraining issue tracking this dataset",
            "severity": "error",
            "suggested_fix": "create a mia_pretraining issue for this dataset (not automated -- flag only)",
        })

    run_date = datetime.date.today().isoformat()
    write_check_report(CHECK_NAME, findings, reports_dir=Path(args.reports_dir), date=run_date)

    print(f"{CHECK_NAME}: {len(findings)} finding(s) across {len(real_datasets)} real dataset(s)")
    if findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
