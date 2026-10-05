#!/usr/bin/env python3
"""Check: every file and folder under --root (default data/) is group miaai,
and group permissions are read+execute but not write — for the root itself
and every file/folder nested under it, however deep.
"""
import argparse
import grp
import os
import stat
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.report import write_check_report

CHECK_NAME = "ownership_permissions"


def _check_entry(entry: Path, root: Path, expected_gid: int, expected_group: str) -> list[dict]:
    st = entry.lstat()
    rel = entry.relative_to(root)
    dataset = rel.parts[0] if rel.parts else "."
    findings = []

    if st.st_gid != expected_gid:
        try:
            actual_group = grp.getgrgid(st.st_gid).gr_name
        except KeyError:
            actual_group = str(st.st_gid)
        findings.append({
            "check": CHECK_NAME,
            "dataset": dataset,
            "path": str(rel),
            "field": "group",
            "actual": actual_group,
            "expected": expected_group,
            "severity": "error",
            "suggested_fix": f"chgrp {expected_group} {entry}",
        })

    mode = st.st_mode
    if not (mode & stat.S_IRGRP):
        findings.append({
            "check": CHECK_NAME,
            "dataset": dataset,
            "path": str(rel),
            "field": "group_read",
            "actual": "missing",
            "expected": "present",
            "severity": "error",
            "suggested_fix": f"chmod g+r {entry}",
        })
    if not (mode & stat.S_IXGRP):
        findings.append({
            "check": CHECK_NAME,
            "dataset": dataset,
            "path": str(rel),
            "field": "group_execute",
            "actual": "missing",
            "expected": "present",
            "severity": "error",
            "suggested_fix": f"chmod g+x {entry}",
        })
    if mode & stat.S_IWGRP:
        findings.append({
            "check": CHECK_NAME,
            "dataset": dataset,
            "path": str(rel),
            "field": "group_write",
            "actual": "present",
            "expected": "missing",
            "severity": "error",
            "suggested_fix": f"chmod g-w {entry}",
        })

    return findings


def _walk_subtree(subtree: Path, root: Path, expected_gid: int, expected_group: str) -> list[dict]:
    """Walk one directory (e.g. one dataset dir under data/) and check every entry in it."""
    findings = _check_entry(subtree, root, expected_gid, expected_group)
    for dirpath, dirnames, filenames in os.walk(subtree):
        dirpath = Path(dirpath)
        for name in dirnames + filenames:
            entry = dirpath / name
            try:
                findings.extend(_check_entry(entry, root, expected_gid, expected_group))
            except OSError:
                continue
    return findings


def iter_dataset_findings(root: Path, expected_group: str, workers: int = 1):
    """Yield (dataset_name, findings) for each immediate child of root as it completes.

    With workers > 1, subtrees (e.g. dataset dirs) are walked concurrently by threads —
    this is an I/O-bound walk (just lstat calls), so threads help despite the GIL since
    each blocks on a syscall, not CPU work. Yielding per-subtree (instead of returning one
    big list at the end) is what lets the caller print progress and flush partial reports
    as a long corpus-wide run proceeds.
    """
    try:
        expected_gid = grp.getgrnam(expected_group).gr_gid
    except KeyError:
        raise SystemExit(f"Unknown group: {expected_group!r}")

    pre_findings = list(_check_entry(root, root, expected_gid, expected_group))

    subtrees = sorted(p for p in root.iterdir() if p.is_dir())
    direct_files = sorted(p for p in root.iterdir() if not p.is_dir())
    for f in direct_files:
        pre_findings.extend(_check_entry(f, root, expected_gid, expected_group))
    yield ("(root + direct files)", pre_findings, False)

    if workers <= 1:
        for subtree in subtrees:
            yield (subtree.name, _walk_subtree(subtree, root, expected_gid, expected_group), True)
    else:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_to_name = {
                pool.submit(_walk_subtree, s, root, expected_gid, expected_group): s.name
                for s in subtrees
            }
            for future in as_completed(future_to_name):
                yield (future_to_name[future], future.result(), True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="data", help="Directory to scan, recursively (default: data)")
    parser.add_argument("--group", default="miaai", help="Expected group (default: miaai)")
    parser.add_argument("--reports-dir", default="reports", help="Where to write dated reports (default: reports)")
    parser.add_argument("--workers", type=int, default=1,
                         help="Thread count for walking root's immediate subdirs in parallel "
                              "(I/O-bound; match to -n when submitting via bsub, default: 1)")
    parser.add_argument("--flush-every", type=int, default=10,
                         help="Write a partial report every N completed dataset dirs, so a long "
                              "run's report reflects live progress (default: 10)")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    if not root.is_dir():
        raise SystemExit(f"Not a directory: {root}")

    total = sum(1 for p in root.iterdir() if p.is_dir())
    reports_dir = Path(args.reports_dir)

    findings = []
    done = 0
    for name, subtree_findings, is_dataset in iter_dataset_findings(root, args.group, workers=args.workers):
        findings.extend(subtree_findings)
        if is_dataset:
            done += 1
            print(f"{CHECK_NAME}: {done}/{total} checked ({name}) — {len(findings)} finding(s) so far", flush=True)
        else:
            print(f"{CHECK_NAME}: {name} — {len(findings)} finding(s) so far", flush=True)
        if done % args.flush_every == 0:
            write_check_report(CHECK_NAME, findings, reports_dir=reports_dir)

    write_check_report(CHECK_NAME, findings, reports_dir=reports_dir)

    print(f"{CHECK_NAME}: done — {len(findings)} violation(s) under {root}")
    if findings:
        sys.exit(1)


if __name__ == "__main__":
    main()
