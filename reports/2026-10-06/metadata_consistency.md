# metadata_consistency — 2026-10-06

[← 2026-10-06](index.md)

2 finding(s) on 2026-10-06.

| Dataset | Path | Field | Actual | Expected | Severity | Suggested fix |
|---|---|---|---|---|---|---|
| em-human-H01-cortex | em-human-H01-cortex/crop-001.zarr/labels/auto_pred-cells-c2_seg/zarr.json | label_class_mismatch | dir='cells' vs metadata='cell' | directory name and stored metadata agree | error | determine which is correct and fix the other (don't assume either side) |
| em-human-H01-cortex | em-human-H01-cortex/crop-001.zarr/labels/auto_pred-cells-c3_seg/zarr.json | label_class_mismatch | dir='cells' vs metadata='cell' | directory name and stored metadata agree | error | determine which is correct and fix the other (don't assume either side) |
