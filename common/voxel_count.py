"""Exact non-zero voxel counting, ported from the worklog repo's
`scripts/lmvd_plots/measure_labels.py` (`nonzero_voxels()`) -- same
algorithm, not reimplemented differently. Needs `zarr`/`numpy`
(`pixi.toml`), unlike every other `common/` module -- isolated here so the
dependency stays scoped to the one or two checks that actually need real
pixel data, not the other ~20 metadata-only checks.

Cost-gated the same way that pipeline gates it: only attempt an exact
read when the label is small enough on disk, small enough decompressed,
and spans few enough chunks -- a label's declared shape can vastly
overstate its real size (zarr never writes an all-empty chunk), so
`common.zarr_meta.written_chunk_bounds()` narrows the scan to the
written-chunk bounding box first, which is what makes the exact pass
affordable even when the declared array is huge.
"""
from pathlib import Path

from common.zarr_meta import read_array_meta, written_chunk_bounds

DTYPE_BYTES = {
    "uint8": 1, "int8": 1, "uint16": 2, "int16": 2,
    "uint32": 4, "int32": 4, "float32": 4, "float64": 8,
}

# Same thresholds as measure_labels.py's --exact-max-bytes / --exact-max-decompressed-bytes /
# --exact-max-chunks defaults.
MAX_DISK_BYTES = 2e9
MAX_DECOMPRESSED_BYTES = 8e11
MAX_CHUNKS = 2e5


def _dir_bytes(path: Path) -> int:
    total = 0
    for p in path.rglob("*"):
        if p.is_file():
            try:
                total += p.stat().st_size
            except OSError:
                pass
    return total


def exact_nonzero_count(label_s0_dir: Path):
    """Exact non-zero voxel count for one label's finest pyramid level, or
    None if it's too large to read affordably (any of the three gates
    fails) or its metadata/chunks can't be read at all. Never attempts a
    full-array read -- only ever reads within the written-chunk bbox.
    """
    disk_bytes = _dir_bytes(label_s0_dir)
    if disk_bytes > MAX_DISK_BYTES:
        return None

    meta = read_array_meta(label_s0_dir)
    if meta is None:
        return None

    bounds = written_chunk_bounds(label_s0_dir)
    if bounds is None:
        return 0  # no chunks written at all -- a real, cheap, exact answer

    elem_bounds = bounds["elem_bounds"]
    bbox_voxels = 1
    for lo, hi in elem_bounds:
        bbox_voxels *= (hi - lo)

    dtype_bytes = DTYPE_BYTES.get(meta.get("dtype"), 4)
    if bbox_voxels * dtype_bytes > MAX_DECOMPRESSED_BYTES:
        return None

    file_chunk_shape = meta.get("shard_shape") or meta.get("chunk_shape")
    n_chunks = 1
    for (lo, hi), c in zip(elem_bounds, file_chunk_shape):
        n_chunks *= -(-(hi - lo) // c)  # ceil division
    if n_chunks > MAX_CHUNKS:
        return None

    import numpy as np
    import zarr

    array = zarr.open_array(str(label_s0_dir), mode="r")
    count = 0
    step = array.chunks
    ranges = [range(lo, hi, c) for (lo, hi), c in zip(elem_bounds, step)]

    def walk(dim, sl):
        nonlocal count
        if dim == len(array.shape):
            count += int(np.count_nonzero(array[tuple(sl)]))
            return
        for start in ranges[dim]:
            walk(dim + 1, sl + [slice(start, min(start + step[dim], array.shape[dim]))])

    walk(0, [])
    return count
