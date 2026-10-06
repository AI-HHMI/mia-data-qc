#!/usr/bin/env python3
"""Check: every zarr.json with an OME multiscales block (crop root, raw/, each
label) has its multiscales.datasets[].path list actually matching what pyramid
levels (s0, s1, ...) exist on disk -- both directions: a listed level that's
missing on disk (dangling -- the documented incident: an ingest once silently
dropped raw's s0-s5 entries from root metadata) and a level present on disk but
not listed (orphaned -- never registered, e.g. a pyramid job that half-finished).

Root zarr.json's paths are prefixed ("raw/s0"); raw/zarr.json's and each label's
own paths are bare ("s0") relative to themselves -- root is checked for dangling
entries only, since it doesn't own sN dirs directly, only raw/ and each label do.
"""
import argparse
import datetime
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.report import write_check_report
from common.vocab import NON_DATASET_DIRS

CHECK_NAME = "pyramid_consistency"
_RUNG_RE = re.compile(r"^s\d+$")


def _multiscale_dataset_paths(zarr_json_path: Path):
    try:
        data = json.loads(zarr_json_path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    multiscales = data.get("attributes", {}).get("ome", {}).get("multiscales")
    if not multiscales:
        return None
    return [d["path"] for d in multiscales[0].get("datasets", []) if d.get("path")]


def check_zarr_json(zarr_json_path: Path, root: Path, dataset: str, check_orphans: bool,
                     required_prefix: str = None) -> list[dict]:
    findings = []
    paths = _multiscale_dataset_paths(zarr_json_path)
    if paths is None:
        return findings

    base_dir = zarr_json_path.parent
    rel = str(zarr_json_path.relative_to(root))

    for p in paths:
        # A path that resolves to a real directory can still be WRONG -- the
        # documented incident replaced root's raw/sN entries with a label's own
        # path, which itself existed on disk. Catch that even when the swapped
        # path happens to exist, not just true dangling references.
        if required_prefix is not None and not p.startswith(required_prefix):
            findings.append({
                "check": CHECK_NAME,
                "dataset": dataset,
                "path": rel,
                "field": "misdirected_pyramid_level",
                "actual": p,
                "expected": f"path starting with '{required_prefix}'",
                "severity": "error",
                "suggested_fix": "fix multiscales.datasets to reference raw/'s own pyramid levels, not another group's",
            })
            continue
        if not (base_dir / p).is_dir():
            findings.append({
                "check": CHECK_NAME,
                "dataset": dataset,
                "path": rel,
                "field": "dangling_pyramid_level",
                "actual": p,
                "expected": "a directory present on disk",
                "severity": "error",
                "suggested_fix": "regenerate the pyramid or fix the multiscales.datasets list to match disk",
            })

    if check_orphans:
        listed_names = {Path(p).name for p in paths}
        try:
            on_disk = {e.name for e in base_dir.iterdir() if e.is_dir() and _RUNG_RE.match(e.name)}
        except OSError:
            on_disk = set()
        for extra in sorted(on_disk - listed_names):
            findings.append({
                "check": CHECK_NAME,
                "dataset": dataset,
                "path": rel,
                "field": "orphaned_pyramid_level",
                "actual": extra,
                "expected": "every on-disk level listed in multiscales.datasets",
                "severity": "error",
                "suggested_fix": f"add '{extra}' to multiscales.datasets, or remove it if it's stale",
            })

    return findings


def iter_zarr_jsons(root: Path):
    """Yield (dataset_name, zarr_json_path, check_orphans, required_prefix) for
    every zarr.json worth checking: a crop's root, its raw/ (if present), and
    every label under it (orphan check).

    Most crops wrap their image pyramid in a raw/ subgroup -- there, root must
    only reference raw/'s levels (required_prefix="raw/", no orphan check: root
    doesn't own sN dirs directly) and raw/zarr.json itself gets the orphan check.
    Some crops (confirmed on disk, Oct 6 2026 -- a pre-convention Betzig demo
    dataset) have no raw/ at all and keep s0.. directly under the crop root --
    there root IS the image level, so it gets the orphan check instead and no
    prefix requirement.
    """
    for dataset_dir in sorted(p for p in root.iterdir() if p.is_dir() and p.name not in NON_DATASET_DIRS):
        for crop_dir in sorted(p for p in dataset_dir.iterdir() if p.is_dir() and p.name.endswith(".zarr")):
            root_zj = crop_dir / "zarr.json"
            has_raw = (crop_dir / "raw").is_dir()
            if root_zj.is_file():
                if has_raw:
                    yield dataset_dir.name, root_zj, False, "raw/"
                else:
                    yield dataset_dir.name, root_zj, True, None

            raw_zj = crop_dir / "raw" / "zarr.json"
            if raw_zj.is_file():
                yield dataset_dir.name, raw_zj, True, None

            labels_dir = crop_dir / "labels"
            if labels_dir.is_dir():
                for label_dir in sorted(p for p in labels_dir.iterdir() if p.is_dir()):
                    label_zj = label_dir / "zarr.json"
                    if label_zj.is_file():
                        yield dataset_dir.name, label_zj, True, None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="data", help="Directory to scan (default: data)")
    parser.add_argument("--reports-dir", default="reports", help="Where to write dated reports (default: reports)")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    findings = []
    n_checked = 0
    for dataset_name, zarr_json_path, check_orphans, required_prefix in iter_zarr_jsons(root):
        n_checked += 1
        findings.extend(check_zarr_json(zarr_json_path, root, dataset_name, check_orphans, required_prefix))

    run_date = datetime.date.today().isoformat()
    write_check_report(CHECK_NAME, findings, reports_dir=Path(args.reports_dir), date=run_date)

    print(f"{CHECK_NAME}: {len(findings)} finding(s) across {n_checked} zarr.json file(s) under {root}")
    if findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
