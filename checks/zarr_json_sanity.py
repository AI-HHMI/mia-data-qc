#!/usr/bin/env python3
"""Check: every zarr v3 *group* `zarr.json` (crop root, `raw/`, `labels/`, and
each individual label) has only keys the zarr v3 spec actually allows at the
group level -- `zarr_format`, `node_type`, `attributes`, and
`consolidated_metadata`. Any other top-level key makes the store unreadable
by zarr-python itself, not just a convention violation.

Found Nov 9 2026 -- Emin Orhan reported 5 stores (`em-drosophila-FANC-vnc`
crop-001/crop-002, `em-drosophila-flyem-hemibrain` crop-001/002/003) whose
root `zarr.json` carried a `_source` provenance block as a *sibling* of
`attributes` instead of nested inside it:
  zarr 3.2.1: TypeError: GroupMetadata.__init__() got an unexpected keyword
  argument '_source'
  zarr 3.4.2: MetadataValidationError: ... disallowed extra fields: ['_source']
A corpus-wide scan confirmed exactly those 5, all at the crop-root level
only (`raw/`/`labels/*` were clean) -- fixed by moving `_source` one level
deeper, into `attributes._source` (same content, just legally placed; see
`lmvd_quality_control.md`'s 2026-11-09 entry). This check exists so the next
time any script writes a custom top-level key by mistake, it's caught before
someone discovers their store can no longer be opened at all.

Scoped to **group** metadata only -- an *array* `zarr.json` (e.g. a pyramid
level's `s0/zarr.json`) legitimately has a completely different key set
(`shape`, `data_type`, `chunk_grid`, `codecs`, ...), so this check skips any
`zarr.json` whose `node_type` isn't `"group"` rather than false-flagging
every array in the corpus. zarr v2 (`.zattrs`/`.zarray`) has no such
constraint at all -- it's a different metadata format entirely, not scoped
here.
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.report import write_check_report
from common.vocab import NON_DATASET_DIRS

CHECK_NAME = "zarr_json_sanity"
ALLOWED_GROUP_KEYS = {"zarr_format", "node_type", "attributes", "consolidated_metadata"}


def check_zarr_json(path: Path, root: Path, dataset: str) -> list[dict]:
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    if data.get("node_type") != "group":
        return []

    extra = sorted(set(data) - ALLOWED_GROUP_KEYS)
    if not extra:
        return []
    return [{
        "check": CHECK_NAME,
        "dataset": dataset,
        "path": str(path.relative_to(root)),
        "field": "zarr_json_extra_root_key",
        "actual": extra,
        "expected": f"only {sorted(ALLOWED_GROUP_KEYS)} at the top level of a group zarr.json",
        "severity": "error",
        "suggested_fix": (
            "move each extra key's value into attributes (same key name, nested one level deeper) "
            "-- zarr-python refuses to even open a group zarr.json with an unrecognized top-level key"
        ),
    }]


def check_crop(crop_dir: Path, root: Path, dataset: str) -> list[dict]:
    findings = []
    findings.extend(check_zarr_json(crop_dir / "zarr.json", root, dataset))
    findings.extend(check_zarr_json(crop_dir / "raw" / "zarr.json", root, dataset))
    labels_dir = crop_dir / "labels"
    if labels_dir.is_dir():
        findings.extend(check_zarr_json(labels_dir / "zarr.json", root, dataset))
        for label_dir in sorted(p for p in labels_dir.iterdir() if p.is_dir()):
            findings.extend(check_zarr_json(label_dir / "zarr.json", root, dataset))
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
