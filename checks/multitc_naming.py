#!/usr/bin/env python3
"""Check: every crop whose raw array actually has more than one timepoint,
channel, and/or TensorSwitch non-spatial `s` axis value (read from its own
ome.multiscales axes + the finest pyramid level's real shape, not assumed
from the name) encodes that in its crop descriptor using the canonical
`t`/`c`/`s` shorthand, in that fixed order -- each included only if that
axis is actually *present* in the raw array's own axes list. A present
axis always gets its count spelled out even when it's 1 (e.g.
`crop-001_dsr_timeseries_48t_1c.zarr` for 48 timepoints / 1 channel is
unaffected by a future single-timepoint crop also needing `1t_2c` if it
genuinely has a `t` axis) -- but a crop whose raw array has no `t` axis at
all (e.g. plain `czyx`, not `tczyx`) only ever needs its channel count
(`2c`), never a fabricated `1t_` prefix for an axis that doesn't exist. `s`
(TensorSwitch's non-spatial axis, added there but not yet used by any real
crop on this corpus as of Oct 16 2026) follows the identical presence-based
rule, ready for whenever a real `s`-axis crop lands.
Found and fixed Oct 16 2026 after a real false positive: a genuinely 4D
`czyx` crop (`exm-drosophila-flyliconn-FlyID45-1-flybrain-synapse-2ch-
20260624/crop-001_...`) was flagged for missing `1t_2c` despite having no
time axis whatsoever -- the original version treated "no t axis" the same
as "t axis present with count 1," which are different real situations.
This is for a crop that keeps every timepoint/channel/s-value together in
one store; it's unrelated to the `tN`/`chN` suffix used on a label that's
already been split out to a single timepoint or channel.

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

# Non-spatial axes this corpus's naming convention encodes, in the fixed
# order they appear in a crop descriptor (t, then c, then s). "s" is
# TensorSwitch's own non-spatial axis -- not used by any real crop on this
# corpus yet, included so the check is ready the moment one lands.
_AXIS_ORDER = ["t", "c", "s"]
_AXIS_LABEL = {"t": "timepoint(s)", "c": "channel(s)", "s": "s-value(s)"}


def _real_nonspatial_counts(crop_dir: Path):
    """{axis: count} for each of _AXIS_ORDER present in the raw array's own
    axes -- an axis missing from this dict is absent from the schema
    entirely, which is not the same as being present with count 1 (a crop
    can be genuinely 4D czyx, with no t axis whatsoever, vs. tczyx with a
    real but size-1 t axis).
    """
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

    return {ax: shape[axis_names.index(ax)] for ax in _AXIS_ORDER if ax in axis_names}


def check_crop(crop_dir: Path, root: Path, dataset: str) -> list[dict]:
    counts = _real_nonspatial_counts(crop_dir)
    if counts is None:
        return []
    present = [ax for ax in _AXIS_ORDER if ax in counts]
    if not present or all(counts[ax] <= 1 for ax in present):
        return []

    name = crop_dir.name
    expected = "_".join(f"{counts[ax]}{ax}" for ax in present)
    pattern = r"(?:^|_)" + "_".join(rf"(\d+){ax}" for ax in present) + r"(?:_|\.|$)"
    match = re.search(pattern, name)
    if match and tuple(int(g) for g in match.groups()) == tuple(counts[ax] for ax in present):
        return []

    rel = str(crop_dir.relative_to(root))
    shape_desc = ", ".join(f"{counts[ax]} {_AXIS_LABEL[ax]}" for ax in present)
    return [{
        "check": CHECK_NAME,
        "dataset": dataset,
        "path": rel,
        "field": "crop_name",
        "actual": name,
        "expected": f"crop descriptor contains `{expected}` (real raw shape: {shape_desc})",
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
