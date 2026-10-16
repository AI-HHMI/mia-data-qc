# mia-data-qc

Automated QC checks over the LMD `data/` corpus (`/groups/miaai/miaai/lmd-v0.0.1/data`), run on
the Janelia cluster and published as a static-HTML report site.

**Live reports: https://ai-hhmi.github.io/mia-data-qc/qc_dashboard.html**

## Layout

- `checks/` — one script per check, plus its `bsub` submit wrapper. Each check is independently
  runnable for development/testing against a scratch directory or a single dataset.
- `common/` — shared code: `report.py` (JSON+HTML report writer, dated index pages),
  `vocab.py` (controlled vocabularies for dataset/organism/label-class naming, single source of
  truth), `deep_walk.py` (shared single-pass corpus traversal for checks that need to visit every
  file), `zarr_meta.py` (zarr v2/v3-transparent metadata reads, no dependency beyond stdlib),
  `github.py` (read-only GitHub Projects v2 board fetch via the `gh` CLI).
- `reports/` — `reports/<date>/` per run; `qc_dashboard.html` at the repo root lists dates
  newest-first with finding counts.

## Checks implemented so far

Grouped by what each check actually validates (purely a reading aid — every check still runs and
reports independently; see `common/report.py`'s `CHECK_CATEGORIES` for the single source of truth
the dashboard uses too).

### Filesystem & permissions

| Check | What it checks |
|---|---|
| `ownership_permissions.py` | Every file/dir under `data/` is group `miaai`, group-read, group-execute, no group-write |
| `stray_files.py` | Flags leftover junk (`.DS_Store` files, old job logs) that shouldn't be sitting inside the data folders |
| `label_disk_usage_sanity.py` | Flags a label's folder if its disk footprint looks abnormal compared to every other folder on the corpus — a sign something's corrupted or unusual |
| `dataset_disk_usage_sanity.py` | Flags a dataset's folders if their disk footprint looks abnormal compared to every other folder on the corpus — a sign something's corrupted or unusual |

### Naming conventions

| Check | What it checks |
|---|---|
| `dataset_naming.py` | Every dataset's folder name follows the standard pattern (modality-organism-dataset) and uses approved terms |
| `label_naming.py` | `{provenance}-{label_class}-{specific_info}` for every label dir |
| `crop_naming.py` | Every crop's folder name follows the standard `crop-NNN` pattern |
| `multitc_naming.py` | A crop with more than one timepoint/channel in its raw array encodes that as `{N}t_{M}c` in its descriptor |

### Zarr structure validity

| Check | What it checks |
|---|---|
| `pyramid_consistency.py` | Each zarr.json's `multiscales.datasets` list matches what pyramid levels actually exist on disk |
| `metadata_consistency.py` | A label's directory-name-derived provenance/label_class agrees with its own stored metadata |
| `chunk_shard_sanity.py` | Every sharded array's shard shape is an exact multiple of its own chunk shape |
| `parent_raw_validity.py` | A label's `parent_raw` field (when present) points to a directory that actually exists |
| `channel_index_consistency.py` | A label pulled from one channel of a multi-channel image correctly records which channel it came from |
| `multitimepoint_label_sparsity.py` | A single-timepoint label is sized to match the full time series but only has actual content where it's supposed to — at its one timepoint |
| `empty_label_data.py` | A label with complete metadata actually has chunk data written at its finest pyramid level |
| `bbox_sanity.py` | A label's bbox has a valid coordinate_order/unit and a structurally sane offset/size |

### Metadata content & vocabulary

| Check | What it checks |
|---|---|
| `metadata_vocab.py` | A label's segmentation type, proofreading status, and coverage use only approved, recognized values |
| `metadata_completeness.py` | Every label's zarr.json has all 12 required metadata fields present (label_class, segmentation_type, provenance, proofreading_status, coverage, bbox, source, created, parent_raw, dataset, publication, notes) |
| `voxel_size.py` | Raw's voxel size isn't a placeholder; each label's voxel size aligns with raw's pyramid |
| `license_fields.py` | Every crop has a `license` field present on both its root `zarr.json` and `raw/zarr.json` |
| `freshness.py` | A label's creation date is valid, and when multiple versions of the same label exist, the one marked "current" really is the newest |

### Board vs. disk (`mia_annotation` / `mia_pretraining`)

| Check | What it checks |
|---|---|
| `label_field_drift.py` | A label's tracking issue on GitHub shows the same info as what's actually stored with the label on disk (warning only — either side can be stale) |
| `dataset_field_drift.py` | A dataset's tracking issue on GitHub shows the same axis order and data type as what's actually on disk |
| `label_orphaned_ingest.py` | Every real label has a GitHub issue tracking it, and every GitHub issue marked done actually has real data behind it |
| `dataset_orphaned_ingest.py` | Every real dataset has at least one GitHub issue tracking it |
| `dataset_crop_coverage.py` | Every crop in a multi-crop dataset is tracked by a GitHub issue — either its own, or one covering the whole dataset |

### Pixel-data sanity

| Check | What it checks |
|---|---|
| `divergent_voxel_counts.py` | Two different versions of the same labeled region (e.g. a manual annotation vs. an automated one) have wildly different amounts of annotated data — worth a second look |
| `annotated_voxels_sanity.py` | A label's annotated data can't be bigger than the image it's supposed to fit inside — flags it if the numbers don't add up |

The original design proposal and open questions: [issue #1](https://github.com/AI-HHMI/mia-data-qc/issues/1).

## Running a check

Each check runs standalone, e.g.:
```bash
python3 checks/dataset_naming.py --root /groups/miaai/miaai/lmd-v0.0.1/data
```

Every check above is pure stdlib — no setup beyond Python itself. A small number of checks that
need to decode real pixel data (not just metadata) need `zarr`/`numpy`, pinned in `pixi.toml`
(same `zarr>=3.1.1,<4` TensorSwitch uses, since zarr-python 2.x can't open this corpus's zarr v3
stores). Run those via `pixi run python3 checks/<name>.py ...` instead of bare `python3`.

Checks that walk every file under `data/` (`ownership_permissions.py`, `stray_files.py`,
`label_disk_usage_sanity.py`, `dataset_disk_usage_sanity.py`) should be submitted as an LSF job,
never run on a login node — use the matching `submit_*.sh` script, or `submit_deep_walk_checks.sh`
to run all four from a single corpus walk (the real production entry point for those four —
`run_deep_walk_checks.py`). Shallow checks (naming, pyramid consistency, metadata consistency) run
in seconds and don't need a cluster job.

**New-check convention**: if a new check needs a deep, file-level walk (visiting every chunk, not
just dataset/crop/label directories), pair it with the existing deep-walk checks in
`run_deep_walk_checks.py` so the corpus is only walked once — a second independent deep walk would
double the actual expensive cost. Shallow checks don't need this: each one listing
dataset→crop→label directories independently (as `checks/run_all_checks.py` does when running
everything) costs seconds in aggregate, not worth merging into a shared traversal.

Cluster convention: `bsub -q local -P miaai`, no host pinned (let LSF's scheduler pick), `-n`
matched to `--workers`, memory `cores * 15GB` per the cluster's per-core memory policy.
