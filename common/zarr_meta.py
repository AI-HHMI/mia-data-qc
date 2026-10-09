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
