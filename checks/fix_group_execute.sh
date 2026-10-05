#!/bin/bash
# Apply chmod g+x to every file missing it, under each directory given.
# This is the one systemic fix found by ownership_permissions.py's Oct 5 2026
# corpus run (8,950,233 of 8,950,234 findings were exactly this). Matches the
# check's own predicate (group-execute missing) directly via find, rather than
# replaying the check's report -- so it stays correct even if the report format
# changes later.
#
# Usage: fix_group_execute.sh <dir> [<dir> ...]
set -euo pipefail

for d in "$@"; do
  if [ ! -d "$d" ]; then
    echo "Skipping (not a directory): $d" >&2
    continue
  fi
  before=$(find "$d" -not -perm -g+x | wc -l)
  echo "$d: $before entries missing group-execute"
  find "$d" -not -perm -g+x -print0 | xargs -0 --no-run-if-empty chmod g+x
  after=$(find "$d" -not -perm -g+x | wc -l)
  echo "$d: $after remaining after fix"
done
