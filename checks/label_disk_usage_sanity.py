#!/usr/bin/env python3
"""Check: every directory under a label (its own root dir and everything
nested under it -- pyramid levels, chunk dirs) has an apparent size
(`os.stat().st_size`) of exactly 4096 bytes -- the same value `du -sb
--apparent-size` would report for it. This isn't a guess at a "normal"
value: `du -sb --apparent-size <dir>` is exactly
`sum(file st_size) + sum(dir st_size, including the dir itself)`, verified
directly against real `du` output on this filesystem -- so a directory
whose own apparent size differs from 4096 is exactly the real,
disk-usage-level discrepancy the original design proposal's "du vs.
recorded bytes" item was about, without needing to shell out to `du`
itself. Surveyed the whole real corpus first (Oct 13 2026, 7,483,957
directories across all 139 datasets, including the largest Betzig fullvol
crops at 2-3.5M directories each): every single one is 4096 bytes, so this
rule isn't a guess that happens to hold on small data -- it holds
everywhere this corpus has been checked, including its most populous
directories.

mia_annotation tracks per-label, so this check is scoped to one label's
own subtree at a time (its sibling, dataset_disk_usage_sanity.py, is
scoped to the whole dataset instead, matching how mia_pretraining tracks
coverage).

Folded into the shared deep walk (common/deep_walk.py) rather than built
standalone -- this check's cost is stat-ing every directory in the corpus,
the same cost class as ownership_permissions.py/stray_files.py, not the
pixel-decode cost of divergent_voxel_counts.py/annotated_voxels_sanity.py.
"""
import argparse
import datetime
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.report import write_check_report
from common.vocab import NON_DATASET_DIRS
from common.deep_walk import walk_dataset, CHECK_LABEL_DISK_USAGE

CHECK_NAME = CHECK_LABEL_DISK_USAGE


def check_dataset(dataset_dir: Path, root: Path) -> list[dict]:
    """Walk one dataset dir and return just this check's slice of the shared
    deep walk (common.deep_walk.walk_dataset also computes ownership_permissions/
    stray_files/dataset_disk_usage_sanity findings in the same pass --
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
