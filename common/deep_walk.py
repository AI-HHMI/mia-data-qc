"""Shared single-pass corpus traversal for "deep-walk" checks -- checks that need
to visit every file/directory under a dataset, not just a top-level listing
(today: ownership_permissions, stray_files, label_disk_usage_sanity,
dataset_disk_usage_sanity). walk_dataset() does ONE os.walk per dataset dir and
returns every registered check's findings from that one pass, so adding another
deep-walk check later doesn't cost the corpus another full walk.

Each individual check script (checks/ownership_permissions.py, checks/stray_files.py,
checks/label_disk_usage_sanity.py, checks/dataset_disk_usage_sanity.py) still runs
standalone by calling this same function and keeping only its own slice of the
result -- useful for the synthetic/single-dataset testing each check gets before
being trusted. The actual corpus-wide production run should go through
checks/run_deep_walk_checks.py instead, which writes every check's report from one
walk per dataset.
"""
import grp
import os
import re
import stat
from pathlib import Path

CHECK_PERMISSIONS = "ownership_permissions"
CHECK_STRAY = "stray_files"
CHECK_LABEL_DISK_USAGE = "label_disk_usage_sanity"
CHECK_DATASET_DISK_USAGE = "dataset_disk_usage_sanity"

# Every one of the corpus's 7,483,957 directories (surveyed Oct 13, 2026, across
# all 139 datasets including the largest Betzig fullvol crops) has exactly this
# apparent size -- `du -sb --apparent-size` is `sum(file st_size) + sum(dir
# st_size)` exactly (verified directly against real `du` output), so this is
# really a check that no directory's own inode size has drifted from every
# other directory on the corpus, not a guess at what "normal" looks like.
EXPECTED_DIR_SIZE = 4096

_RUNG_RE = re.compile(r"^s\d+$")
JUNK_FILE_SUFFIXES = {".log", ".err", ".sh"}
JUNK_DIR_NAMES = {"output"}


def check_entry_permissions(entry: Path, root: Path, expected_gid: int, expected_group: str) -> list[dict]:
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
            "check": CHECK_PERMISSIONS, "dataset": dataset, "path": str(rel), "field": "group",
            "actual": actual_group, "expected": expected_group, "severity": "error",
            "suggested_fix": f"chgrp {expected_group} {entry}",
        })

    mode = st.st_mode
    if not (mode & stat.S_IRGRP):
        findings.append({
            "check": CHECK_PERMISSIONS, "dataset": dataset, "path": str(rel), "field": "group_read",
            "actual": "missing", "expected": "present", "severity": "error",
            "suggested_fix": f"chmod g+r {entry}",
        })
    if not (mode & stat.S_IXGRP):
        findings.append({
            "check": CHECK_PERMISSIONS, "dataset": dataset, "path": str(rel), "field": "group_execute",
            "actual": "missing", "expected": "present", "severity": "error",
            "suggested_fix": f"chmod g+x {entry}",
        })
    if mode & stat.S_IWGRP:
        findings.append({
            "check": CHECK_PERMISSIONS, "dataset": dataset, "path": str(rel), "field": "group_write",
            "actual": "present", "expected": "missing", "severity": "error",
            "suggested_fix": f"chmod g-w {entry}",
        })

    return findings


def _looks_like_label(entry_path: Path, dirnames_by_path: dict) -> bool:
    child_dirnames = dirnames_by_path.get(entry_path)
    if child_dirnames is None:
        return False
    return any(_RUNG_RE.match(d) for d in child_dirnames)


def _is_job_output_junk(entry_path: Path, filenames_by_path: dict) -> bool:
    if entry_path.name in JUNK_DIR_NAMES:
        return True
    child_filenames = filenames_by_path.get(entry_path, [])
    return any(Path(f).suffix in JUNK_FILE_SUFFIXES for f in child_filenames)


def _owning_label_root(dir_path: Path, dataset_dir: Path):
    """If dir_path is a label dir or sits somewhere under one
    (`.../labels/<name>/...`), return that label dir's own path; else None."""
    rel_parts = dir_path.relative_to(dataset_dir).parts
    if "labels" in rel_parts:
        idx = rel_parts.index("labels")
        if len(rel_parts) > idx + 1:
            return dataset_dir.joinpath(*rel_parts[: idx + 2])
    return None


