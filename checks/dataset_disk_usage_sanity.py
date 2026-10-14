#!/usr/bin/env python3
"""Check: every directory under a dataset (every crop, every label, every
pyramid/chunk dir nested under it) has an apparent size
(`os.stat().st_size`) of exactly 4096 bytes -- see
label_disk_usage_sanity.py's docstring for the full reasoning and the
real-corpus survey (7,483,957 directories, all 4096 bytes, Oct 13 2026)
that validated this as a flat rule rather than a guess.

mia_pretraining tracks coverage per *dataset*, not per crop (some issues
cover a whole multi-crop dataset with one path -- the same reasoning
dataset_orphaned_ingest.py's scoping already established), so this check
is scoped to a whole dataset dir at a time, unlike its
label_disk_usage_sanity.py sibling.

Folded into the shared deep walk (common/deep_walk.py) rather than built
standalone -- same cost class as ownership_permissions.py/stray_files.py
(stat-ing every directory), not the pixel-decode cost of the last two
checks shipped.
"""
import argparse
import datetime
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.report import write_check_report
from common.vocab import NON_DATASET_DIRS
from common.deep_walk import walk_dataset, CHECK_DATASET_DISK_USAGE

CHECK_NAME = CHECK_DATASET_DISK_USAGE


def check_dataset(dataset_dir: Path, root: Path) -> list[dict]:
    """Walk one dataset dir and return just this check's slice of the shared
    deep walk (common.deep_walk.walk_dataset also computes ownership_permissions/
    stray_files/label_disk_usage_sanity findings in the same pass --
    checks/run_deep_walk_checks.py uses all of them from one walk; this
    standalone script only keeps its own).
    """
    return walk_dataset(dataset_dir, root)[CHECK_NAME]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="data", help="Directory to scan, recursively (default: data)")
    parser.add_argument("--reports-dir", default="reports", help="Where to write dated reports (default: reports)")
    parser.add_argument("--workers", type=int, default=1,
                         help="Thread count for walking root's immediate subdirs in parallel "
                              "(I/O-bound; match to -n when submitting via bsub, default: 1)")
    parser.add_argument("--flush-every", type=int, default=10,
                         help="Write a partial report every N completed dataset dirs (default: 10)")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    datasets = sorted(p for p in root.iterdir() if p.is_dir() and p.name not in NON_DATASET_DIRS)
    total = len(datasets)
    reports_dir = Path(args.reports_dir)
    run_date = datetime.date.today().isoformat()

    findings = []
    done = 0

    def flush():
        write_check_report(CHECK_NAME, findings, reports_dir=reports_dir, date=run_date)

    if args.workers <= 1:
        for d in datasets:
            findings.extend(check_dataset(d, root))
            done += 1
            print(f"{CHECK_NAME}: {done}/{total} checked ({d.name}) — {len(findings)} finding(s) so far", flush=True)
            if done % args.flush_every == 0:
                flush()
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            future_to_name = {pool.submit(check_dataset, d, root): d.name for d in datasets}
            for future in as_completed(future_to_name):
                findings.extend(future.result())
                done += 1
                name = future_to_name[future]
                print(f"{CHECK_NAME}: {done}/{total} checked ({name}) — {len(findings)} finding(s) so far", flush=True)
                if done % args.flush_every == 0:
                    flush()

    flush()
    print(f"{CHECK_NAME}: done — {len(findings)} finding(s) under {root}")
    if findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
