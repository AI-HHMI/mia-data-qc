#!/usr/bin/env python3
"""Check: a label's bbox metadata is structurally sane --
coordinate_order is exactly "XYZ" or "ZYX" (case-sensitive; a real corpus
survey found 6 labels with lowercase "xyz", all the same dataset that
voxel_size.py independently flags for an anisotropic voxel-size bug --
cross-check evidence this dataset's ingestion pipeline is non-standard),
unit is one of the two legitimate real conventions ("voxel",
"nanometer_offset_voxel_size"), offset/size are both present with matching,
3-element length, and every size value is positive.

Does NOT check whether offset+size stays within the parent raw's actual
shape -- the two different unit conventions need separate conversion logic
to do that correctly; left for a future, separate check rather than guessed
at here.
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.report import write_check_report
from common.vocab import NON_DATASET_DIRS

CHECK_NAME = "bbox_sanity"

COORDINATE_ORDERS = {"XYZ", "ZYX"}
UNITS = {"voxel", "nanometer_offset_voxel_size"}


def check_label(label_dir: Path, root: Path, dataset: str) -> list[dict]:
    zarr_json_path = label_dir / "zarr.json"
    try:
        attrs = json.loads(zarr_json_path.read_text()).get("attributes", {})
    except (OSError, json.JSONDecodeError):
        return []

    bbox = attrs.get("bbox")
    if bbox is None:
        return []  # missing entirely is metadata_completeness.py's job

    rel = str(zarr_json_path.relative_to(root))
    findings = []

    def add(field, actual, expected, fix):
        findings.append({
            "check": CHECK_NAME, "dataset": dataset, "path": rel, "field": field,
            "actual": actual, "expected": expected, "severity": "error", "suggested_fix": fix,
        })

    coord_order = bbox.get("coordinate_order")
    if coord_order is not None and coord_order not in COORDINATE_ORDERS:
        add("bbox.coordinate_order", coord_order, "/".join(sorted(COORDINATE_ORDERS)),
            "fix casing/value to match the canonical XYZ or ZYX convention")

    unit = bbox.get("unit")
    if unit is not None and unit not in UNITS:
        add("bbox.unit", unit, "/".join(sorted(UNITS)),
            "confirm this is a genuinely new unit convention, not a typo")

    offset = bbox.get("offset")
    size = bbox.get("size")
    if offset is not None and size is not None:
        if len(offset) != len(size):
            add("bbox.offset_size_length", f"offset={len(offset)}, size={len(size)}",
                "offset and size the same length", "fix whichever array is the wrong length")
        elif len(offset) != 3:
            add("bbox.array_length", len(offset), 3,
                "confirm this label genuinely has a non-3D bbox, not a truncated/malformed one")

        if size is not None and any(s <= 0 for s in size):
            add("bbox.size_positive", size, "every size value > 0",
                "a zero or negative bbox size is not a real region -- fix or remove this bbox")

    return findings


def iter_label_dirs(root: Path):
    for dataset_dir in sorted(p for p in root.iterdir() if p.is_dir() and p.name not in NON_DATASET_DIRS):
        for crop_dir in sorted(p for p in dataset_dir.iterdir() if p.is_dir() and p.name.endswith(".zarr")):
            labels_dir = crop_dir / "labels"
            if not labels_dir.is_dir():
                continue
            for label_dir in sorted(p for p in labels_dir.iterdir() if p.is_dir()):
                if (label_dir / "zarr.json").is_file():
                    yield dataset_dir.name, label_dir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="data", help="Directory to scan (default: data)")
    parser.add_argument("--reports-dir", default="reports", help="Where to write dated reports (default: reports)")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    findings = []
    n_labels = 0
    for dataset_name, label_dir in iter_label_dirs(root):
        n_labels += 1
        findings.extend(check_label(label_dir, root, dataset_name))

    run_date = datetime.date.today().isoformat()
    write_check_report(CHECK_NAME, findings, reports_dir=Path(args.reports_dir), date=run_date)

    print(f"{CHECK_NAME}: {len(findings)} finding(s) across {n_labels} label dir(s) under {root}")
    if findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
