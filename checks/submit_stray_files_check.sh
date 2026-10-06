#!/bin/bash
# Submit the stray-files check as an LSF job (same reasoning as
# submit_ownership_check.sh -- don't run a corpus-wide walk on a login node).
#
# Usage: submit_stray_files_check.sh [cores] [wall_time] [root] [reports_dir]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORES="${1:-8}"
WALL_TIME="${2:-24:00}"
ROOT="${3:-/groups/miaai/miaai/lmd-v0.0.1/data}"
REPORTS_DIR="${4:-$REPO_DIR/reports}"
MEM_MB=$((CORES * 15 * 1024))

mkdir -p "$REPO_DIR/logs"

bsub -J "mia_qc_stray_${CORES}c" -P miaai -q local \
  -n "$CORES" -W "$WALL_TIME" \
  -M "${MEM_MB}" -R "rusage[mem=${MEM_MB}]" \
  -o "$REPO_DIR/logs/stray_%J.log" -e "$REPO_DIR/logs/stray_%J.err" \
  "cd $REPO_DIR && python3 checks/stray_files.py --root $ROOT --workers $CORES --reports-dir $REPORTS_DIR"
