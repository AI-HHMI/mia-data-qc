#!/usr/bin/env python3
"""Check: for a crop whose raw array really has more than one channel (read
from its own ome.multiscales axes + the finest pyramid level's real shape,
same method as multitc_naming.py), every label that does NOT itself keep a
`c` axis -- meaning it was derived from a single specific channel, not all
of them together -- has a valid `source.channel_index` recording which
channel, an integer in `[0, channel_count)`. A label that still has its own
`c` axis (covers every channel) needs no such field and isn't checked.

Real corpus survey (Oct 7 2026): 96 crops have a real raw channel count > 1,
but only one of them -- `lm-zebrafish-Betzig-mosaic-example_annotations_Thayer
/crop-002_example_annotations_Thayer_2channels.zarr` -- actually has labels
yet (4, all 3D ZYX with no `c` axis), and none of the 4 records which channel
they came from. This is the exact known gap called out when this rule was
first proposed; the other 95 multi-channel crops have no labels at all yet,
so this check mostly validates the rule going forward.
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.report import write_check_report
from common.vocab import NON_DATASET_DIRS

CHECK_NAME = "channel_index_consistency"


def _real_channel_count(crop_dir: Path):
    raw_dir = crop_dir / "raw" if (crop_dir / "raw").is_dir() else crop_dir
    try:
        data = json.loads((raw_dir / "zarr.json").read_text())
    except (OSError, json.JSONDecodeError):
        return None

    multiscales = data.get("attributes", {}).get("ome", {}).get("multiscales", [])
    if not multiscales:
        return None
    axes = [a.get("name") for a in multiscales[0].get("axes", [])]
    datasets = multiscales[0].get("datasets", [])
    if not datasets or "c" not in axes:
        return None

    s0_path = datasets[0].get("path", "s0")
    try:
        shape = json.loads((raw_dir / s0_path / "zarr.json").read_text()).get("shape")
    except (OSError, json.JSONDecodeError):
        return None
    if shape is None or len(shape) != len(axes):
        return None

    return shape[axes.index("c")]


def _label_has_c_axis(label_dir: Path):
    try:
        attrs = json.loads((label_dir / "zarr.json").read_text()).get("attributes", {})
    except (OSError, json.JSONDecodeError):
        return None
    multiscales = attrs.get("ome", {}).get("multiscales", [])
    if not multiscales:
        return None  # no axes metadata -- can't determine, don't guess
    axes = [a.get("name") for a in multiscales[0].get("axes", [])]
    return "c" in axes


def check_label(label_dir: Path, root: Path, dataset: str, channel_count: int) -> list[dict]:
    has_c_axis = _label_has_c_axis(label_dir)
    if has_c_axis is None or has_c_axis:
        return []  # covers all channels, or undetermined -- not this check's concern

    try:
        attrs = json.loads((label_dir / "zarr.json").read_text()).get("attributes", {})
    except (OSError, json.JSONDecodeError):
        return []

    source = attrs.get("source")
    channel_index = source.get("channel_index") if isinstance(source, dict) else None

    rel = str((label_dir / "zarr.json").relative_to(root))
    if channel_index is None:
        return [{
            "check": CHECK_NAME, "dataset": dataset, "path": rel,
            "field": "source.channel_index",
            "actual": "missing",
            "expected": f"an integer in [0, {channel_count})",
            "severity": "error",
            "suggested_fix": "record which raw channel this label was derived from in source.channel_index",
        }]

    if not isinstance(channel_index, int) or not (0 <= channel_index < channel_count):
        return [{
            "check": CHECK_NAME, "dataset": dataset, "path": rel,
            "field": "source.channel_index",
            "actual": channel_index,
            "expected": f"an integer in [0, {channel_count})",
            "severity": "error",
            "suggested_fix": "fix source.channel_index to a valid channel index for this crop's raw",
        }]

    return []


def iter_crop_dirs(root: Path):
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
    n_labels = 0
    for dataset_name, crop_dir in iter_crop_dirs(root):
        channel_count = _real_channel_count(crop_dir)
        if channel_count is None or channel_count <= 1:
            continue
        labels_dir = crop_dir / "labels"
        if not labels_dir.is_dir():
            continue
        for label_dir in sorted(p for p in labels_dir.iterdir() if p.is_dir()):
            if not (label_dir / "zarr.json").is_file():
                continue
            n_labels += 1
            findings.extend(check_label(label_dir, root, dataset_name, channel_count))

    run_date = datetime.date.today().isoformat()
    write_check_report(CHECK_NAME, findings, reports_dir=Path(args.reports_dir), date=run_date)

    print(f"{CHECK_NAME}: {len(findings)} finding(s) across {n_labels} label dir(s) in multi-channel crops under {root}")
    if findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
