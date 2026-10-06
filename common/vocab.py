"""Controlled vocabularies from lmvd_structure_guideline.md, kept in one place so
every check references the same canonical lists instead of each hardcoding its own
copy that can drift out of sync.
"""

# Section 1: Directory naming -- {modality}-{organism}-{dataset}
MODALITIES = {"em", "exm", "lm", "uct"}

# Canonical organism tokens -- §1: "one lowercase token per organism... never a
# placeholder". Built from the doc's own examples plus every organism actually in
# use on disk as of Oct 6, 2026 (13 distinct tokens, no spelling collisions found).
ORGANISMS = {
    "human", "drosophila", "mouse", "celegans", "zebrafish", "salamander", "rat",
    "greenmonkey", "zebrafinch", "mosquito", "macaque", "hydra", "danionella",
    "insect",
}
# §1: "If the correct organism is unknown, use UNKNOWN -- which reads as a gap --
# rather than a word that reads as an answer." Explicitly allowed, not a violation.
ORGANISM_PLACEHOLDER = "UNKNOWN"

# §1: "data/source_tmp/{name}/" -- a documented scratch area for not-yet-identified
# source data, not a real {modality}-{organism}-{dataset} directory. Excluded from
# the dataset-naming check entirely.
NON_DATASET_DIRS = {"source_tmp"}

# §3: Label directory naming -- {provenance}-{label_class}-{specific_info}
PROVENANCE = {"manual_gt", "auto_pred", "proofread", "public_gt"}

LABEL_CLASS_CORE = {
    "cell", "neurite", "nucleus", "mitochondria", "synapse", "vesicle", "myelin",
    "blood_vessel", "spine",
}
LABEL_CLASS_CELLMAP = {
    "cytoplasm", "plasma_membrane", "extracellular_space", "endoplasmic_reticulum",
    "er_exit_site", "golgi_apparatus", "endosome", "lysosome", "lipid_droplet",
    "peroxisome", "nuclear_envelope", "nuclear_pore", "chromatin", "heterochromatin",
    "euchromatin", "nucleoplasm", "microtubule",
}
LABEL_CLASS_CELLMAP_TB = {
    "nucleolus", "actin", "vimentin", "centriole", "insulin_secretory_granule",
    "glycogen", "red_blood_cell", "ribosome", "basement_membrane",
}
LABEL_CLASS_OTHER = {"all_organelles"}

LABEL_CLASSES = (
    LABEL_CLASS_CORE | LABEL_CLASS_CELLMAP | LABEL_CLASS_CELLMAP_TB | LABEL_CLASS_OTHER
)

# §4: Label Metadata Schema -- stored zarr.json attributes, not directory-name
# components. Confirmed against real corpus usage Oct 6, 2026: segmentation_type
# and coverage match the doc's vocab exactly; proofreading_status has 3 real,
# undocumented values in use (n/a, complete, none) the doc's 4-value list misses.
SEGMENTATION_TYPES = {"semantic", "instance", "point"}
PROOFREADING_STATUSES = {"unreviewed", "partial", "full", "expert_reviewed"}
COVERAGES = {"dense_volume", "full_volume", "sparse_crop", "sparse_points"}
