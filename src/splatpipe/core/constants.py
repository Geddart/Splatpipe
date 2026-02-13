"""Constants for the splatpipe pipeline."""


# Project folder names (renumbered, no RC-specific folders)
FOLDER_COLMAP_SOURCE = "01_colmap_source"
FOLDER_COLMAP_CLEAN = "02_colmap_clean"
FOLDER_TRAINING = "03_training"
FOLDER_REVIEW = "04_review"
FOLDER_OUTPUT = "05_output"

PROJECT_FOLDERS = [
    FOLDER_COLMAP_SOURCE,
    FOLDER_COLMAP_CLEAN,
    FOLDER_TRAINING,
    FOLDER_REVIEW,
    FOLDER_OUTPUT,
]

# Default LOD configurations: (name_suffix, max_splats)
DEFAULT_LOD_LEVELS = [
    ("lod0_20000k", 20_000_000),
    ("lod1_10000k", 10_000_000),
    ("lod2_5000k",   5_000_000),
    ("lod3_2000k",   2_000_000),
    ("lod4_1000k",   1_000_000),
    ("lod5_500k",      500_000),
]

# Step names used in state.json
STEP_CLEAN = "clean"
STEP_TRAIN = "train"
STEP_REVIEW = "review"
STEP_ASSEMBLE = "assemble"
STEP_EXPORT = "export"
