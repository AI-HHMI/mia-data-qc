#!/usr/bin/env python3
"""Check: a crop's `labels/zarr.json` (the OME-NGFF labels-*group*'s own
manifest, `attributes.ome.labels` -- distinct from any individual label's own
metadata) lists exactly the label directories that actually exist on disk,
no more and no less.

Found Nov 2 2026 while tracing an unrelated Neuroglancer "can't find the
label" report: the real cause turned out to be this manifest still listing a
label's *old, pre-rename* name after the directory itself had been renamed
(`label_naming.py`'s own fix renames a label's directory but has never
touched this separate group-level manifest). No existing check reads this
file at all -- confirmed by grepping every other check for any reference to
a crop's `labels/zarr.json` manifest list; zero hits before this one.

A full corpus scan (549 crops carrying a `labels` manifest) found exactly 2
real mismatches, both the same shape -- a rename that never propagated here:
`em-celegans-funceworm-jrc-20250414` (`organelle` -> `all_organelles`) and
`em-human-H01-cortex` (`cells` -> `cell`). Rare, but a real discoverability
bug when it happens -- Neuroglancer/any OME-NGFF-aware viewer reads this
manifest to know what labels exist under a crop, so a stale entry here can
make an otherwise-correct label invisible to tooling that trusts the
manifest instead of listing the directory itself.

A crop with no `labels/` directory, no manifest file, or a manifest with no
`labels` key at all is not an error -- this field is optional OME-NGFF
metadata, not every crop populates it, and this check has nothing to say
about a crop that simply doesn't declare one.

Checks zarr v2 crops (`.zattrs`) as well as zarr v3 (`zarr.json`) via
`common.zarr_meta`, consistent with every other check here.
"""
import argparse
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.report import write_check_report
from common.vocab import NON_DATASET_DIRS
from common.zarr_meta import read_group_attrs

CHECK_NAME = "label_manifest_consistency"


def check_crop(crop_dir: Path, root: Path, dataset: str) -> list[dict]:
    labels_dir = crop_dir / "labels"
    if not labels_dir.is_dir():
        return []

    attrs = read_group_attrs(labels_dir)
    if attrs is None:
        return []

    listed = attrs.get("ome", {}).get("labels")
    if listed is None:
        listed = attrs.get("labels")
    if listed is None:
        return []

    real = {p.name for p in labels_dir.iterdir() if p.is_dir()}
    listed_set = set(listed)
    if listed_set == real:
        return []

    stale = sorted(listed_set - real)
    unlisted = sorted(real - listed_set)
    return [{
        "check": CHECK_NAME,
        "dataset": dataset,
        "path": str(labels_dir.relative_to(root)),
        "field": "label_manifest_mismatch",
        "actual": {"manifest_only": stale, "disk_only": unlisted},
        "expected": "labels/zarr.json's ome.labels list matches the real label directory names exactly",
        "severity": "error",
        "suggested_fix": (
            "update the ome.labels list to match the real directory names -- likely a label was "
            "renamed (e.g. a label_naming.py fix) without this group-level manifest being updated "
            "to match"
        ),
    }]


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
