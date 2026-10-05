#!/bin/bash
# Submit the ownership/permissions check as an LSF job. Never run this check
# interactively on a login node against the full corpus -- it's an I/O-bound
# walk over every file under data/, same reasoning as lmd-configs/describe.py's
# disk-size mode (see lmvd_stats_reporting.md).
#
# Usage: submit_ownership_check.sh [cores] [wall_time] [root] [reports_dir]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORES="${1:-8}"
WALL_TIME="${2:-24:00}"
ROOT="${3:-/groups/miaai/miaai/lmd-v0.0.1/data}"
REPORTS_DIR="${4:-$REPO_DIR/reports}"
MEM_MB=$((CORES * 15 * 1024))

mkdir -p "$REPO_DIR/logs"

# -q local: this is a fine-grained per-file lstat walk (not the coarser store-level
# disk-usage calls describe.py does), so it can run well past the "short" queue's
# 61-min cap -- "short" killed 3 earlier attempts with zero output since the old
# code only wrote its report once, at the very end. local allows up to 14 days.
bsub -J "mia_qc_ownership_${CORES}c" -P miaai -q local \
  -n "$CORES" -W "$WALL_TIME" \
  -M "${MEM_MB}" -R "rusage[mem=${MEM_MB}]" \
  -o "$REPO_DIR/logs/ownership_%J.log" -e "$REPO_DIR/logs/ownership_%J.err" \
  "cd $REPO_DIR && /usr/bin/time -v python3 checks/ownership_permissions.py --root $ROOT --group miaai --workers $CORES --reports-dir $REPORTS_DIR"
