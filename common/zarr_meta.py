"""Read zarr group/array metadata transparently across zarr v3 (`zarr.json`)
and the legacy zarr v2 layout (`.zattrs` + `.zarray`) still used by 9 labels
and 117 whole crops on this corpus (found Oct 8 2026 -- every check written
before this module silently skipped all of them, since each one's label/crop
discovery filtered on `zarr.json` existing alone).

zarr v3 attributes live under a `"attributes"` wrapper key in `zarr.json`,
with OME-NGFF's `multiscales` nested one level deeper under `"ome"`. zarr v2
attributes are the bare contents of `.zattrs` -- no wrapper, and
`multiscales` sits at the top level, not under `"ome"`.
"""
import json
import os
from pathlib import Path


def group_exists(group_dir: Path) -> bool:
    """True if `group_dir` is a zarr group in either format."""
    return (group_dir / "zarr.json").is_file() or (group_dir / ".zattrs").is_file()


def read_group_attrs(group_dir: Path):
    """Return a group's own attributes dict (zarr v3's `attributes`, or a
    zarr v2 `.zattrs` file's contents directly), or None if neither format is
    present or unreadable.
    """
    zarr_json = group_dir / "zarr.json"
    if zarr_json.is_file():
        try:
            return json.loads(zarr_json.read_text()).get("attributes", {})
        except (OSError, json.JSONDecodeError):
            return None
    zattrs = group_dir / ".zattrs"
    if zattrs.is_file():
        try:
            return json.loads(zattrs.read_text())
        except (OSError, json.JSONDecodeError):
            return None
    return None


def get_multiscale(attrs: dict):
    """Return the first OME-NGFF multiscale entry (`{"axes": [...], "datasets": [...]}`)
    from an already-read attributes dict, whichever nesting convention it uses.
    """
    if attrs is None:
        return None
    multiscales = attrs.get("ome", {}).get("multiscales") or attrs.get("multiscales")
    if not multiscales:
        return None
    return multiscales[0]


def read_array_meta(array_dir: Path):
    """Return a normalized dict for one pyramid-level array:
    `{"shape": [...], "dtype": str, "chunk_shape": [...], "shard_shape": [...] | None}`.
    `shard_shape` is only ever set for a zarr v3 array using the
    `sharding_indexed` codec; zarr v2 has no sharding concept, so it's always
    None there and `chunk_shape` is the array's own `.zarray["chunks"]`.
    Returns None if neither format is present or unreadable.
    """
    zarr_json = array_dir / "zarr.json"
    if zarr_json.is_file():
        try:
            data = json.loads(zarr_json.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        shard_shape = data.get("chunk_grid", {}).get("configuration", {}).get("chunk_shape")
        inner_chunk_shape = None
        for codec in data.get("codecs", []):
            if codec.get("name") == "sharding_indexed":
                inner_chunk_shape = codec.get("configuration", {}).get("chunk_shape")
        return {
            "shape": data.get("shape"),
            "dtype": data.get("data_type"),
            "chunk_shape": inner_chunk_shape or shard_shape,
            "shard_shape": shard_shape if inner_chunk_shape else None,
        }
    zarray = array_dir / ".zarray"
    if zarray.is_file():
        try:
            data = json.loads(zarray.read_text())
        except (OSError, json.JSONDecodeError):
            return None
        return {
            "shape": data.get("shape"),
            "dtype": data.get("dtype"),
            "chunk_shape": data.get("chunks"),
            "shard_shape": None,
            "dimension_separator": data.get("dimension_separator", "."),
        }
    return None


def written_chunk_bounds(array_dir: Path):
    """Ported from `measure_labels.py`'s `written_extent()` (worklog repo,
    `scripts/lmvd_plots/`) -- same algorithm, not reimplemented differently.
    Determines the bounding box of chunks actually written on disk *without
    reading a single pixel*, just by listing chunk file names: zarr never
    writes an all-empty chunk, so the declared array shape can vastly
    overstate where real data lives (a label's shape routinely spans the
    whole parent volume while only a small sub-box carries annotation).

    Walks every file under `array_dir`, strips a leading `"c"` path segment
    (zarr v3's default chunk-key prefix) if present, and reads the chunk
    index either from nested path segments (zarr v3, or zarr v2 with
    `dimension_separator: "/"`) or from a single dot-joined filename (zarr
    v2 with `dimension_separator: "."`) -- both conventions are detected
    automatically from the path shape, not assumed up front.

    The index granularity is the *file* granularity -- for a sharded zarr v3
    array that's the shard shape (one shard is one file), not the finer
    inner chunk shape `read_array_meta()` reports separately.

    Returns `{"elem_bounds": [(lo, hi), ...]}` (per-axis element-space
    bounds, already clipped to the declared shape) or None if the array
    metadata is missing/unreadable or no chunks have been written at all.
    """
    meta = read_array_meta(array_dir)
    if meta is None:
        return None
    shape = meta.get("shape")
    file_chunk_shape = meta.get("shard_shape") or meta.get("chunk_shape")
    if not shape or not file_chunk_shape or len(shape) != len(file_chunk_shape):
        return None
    ndim = len(shape)

    indices = []
    for dirpath, _dirnames, filenames in os.walk(array_dir):
        for name in filenames:
            if name in ("zarr.json", ".zarray", ".zattrs", ".zgroup"):
                continue
            rel = os.path.relpath(os.path.join(dirpath, name), array_dir)
            parts = rel.replace(os.sep, "/").split("/")
            if parts and parts[0] == "c":
                parts = parts[1:]
            if len(parts) == 1:
                parts = parts[0].split(".")
            if len(parts) != ndim:
                continue
            try:
                indices.append(tuple(int(p) for p in parts))
            except ValueError:
                continue

    if not indices:
        return None

    elem_bounds = []
    for d in range(ndim):
        lo = min(i[d] for i in indices) * file_chunk_shape[d]
        hi = min(max(i[d] for i in indices) * file_chunk_shape[d] + file_chunk_shape[d], shape[d])
        elem_bounds.append((lo, hi))
    return {"elem_bounds": elem_bounds}
