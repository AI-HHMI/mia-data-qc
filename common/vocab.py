"""Controlled vocabularies for the LMD corpus's naming and metadata conventions,
kept in one place so every check references the same canonical lists instead of
each hardcoding its own copy that can drift out of sync.
"""

# Dataset directory naming: {modality}-{organism}-{dataset}
MODALITIES = {"em", "exm", "lm", "uct"}

# Canonical organism tokens -- one lowercase token per organism, no placeholder
# words. Built from real corpus usage as of Oct 6, 2026 (13 distinct tokens,
# no spelling collisions found).
ORGANISMS = {
    "human", "drosophila", "mouse", "celegans", "zebrafish", "salamander", "rat",
    "greenmonkey", "zebrafinch", "mosquito", "macaque", "hydra", "danionella",
    "insect",
}
# If the correct organism is genuinely unknown, use this placeholder -- it
# reads as an honest gap rather than a wrong answer. Explicitly allowed, not
# a violation.
ORGANISM_PLACEHOLDER = "UNKNOWN"

# "data/source_tmp/{name}/" is a scratch area for not-yet-identified source
# data, not a real {modality}-{organism}-{dataset} directory. Excluded from
# the dataset-naming check entirely.
NON_DATASET_DIRS = {"source_tmp"}

# Label directory naming: {provenance}-{label_class}-{specific_info}
PROVENANCE = {"manual_gt", "auto_pred", "proofread", "public_gt"}

# `neuron` added Oct 21 2026 -- a deliberate choice (FlyID49's `auto_pred-neuron-LSD_sws_b4_msd20`,
# Oct 15 2026) never added to this list; a real gap, not a naming mistake.
# `active_zone` added Oct 21 2026 -- a real, correct biological term (presynaptic active zones,
# `em-mouse-PyTC-synapsenet-hippocampus`'s SynapseNet-derived labels), same pattern as `spine`.
LABEL_CLASS_CORE = {
    "cell", "neurite", "nucleus", "mitochondria", "synapse", "vesicle", "myelin",
    "blood_vessel", "spine", "neuron", "active_zone",
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

# Label metadata schema -- stored zarr.json attributes, not directory-name
# components. Confirmed against real corpus usage Oct 6, 2026: segmentation_type
# and coverage match this vocab exactly; proofreading_status had 3 real
# non-canonical values in use on disk (n/a, complete, none), resolved Oct 20
# 2026 by checking what each one actually meant on its real labels rather than
# just picking a spelling: "complete" (`proofread`-provenance fish2 labels) was
# a spelling variant of `full`; "none" (`auto_pred`-provenance H01-cortex
# labels, zero review done) duplicated `unreviewed`'s existing meaning; "n/a"
# (`public_gt`-provenance synapsenet labels, externally published GT) was a
# genuinely distinct concept -- proofreading doesn't apply to GT at all, not
# merely "unreviewed" -- so `not_applicable` was added as a real 5th value.
SEGMENTATION_TYPES = {"semantic", "instance", "point"}
PROOFREADING_STATUSES = {"unreviewed", "partial", "full", "expert_reviewed", "not_applicable"}
COVERAGES = {"dense_volume", "full_volume", "sparse_crop", "sparse_points"}
