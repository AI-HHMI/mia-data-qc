#!/usr/bin/env python3
"""Production entry point for every "deep-walk" check (checks that need to visit
every file/directory under a dataset, not just a top-level listing) -- currently
ownership_permissions and stray_files. Walks the corpus ONCE per dataset dir and
writes both checks' reports from that single pass, instead of each check walking
the whole corpus on its own.

Individual check scripts (checks/ownership_permissions.py, checks/stray_files.py)
still run standalone for development/testing against a scratch directory or a
single dataset -- this script is for real corpus-wide runs (cron/bsub).
"""
import argparse
import datetime
import grp
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.report import write_check_report
from common.vocab import NON_DATASET_DIRS
from common.deep_walk import walk_dataset, check_entry_permissions, CHECK_PERMISSIONS, CHECK_STRAY


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="data", help="Directory to scan, recursively (default: data)")
    parser.add_argument("--group", default="miaai", help="Expected group for ownership_permissions (default: miaai)")
    parser.add_argument("--reports-dir", default="reports", help="Where to write dated reports (default: reports)")
    parser.add_argument("--workers", type=int, default=1,
                         help="Thread count for walking dataset dirs in parallel "
                              "(I/O-bound; match to -n when submitting via bsub, default: 1)")
    parser.add_argument("--flush-every", type=int, default=10,
                         help="Write partial reports every N completed dataset dirs (default: 10)")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    try:
        expected_gid = grp.getgrnam(args.group).gr_gid
    except KeyError:
        raise SystemExit(f"Unknown group: {args.group!r}")

    datasets = sorted(p for p in root.iterdir() if p.is_dir() and p.name not in NON_DATASET_DIRS)
    total = len(datasets)
    reports_dir = Path(args.reports_dir)
    # Pinned once so a run spanning midnight doesn't split its own report across two
    # date folders -- every write_check_report() call below uses this same date.
    run_date = datetime.date.today().isoformat()

    findings = {CHECK_PERMISSIONS: [], CHECK_STRAY: []}
    done = 0

    # Root itself + any files directly under it (not inside any dataset dir) --
    # same pre-check ownership_permissions.py does standalone.
    findings[CHECK_PERMISSIONS].extend(check_entry_permissions(root, root, expected_gid, args.group))
    for f in sorted(p for p in root.iterdir() if not p.is_dir()):
        findings[CHECK_PERMISSIONS].extend(check_entry_permissions(f, root, expected_gid, args.group))

    def flush():
        for check_name, check_findings in findings.items():
            write_check_report(check_name, check_findings, reports_dir=reports_dir, date=run_date)

    def handle_result(name, result):
        nonlocal done
        for check_name, check_findings in result.items():
            findings[check_name].extend(check_findings)
        done += 1
        total_so_far = sum(len(v) for v in findings.values())
        print(f"deep_walk: {done}/{total} checked ({name}) — {total_so_far} finding(s) so far", flush=True)
        if done % args.flush_every == 0:
            flush()

    if args.workers <= 1:
        for d in datasets:
            handle_result(d.name, walk_dataset(d, root, expected_gid, args.group))
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            future_to_name = {
                pool.submit(walk_dataset, d, root, expected_gid, args.group): d.name
                for d in datasets
            }
            for future in as_completed(future_to_name):
                handle_result(future_to_name[future], future.result())

    flush()
    total_findings = sum(len(v) for v in findings.values())
    for check_name, check_findings in findings.items():
        print(f"deep_walk: {check_name} — {len(check_findings)} finding(s)")
    print(f"deep_walk: done — {total_findings} finding(s) total under {root}")
    if total_findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
