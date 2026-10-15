#!/usr/bin/env python3
"""Run every check in this repo against the real corpus in one pass, writing
to the same dated reports dir so the dashboard reflects a single coherent
run. Four deep-walk checks (ownership_permissions, stray_files,
label_disk_usage_sanity, dataset_disk_usage_sanity) go through
run_deep_walk_checks.py so the corpus is only walked once; PIXI_CHECKS need
real pixel decoding (zarr/numpy, see pixi.toml) so run via `pixi run
python3`; every other check is shallow metadata/board-only and runs
directly. This is the one script to submit for a full corpus-wide refresh
-- see submit_all_checks.sh for the cluster job wrapper.

Crash detection can't rely on exit code alone: every check in this repo uses
sys.exit(1) for "findings present," the exact same code Python uses by
default for an unhandled exception -- so a real crash and a normal
findings-present run are indistinguishable by exit code. Instead, a
subprocess is only flagged as crashed if it wrote anything to stderr (a
traceback) -- a normal run only ever prints to stdout.
"""
import argparse
import datetime
import subprocess
import sys
import time
from pathlib import Path

REPO_DIR = Path(__file__).resolve().parent.parent

SHALLOW_CHECKS = [
    "dataset_naming.py",
    "label_naming.py",
    "crop_naming.py",
    "pyramid_consistency.py",
    "metadata_consistency.py",
    "metadata_vocab.py",
    "voxel_size.py",
    "metadata_completeness.py",
    "bbox_sanity.py",
    "chunk_shard_sanity.py",
    "license_fields.py",
    "multitc_naming.py",
    "parent_raw_validity.py",
    "channel_index_consistency.py",
    "multitimepoint_label_sparsity.py",
    "label_field_drift.py",
    "label_orphaned_ingest.py",
    "empty_label_data.py",
    "freshness.py",
    "dataset_field_drift.py",
    "dataset_orphaned_ingest.py",
    "dataset_crop_coverage.py",
]

# Need real pixel data (zarr/numpy), not just metadata -- run via `pixi run
# python3` instead of bare python3 (see pixi.toml).
PIXI_CHECKS = [
    "divergent_voxel_counts.py",
    "annotated_voxels_sanity.py",
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="/groups/miaai/miaai/lmd-v0.0.1/data")
    parser.add_argument("--reports-dir", default=str(REPO_DIR / "reports"))
    parser.add_argument("--workers", type=int, default=8, help="Workers for the deep-walk pass")
    args = parser.parse_args()

    run_date = datetime.date.today().isoformat()
    print(f"=== mia-data-qc full run, {run_date} ===")

    failures = []

    def run(label, cmd):
        print(f"--- {label} ---")
        # GitHub's secondary (burst) rate limit is transient and has hit this project before
        # (clears in well under a minute) -- retry a few times before giving up, since this
        # script runs unattended overnight with nobody around to notice and re-run by hand.
        for attempt in range(4):
            result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_DIR))
            if "rate limit" in result.stderr.lower() and attempt < 3:
                print(f"{label}: hit a GitHub rate limit, retrying in 30s (attempt {attempt + 1}/4)", flush=True)
                time.sleep(30)
                continue
            break
        if result.stdout:
            print(result.stdout, end="")
        if result.stderr.strip():
            print(result.stderr, end="", file=sys.stderr)
            failures.append(label)

    run("deep_walk", [
        sys.executable, str(REPO_DIR / "checks" / "run_deep_walk_checks.py"),
        "--root", args.root, "--group", "miaai",
        "--workers", str(args.workers), "--reports-dir", args.reports_dir,
    ])

    for check in SHALLOW_CHECKS:
        run(check, [
            sys.executable, str(REPO_DIR / "checks" / check),
            "--root", args.root, "--reports-dir", args.reports_dir,
        ])

    for check in PIXI_CHECKS:
        run(check, [
            "pixi", "run", "python3", str(REPO_DIR / "checks" / check),
            "--root", args.root, "--reports-dir", args.reports_dir,
        ])

    print(f"=== done. {len(failures)} check(s) crashed (not counting ones that found findings): {failures} ===")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