def _disk_usage_finding(check_name: str, dataset_name: str, context_path: Path, root: Path,
                         anomalies: list) -> list[dict]:
    if not anomalies:
        return []
    sample = "; ".join(f"{p.relative_to(root)}={sz}B" for p, sz in anomalies[:5])
    more = f" (+{len(anomalies) - 5} more)" if len(anomalies) > 5 else ""
    return [{
        "check": check_name, "dataset": dataset_name, "path": str(context_path.relative_to(root)),
        "field": "directory_apparent_size",
        "actual": f"{len(anomalies)} director{'y' if len(anomalies) == 1 else 'ies'} with non-4096B "
                  f"apparent size: {sample}{more}",
        "expected": f"every directory's own apparent size is {EXPECTED_DIR_SIZE} bytes "
                    "(true for all 7.48M directories surveyed corpus-wide, Oct 13 2026)",
        "severity": "error",
        "suggested_fix": "investigate the listed director(y/ies) directly -- an inode size differing "
                          "from the rest of the corpus means `du` and a file-byte-sum would disagree "
                          "by more than the usual per-directory overhead",
    }]


def walk_dataset(dataset_dir: Path, root: Path, expected_gid: int = None, expected_group: str = None) -> dict:
    """One os.walk over dataset_dir; returns {check_name: [findings]} for every
    deep-walk check registered here. Pass expected_gid/expected_group to also get
    permissions findings; omit them (e.g. a stray_files-only standalone run) to
    skip that check's work entirely rather than compute and discard it.
    """
    perm_findings = []
    stray_findings = []

    # First pass: collect dirnames/filenames per directory so the labels/ junk
    # check (which needs a directory's *children* to classify it) can look them
    # up without a second walk.
    dirnames_by_path = {}
    filenames_by_path = {}
    all_dirs = [dataset_dir]
    all_files = []

    for dirpath, dirnames, filenames in os.walk(dataset_dir):
        dirpath = Path(dirpath)
        dirnames_by_path[dirpath] = dirnames
        filenames_by_path[dirpath] = filenames
        for d in dirnames:
            all_dirs.append(dirpath / d)
        for f in filenames:
            all_files.append(dirpath / f)

        if dirpath.name == ".DS_Store":
            continue  # not a real path, just guarding against a pathological name
        if ".DS_Store" in filenames:
            rel = str((dirpath / ".DS_Store").relative_to(root))
            stray_findings.append({
                "check": CHECK_STRAY, "dataset": dataset_dir.name, "path": rel, "field": "ds_store",
                "actual": ".DS_Store", "expected": "no .DS_Store files under data/", "severity": "error",
                "suggested_fix": f"rm {dirpath / '.DS_Store'}",
            })

        if dirpath.name == "labels":
            for d in dirnames:
                entry_path = dirpath / d
                if _looks_like_label(entry_path, dirnames_by_path):
                    continue
                if _is_job_output_junk(entry_path, filenames_by_path):
                    rel = str(entry_path.relative_to(root))
                    stray_findings.append({
                        "check": CHECK_STRAY, "dataset": dataset_dir.name, "path": rel,
                        "field": "stray_label_junk", "actual": d,
                        "expected": "no job-output leftovers inside labels/", "severity": "error",
                        "suggested_fix": f"rm -rf {entry_path}",
                    })

    if expected_gid is not None:
        for entry in all_dirs + all_files:
            try:
                perm_findings.extend(check_entry_permissions(entry, root, expected_gid, expected_group))
            except OSError:
                continue

    # Disk-usage sanity: every directory's own apparent size should be
    # EXPECTED_DIR_SIZE (see the constant's docstring) -- bucket anomalies by
    # the label they fall under (mia_annotation tracks per-label) and
    # separately for the whole dataset (mia_pretraining tracks per-dataset,
    # since some issues cover a whole multi-crop dataset with no per-crop
    # issue at all).
    dataset_anomalies = []
    label_anomalies = {}
    for d in all_dirs:
        try:
            size = d.stat().st_size
        except OSError:
            continue
        if size == EXPECTED_DIR_SIZE:
            continue
        dataset_anomalies.append((d, size))
        label_root = _owning_label_root(d, dataset_dir)
        if label_root is not None:
            label_anomalies.setdefault(label_root, []).append((d, size))

    label_disk_findings = []
    for label_root, anomalies in label_anomalies.items():
        label_disk_findings.extend(
            _disk_usage_finding(CHECK_LABEL_DISK_USAGE, dataset_dir.name, label_root, root, anomalies)
        )
    dataset_disk_findings = _disk_usage_finding(
        CHECK_DATASET_DISK_USAGE, dataset_dir.name, dataset_dir, root, dataset_anomalies
    )

    return {
        CHECK_PERMISSIONS: perm_findings,
        CHECK_STRAY: stray_findings,
        CHECK_LABEL_DISK_USAGE: label_disk_findings,
        CHECK_DATASET_DISK_USAGE: dataset_disk_findings,
    }
