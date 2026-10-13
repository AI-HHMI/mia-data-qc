#!/bin/bash
# Submit annotated_voxels_sanity.py as an LSF job -- needs pixi's zarr/numpy
# env (real pixel reads, unlike most checks in this repo) and visits every
# real label corpus-wide, each an exact-count attempt (cost-gated).
#
# Usage: submit_annotated_voxels_sanity.sh [wall_time] [root] [reports_dir]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WALL_TIME="${1:-24:00}"
ROOT="${2:-/groups/miaai/miaai/lmd-v0.0.1/data}"
REPORTS_DIR="${3:-$REPO_DIR/reports}"
MEM_MB=$((1 * 15 * 1024))

mkdir -p "$REPO_DIR/logs"

bsub -J "mia_qc_annotated_voxels" -P miaai -q local \
  -n 1 -W "$WALL_TIME" \
  -M "${MEM_MB}" -R "rusage[mem=${MEM_MB}]" \
  -o "$REPO_DIR/logs/annotated_voxels_sanity_%J.log" -e "$REPO_DIR/logs/annotated_voxels_sanity_%J.err" \
  "cd $REPO_DIR && pixi run python3 checks/annotated_voxels_sanity.py --root $ROOT --reports-dir $REPORTS_DIR"
