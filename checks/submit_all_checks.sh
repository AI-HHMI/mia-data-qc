#!/bin/bash
# Submit a full corpus-wide run of every check (run_all_checks.py) as an LSF
# job. Same resource shape as submit_deep_walk_checks.sh since the deep-walk
# pass is the bottleneck here too.
#
# Usage: submit_all_checks.sh [cores] [wall_time] [root] [reports_dir]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORES="${1:-8}"
WALL_TIME="${2:-24:00}"
ROOT="${3:-/groups/miaai/miaai/lmd-v0.0.1/data}"
REPORTS_DIR="${4:-$REPO_DIR/reports}"
MEM_MB=$((CORES * 15 * 1024))

mkdir -p "$REPO_DIR/logs"

bsub -J "mia_qc_all_${CORES}c" -P miaai -q local \
  -n "$CORES" -W "$WALL_TIME" \
  -M "${MEM_MB}" -R "rusage[mem=${MEM_MB}]" \
  -o "$REPO_DIR/logs/all_checks_%J.log" -e "$REPO_DIR/logs/all_checks_%J.err" \
  "cd $REPO_DIR && python3 checks/run_all_checks.py --root $ROOT --workers $CORES --reports-dir $REPORTS_DIR"
