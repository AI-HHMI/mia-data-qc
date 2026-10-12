#!/usr/bin/env python3
"""Check: for every `mia_pretraining` issue whose `HHMI_Path` resolves to a
real crop on disk, compare its `Axis_Order` and `Dtype` board fields against
that crop's own raw metadata. The `mia_pretraining`-side sibling of
`label_field_drift.py`, same severity reasoning: `warning`, not `error` --
either side can be the stale one (a board field and the on-disk metadata
can each be edited independently), so the finding is "these disagree, a
human decides," never an instruction to overwrite one side with the other.

Resolution: `HHMI_Path` (trying each `;`-separated candidate) rather than a
title-derived index -- `mia_pretraining` issue titles are free-form
human-readable names with no fixed relationship to on-disk paths (unlike
`mia_annotation`'s 3-component convention), so there's no equivalent
canonical-title index to build. A path pointing directly at a `*.zarr` crop
is used as-is; a path pointing at a *dataset* directory (several
`mia_pretraining` issues describe a whole multi-crop dataset, not one crop)
is resolved via the one designated `*_fullvol*.zarr` crop if there's exactly
one -- the established "whole dataset, stitched" convention (see the Betzig
mosaic datasets) -- otherwise skipped as ambiguous rather than guessed at.

Only `Axis_Order` and `Dtype` are compared -- the only two fields with a
clean, reliably-parseable format. `Chunk_Shape`/`Shard_Shape` were surveyed
too and found to have 28+ distinct free-text conventions across the real
corpus (`"128³"`, `"128^3"`, `"128,128,128"`, `"128×128×32 (XYZ)"`,
`"1×128×128×128 (inner, CXYZ) / 8×512×512×512 (shard)"`, `"N/A (zarr2)"`,
...) -- too inconsistent to parse reliably without real risk of false
positives; deferred rather than guessed at. Comparison is normalized on both
sides: `Axis_Order` by stripping everything but letters and lowercasing
(so `"XYZ"`, `"x,y,z"`, and `"X, Y, Z"` all compare equal); `Dtype` by
mapping zarr v2's numpy-style dtype strings (`"<u2"`, `">u2"`, ...) to their
zarr v3 name (`"uint16"`) before comparing case-insensitively.

Real corpus survey (Oct 12 2026): 224 `mia_pretraining` issues have an
`HHMI_Path`, 105-106 resolve to a real crop. First pass (naive exact-string
comparison) found 11 `Axis_Order` "mismatches" and 2 `Dtype` "mismatches" --
all 13 were false positives from inadequate normalization (the board
sometimes lists non-spatial axes like `t,c` that a spatial-only axis
extraction had dropped; a couple of entries use `"XYZ"` instead of
`"x,y,z"`; two raw arrays are legacy zarr v2 stores whose dtype reads as
numpy's `"<u2"`/`">u2"` instead of `"uint16"`). After normalizing both
checks properly, a second pass against the real corpus (the shipped check
itself, not just the survey script) found 6 *more* "mismatches" on 3 LICONN
volumes -- a second, more serious bug: this project cross-lists
`mia_annotation`-repo issues alongside `mia_pretraining`'s own (confirmed:
`mia_annotation`'s own project has no such cross-listing, this is
one-directional), so a naive item loop compares two *different* issues
describing two *different* things against the same disk path -- a
`mia_pretraining` dataset issue correctly describing raw's 3D `x,y,z`
`uint16` shape, and a same-looking-named `mia_annotation` *label* issue
describing that label's own 4D `c,x,y,z` `uint32` shape, wrongly compared
against the crop's raw metadata instead of the label's own. Fixed by
filtering to `content.repository == "AI-HHMI/mia_pretraining"` before
resolving anything -- the same `(repository, issue_number)` discipline
flagged repeatedly elsewhere in this project's notes. After that fix: **0
real mismatches**. The specific motivating case (5 Betzig fullvol issues
with `Axis_Order` still reading the stale `t,c,z,y,x` as of Oct 9, 2026) was
re-checked directly and found already corrected on the board by the time
this check was built -- this check mostly validates the fields stay in sync
going forward.
"""
import argparse
import datetime
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.github import fetch_project_items, MIA_PRETRAINING_PROJECT
from common.report import write_check_report
from common.zarr_meta import get_multiscale, read_array_meta, read_group_attrs

