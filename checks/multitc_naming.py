#!/usr/bin/env python3
"""Check: every crop whose raw array actually has more than one timepoint
and/or more than one channel (read from its own ome.multiscales axes + the
finest pyramid level's real shape, not assumed from the name) encodes that
as the canonical `{N}t_{M}c` shorthand somewhere in its crop descriptor --
total timepoint count, then total channel count, in that order, both always
present even when one side is 1 (e.g. `crop-001_dsr_timeseries_48t_1c.zarr`
for 48 timepoints / 1 channel). This is for a crop that keeps every
timepoint/channel together in one store; it's unrelated to the `tN`/`chN`
suffix used on a label that's already been split out to a single timepoint
or channel.

Real corpus survey (Oct 7 2026) found 97 crops with T>1 or C>1 on disk, and
only one already uses this shorthand correctly -- the rest spell it out
differently (`_2channels`, `_2c`, `_3ch`) or don't encode it in the crop name
at all (one dataset puts the channel count in the *dataset* directory name
instead). This was already known and called a gap, not yet remediated, before
this check existed -- the check formalizes it as a standing rule going
forward rather than surfacing a surprise.

Retrofitting zarr v2 support (Oct 8 2026) added 3 more real multi-T/C crops
(the same Betzig zarr v2 crops `multitimepoint_label_sparsity.py` found),
all already correctly named -- 0 new findings.

Checks zarr v2 crops (`.zattrs`) as well as zarr v3 (`zarr.json`) -- retrofitted
Oct 8 2026, see metadata_completeness.py's docstring for why.
"""
import argparse
import datetime
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.report import write_check_report
from common.vocab import NON_DATASET_DIRS
from common.zarr_meta import get_multiscale, read_array_meta, read_group_attrs

CHECK_NAME = "multitc_naming"

_SHORTHAND_RE = re.compile(r"(?:^|_)(\d+)t_(\d+)c(?:_|\.|$)")


def _real_t_c_counts(crop_dir: Path):
    raw_dir = crop_dir / "raw" if (crop_dir / "raw").is_dir() else crop_dir
    attrs = read_group_attrs(raw_dir)
    multiscale = get_multiscale(attrs)
    if multiscale is None:
        return None
    axis_names = [a.get("name") for a in multiscale.get("axes", [])]
    datasets = multiscale.get("datasets", [])
    if not datasets:
        return None

    s0_path = datasets[0].get("path", "s0")
    array_meta = read_array_meta(raw_dir / s0_path)
    if array_meta is None:
        return None
    shape = array_meta["shape"]
    if shape is None or len(shape) != len(axis_names):
        return None

    t_count = shape[axis_names.index("t")] if "t" in axis_names else 1
    c_count = shape[axis_names.index("c")] if "c" in axis_names else 1
    return t_count, c_count


def check_crop(crop_dir: Path, root: Path, dataset: str) -> list[dict]:
    counts = _real_t_c_counts(crop_dir)
    if counts is None:
        return []
    t_count, c_count = counts
    if t_count <= 1 and c_count <= 1:
        return []

    name = crop_dir.name
    match = _SHORTHAND_RE.search(name)
    expected = f"{t_count}t_{c_count}c"
    if match and (int(match.group(1)), int(match.group(2))) == (t_count, c_count):
        return []

    rel = str(crop_dir.relative_to(root))
    return [{
        "check": CHECK_NAME,
        "dataset": dataset,
        "path": rel,
        "field": "crop_name",
        "actual": name,
        "expected": f"crop descriptor contains `{expected}` (real raw shape: {t_count} timepoint(s), {c_count} channel(s))",
        "severity": "error",
        "suggested_fix": f"rename crop directory to include `{expected}` in its descriptor",
    }]


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
    n_crops = 0
    for dataset_name, crop_dir in iter_crop_dirs(root):
        n_crops += 1
        findings.extend(check_crop(crop_dir, root, dataset_name))

    run_date = datetime.date.today().isoformat()
    write_check_report(CHECK_NAME, findings, reports_dir=Path(args.reports_dir), date=run_date)

    print(f"{CHECK_NAME}: {len(findings)} finding(s) across {n_crops} crop(s) under {root}")
    if findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
