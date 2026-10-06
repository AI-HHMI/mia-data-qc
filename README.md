# mia-data-qc

Automated QC checks over the LMD `data/` corpus (`/groups/miaai/miaai/lmd-v0.0.1/data`), run on
the Janelia cluster and published as a static-HTML report site.

**Live reports: https://ai-hhmi.github.io/mia-data-qc/qc_dashboard.html**

## Layout

- `checks/` — one script per check, plus its `bsub` submit wrapper. Each check is independently
  runnable for development/testing against a scratch directory or a single dataset.
- `common/` — shared code: `report.py` (JSON+HTML report writer, dated index pages),
  `vocab.py` (controlled vocabularies from `lmvd_structure_guideline.md`, single source of truth),
  `deep_walk.py` (shared single-pass corpus traversal for checks that need to visit every file).
- `reports/` — `reports/<date>/` per run; `qc_dashboard.html` at the repo root lists dates
  newest-first with finding counts.
- `fixes/` — **local-only, gitignored**. One-time remediation scripts (e.g. bulk permission
  fixes) are deliberately kept out of the repo, since they're not part of the standing QC system.

## Checks implemented so far

| Check | What it checks |
|---|---|
| `ownership_permissions.py` | Every file/dir under `data/` is group `miaai`, group-read, group-execute, no group-write |
| `dataset_naming.py` | `{modality}-{organism}-{dataset}` against the canonical vocab, PyTC-casing rule |
| `label_naming.py` | `{provenance}-{label_class}-{specific_info}` for every label dir |
| `crop_naming.py` | `crop-NNN.zarr` or `crop-NNN_descriptor.zarr` |
| `stray_files.py` | `.DS_Store` anywhere, job-output junk leftover in `labels/` |
| `pyramid_consistency.py` | Each zarr.json's `multiscales.datasets` list matches what pyramid levels actually exist on disk |
| `metadata_consistency.py` | A label's directory-name-derived provenance/label_class agrees with its own stored metadata |

Full incident-by-incident history and the original design proposal: see `lmvd_quality_control.md`
in the `MIAAI/Jakob` worklog, and [issue #1](https://github.com/AI-HHMI/mia-data-qc/issues/1).

## Running a check

Each check runs standalone, e.g.:
```bash
python3 checks/dataset_naming.py --root /groups/miaai/miaai/lmd-v0.0.1/data
```

Checks that walk every file under `data/` (`ownership_permissions.py`, `stray_files.py`) should be
submitted as an LSF job, never run on a login node — use the matching `submit_*.sh` script, or
`submit_deep_walk_checks.sh` to run both from a single corpus walk (the real production entry
point for those two — `run_deep_walk_checks.py`). Shallow checks (naming, pyramid consistency,
metadata consistency) run in seconds and don't need a cluster job.

Cluster convention: `bsub -q local -P miaai`, no host pinned (let LSF's scheduler pick), `-n`
matched to `--workers`, memory `cores * 15GB` per the cluster's per-core memory policy.