CHECK_NAME = "dataset_field_drift"

_DTYPE_NORM = {
    "<u1": "uint8", ">u1": "uint8", "|u1": "uint8",
    "<u2": "uint16", ">u2": "uint16",
    "<i1": "int8", ">i1": "int8", "|i1": "int8",
    "<i2": "int16", ">i2": "int16",
    "<f4": "float32", ">f4": "float32",
}


def _norm_axes(s: str) -> str:
    return re.sub(r"[^a-z]", "", s.lower())


def resolve_crop_dir(hhmi_path: str):
    for candidate in (p.strip() for p in hhmi_path.split(";")):
        p = Path(candidate)
        if p.name.endswith(".zarr") and p.is_dir():
            return p
        if p.is_dir():
            fullvols = sorted(p.glob("*_fullvol*.zarr"))
            if len(fullvols) == 1:
                return fullvols[0]
    return None


def check_item(item: dict, crop_dir: Path, root: Path) -> list[dict]:
    raw_dir = crop_dir / "raw" if (crop_dir / "raw").is_dir() else crop_dir
    attrs = read_group_attrs(raw_dir)
    multiscale = get_multiscale(attrs)
    if multiscale is None:
        return []

    dataset = crop_dir.parent.name
    rel = str(raw_dir.relative_to(root)) if root in raw_dir.parents or raw_dir == root else str(raw_dir)
    try:
        rel = str(raw_dir.relative_to(root))
    except ValueError:
        return []  # resolved outside this corpus root -- not this run's concern

    url = item.get("content", {}).get("url", "")
    findings = []

    board_axis = item.get("axis_Order")
    axes = [a.get("name") for a in multiscale.get("axes", [])]
    if board_axis and axes and _norm_axes(board_axis) != _norm_axes(",".join(axes)):
        findings.append({
            "check": CHECK_NAME, "dataset": dataset, "path": rel,
            "field": "axis_Order",
            "actual": f"board={board_axis!r}, disk={','.join(axes)!r}",
            "expected": "board and disk agree (neither side assumed correct)",
            "severity": "warning",
            "suggested_fix": f"compare both values on issue {url} and update whichever is stale",
        })

    board_dtype = item.get("dtype")
    datasets = multiscale.get("datasets", [])
    if board_dtype and datasets:
        array_meta = read_array_meta(raw_dir / datasets[0].get("path", "s0"))
        if array_meta and array_meta.get("dtype"):
            real_dtype = _DTYPE_NORM.get(array_meta["dtype"], array_meta["dtype"])
            if board_dtype.strip().lower() != str(real_dtype).strip().lower():
                findings.append({
                    "check": CHECK_NAME, "dataset": dataset, "path": rel,
                    "field": "dtype",
                    "actual": f"board={board_dtype!r}, disk={real_dtype!r}",
                    "expected": "board and disk agree (neither side assumed correct)",
                    "severity": "warning",
                    "suggested_fix": f"compare both values on issue {url} and update whichever is stale",
                })

    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="data", help="Directory to scan (default: data)")
    parser.add_argument("--reports-dir", default="reports", help="Where to write dated reports (default: reports)")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    items = fetch_project_items(MIA_PRETRAINING_PROJECT["owner"], MIA_PRETRAINING_PROJECT["number"])

    findings = []
    n_resolved = 0
    for item in items:
        if item.get("content", {}).get("repository") != "AI-HHMI/mia_pretraining":
            continue  # this board cross-lists mia_annotation issues too -- (repository, number), never bare number
        hp = item.get("hHMI_Path")
        if not hp:
            continue
        crop_dir = resolve_crop_dir(hp)
        if crop_dir is None:
            continue
        n_resolved += 1
        findings.extend(check_item(item, crop_dir, root))

    run_date = datetime.date.today().isoformat()
    write_check_report(CHECK_NAME, findings, reports_dir=Path(args.reports_dir), date=run_date)

    print(f"{CHECK_NAME}: {len(findings)} finding(s) across {n_resolved} resolved mia_pretraining item(s)")
    if findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
