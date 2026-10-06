#!/bin/bash
# Submit the combined deep-walk check run (ownership_permissions + stray_files,
# one walk) as an LSF job. This is the real production entry point for these two
# checks -- don't submit submit_ownership_check.sh and submit_stray_files_check.sh
# separately for a corpus-wide run, that walks the corpus twice for no reason.
#
# Usage: submit_deep_walk_checks.sh [cores] [wall_time] [root] [reports_dir]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CORES="${1:-8}"
WALL_TIME="${2:-24:00}"
ROOT="${3:-/groups/miaai/miaai/lmd-v0.0.1/data}"
REPORTS_DIR="${4:-$REPO_DIR/reports}"
MEM_MB=$((CORES * 15 * 1024))

mkdir -p "$REPO_DIR/logs"

bsub -J "mia_qc_deep_walk_${CORES}c" -P miaai -q local \
  -n "$CORES" -W "$WALL_TIME" \
  -M "${MEM_MB}" -R "rusage[mem=${MEM_MB}]" \
  -o "$REPO_DIR/logs/deep_walk_%J.log" -e "$REPO_DIR/logs/deep_walk_%J.err" \
  "cd $REPO_DIR && python3 checks/run_deep_walk_checks.py --root $ROOT --group miaai --workers $CORES --reports-dir $REPORTS_DIR"
