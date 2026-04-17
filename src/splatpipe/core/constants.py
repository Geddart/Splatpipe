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

# Default LOD configurations: (name, max_splats)
DEFAULT_LOD_LEVELS = [
    ("lod0", 25_000_000),
    ("lod1", 10_000_000),
    ("lod2",  5_000_000),
    ("lod3",  2_000_000),
    ("lod4",  1_000_000),
    ("lod5",    500_000),
]

# Step names used in state.json
STEP_CLEAN = "clean"
STEP_TRAIN = "train"
STEP_REVIEW = "review"
STEP_ASSEMBLE = "assemble"
STEP_EXPORT = "export"

# Plain-language explanations shown as tooltips next to each step in the UI.
STEP_DESCRIPTIONS = {
    STEP_CLEAN: (
        "Filter the COLMAP source: remove camera outliers and prune stray "
        "points using a KD-tree against the cleaned mesh. Skipped "
        "automatically for .psht / .ply input."
    ),
    STEP_TRAIN: (
        "Train Gaussian splats with the selected trainer. Postshot and "
        "LichtFeld retrain from scratch; Passthrough extracts the PLY from "
        "a finished .psht or copies an existing .ply (no retraining)."
    ),
    STEP_REVIEW: (
        "Manual cleanup gate — open each LOD's .psht in Postshot to remove "
        "floaters, then approve. Auto-approved when trainer is Passthrough."
    ),
    STEP_ASSEMBLE: (
        "Generate the viewer output. With renderer=playcanvas (default): runs "
        "splat-transform to produce lod-meta.json + SOG webp chunks. With "
        "renderer=spark: runs Rust build-lod to produce a single scene.rad "
        "(HTTP-Range streaming). Both write index.html + viewer-config.json."
    ),
    STEP_EXPORT: (
        "Copy 05_output/ to a local folder OR upload it to Bunny CDN. "
        "CDN mode prints a viewer URL on completion."
    ),
}
