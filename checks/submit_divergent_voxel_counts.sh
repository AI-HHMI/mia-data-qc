#!/bin/bash
# Submit divergent_voxel_counts.py as an LSF job -- needs pixi's zarr/numpy
# env (real pixel reads, unlike every other check in this repo) and can run
# long (up to ~20s per label seen in testing, hundreds of labels to check).
#
# Usage: submit_divergent_voxel_counts.sh [wall_time] [root] [reports_dir]
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WALL_TIME="${1:-24:00}"
ROOT="${2:-/groups/miaai/miaai/lmd-v0.0.1/data}"
REPORTS_DIR="${3:-$REPO_DIR/reports}"
MEM_MB=$((1 * 15 * 1024))

mkdir -p "$REPO_DIR/logs"

bsub -J "mia_qc_divergent_voxels" -P miaai -q local \
  -n 1 -W "$WALL_TIME" \
  -M "${MEM_MB}" -R "rusage[mem=${MEM_MB}]" \
  -o "$REPO_DIR/logs/divergent_voxel_counts_%J.log" -e "$REPO_DIR/logs/divergent_voxel_counts_%J.err" \
  "cd $REPO_DIR && pixi run python3 checks/divergent_voxel_counts.py --root $ROOT --reports-dir $REPORTS_DIR"
