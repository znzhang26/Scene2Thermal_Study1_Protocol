"""Study configuration for the Scene2Thermal Study 1 expert annotation tool.

Everything a researcher may need to adjust lives here. Paths can also be
overridden with environment variables (see README).
"""
from __future__ import annotations

import os
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent


def _default_data_root() -> Path:
    env = os.environ.get("S2T_DATA_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    # Prefer <app>/data, then a sibling ../data (the layout used in clean_scene_scan/).
    for candidate in (APP_DIR / "data", APP_DIR.parent / "data"):
        if candidate.is_dir():
            return candidate
    return APP_DIR / "data"


DATA_ROOT: Path = _default_data_root()
MANIFEST_PATH: Path = Path(os.environ.get("S2T_MANIFEST", APP_DIR / "study_manifest.csv"))
DB_PATH: Path = Path(os.environ.get("S2T_DB", APP_DIR / "annotations.db"))
# DELETE is the safest journal mode when the app folder lives in a synced
# folder (Google Drive / Dropbox). WAL is faster but must not be synced.
SQLITE_JOURNAL_MODE = os.environ.get("S2T_SQLITE_JOURNAL_MODE", "DELETE")
EXPORT_DIR: Path = Path(os.environ.get("S2T_EXPORT_DIR", APP_DIR / "exports"))

# --------------------------------------------------------------------------
# Scenes — this mapping is the source of truth. Folders are NEVER substituted
# with similarly named ones (e.g. request_log_cute_kitchen is not used for
# cube_kitchen).
# --------------------------------------------------------------------------
SCENES: dict[str, str] = {
    "cube_kitchen": "request_log_cube_kitchen",
    "kitchen": "request_log_kitchen",
    "cabin": "request_log_cabin",
    "desert": "request_log_desert",
    "gingerbread": "request_log_gingerbread",
    "winter": "request_log_winter",
}

SCENE_LABELS: dict[str, str] = {
    "cube_kitchen": "Cube Kitchen",
    "kitchen": "Kitchen",
    "cabin": "Cabin",
    "desert": "Desert",
    "gingerbread": "Gingerbread",
    "winter": "Winter",
}

SCENE_CSV_NAME = "postprocess_scene_scan_results.csv"
REQUEST_LOG_NAME = "request_log.csv"
SCENE_IMAGE_SUBDIR = Path("request_images") / "scene_inference"
OBJECT_IMAGE_SUBDIR = Path("request_images") / "object_inference"
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}

# Some scenes contain more than one scene-inference run (e.g. gingerbread has
# 8 images from 2 runs). By default all images are shown and the researcher is
# warned. Pin a run here by its filename prefix, e.g.
#   {"gingerbread": "20260817T205630099116Z_d64c511a"}
SCENE_IMAGE_RUN: dict[str, str] = {}

# Only these CSV columns are ever read by the application.
REQUIRED_COLUMNS = ["Object_name", "Object_category"]

# Scene2Thermal predictions. They are never read, displayed, used as defaults,
# or used for sampling. Listed here only so tests can assert their absence.
HIDDEN_PREDICTION_COLUMNS = [
    "Material_category",
    "Is_heat_source",
    "Heat_generation_rate",
    "Initially_on",
    "Heat_capacity",
    "Thermal_conductivity",
    "Mass",
    "Initial_temperature",
]

# --------------------------------------------------------------------------
# Sampling (manifest generation) and presentation randomization
# --------------------------------------------------------------------------
OBJECTS_PER_SCENE = 15
SAMPLING_SEED = "s2t-study1-v1"            # which objects are in the study
PRESENTATION_SALT = "s2t-study1-order-v1"  # per-expert presentation order
# When filling second-instance slots, require a different Object_name from the
# first pick so an obvious duplicate row is not sampled twice. This is not a
# deduplication rule; the formal duplicate rule is still to be decided.
SECOND_INSTANCE_REQUIRE_DISTINCT_NAME = True

# Development: allow experts to proceed when some configured scenes are
# unavailable. The researcher screen can also toggle this (stored in the DB).
DEV_ALLOW_PARTIAL_DATASET_DEFAULT = True

# Optional password for ?mode=researcher (empty = no password).
RESEARCHER_PASSWORD = os.environ.get("S2T_RESEARCHER_PASSWORD", "")

# --------------------------------------------------------------------------
# Heat-transfer graph
# --------------------------------------------------------------------------
ALLOW_DUPLICATE_EDGES = False

ENV_AMBIENT_AIR = ("env_ambient_air", "Ambient air")
ENV_GROUND = ("env_ground", "Ground / supporting surface")
ENV_RADIANT = ("env_radiant", "Radiant environment / sun")

# Scenes where the radiant environment / sun node is meaningful.
RADIANT_NODE_SCENES = {"desert", "winter"}

# If a sampled study object's category matches this pattern, it already
# represents the ground / supporting surface, so the synthetic node is hidden.
GROUND_EQUIVALENT_PATTERN = r"\b(ground|terrain|floors?|flooring|supporting surface|support surface)\b"

# --------------------------------------------------------------------------
# Answer options (stored verbatim in the database and exports)
# --------------------------------------------------------------------------
CANNOT = "Cannot determine"

THERMAL_ROLES = [
    "Active heat source",
    "Active cooling source",
    "Passive thermal object",
    "Environmental / thermal boundary",
    "Thermally negligible",
    CANNOT,
]
OPERATING_STATES = ["On / active", "Off / inactive", "Standby", "Not applicable", CANNOT]
MATERIALS = [
    "Metal", "Wood", "Glass", "Plastic", "Ceramic", "Stone / concrete", "Fabric",
    "Rubber", "Water", "Ice", "Snow", "Food", "Organic material", "Other", CANNOT,
]
RELATIVE_TO_AMBIENT = [
    "Much colder", "Slightly colder", "Approximately ambient",
    "Slightly warmer", "Much warmer", CANNOT,
]
THERMAL_EVOLUTION = [
    "Warm substantially", "Warm slightly", "Remain approximately stable",
    "Cool slightly", "Cool substantially", CANNOT,
]
EVOLUTION_TIMESCALE = [
    "Within seconds", "Within tens of seconds", "Within a few minutes",
    "Longer than a few minutes", "No meaningful change expected", CANNOT,
]
ACTIVATION_RESPONSE = [
    "Heat substantially", "Heat slightly", "Cool substantially", "Cool slightly",
    "Remain approximately unchanged", CANNOT,
]
ACTIVATION_TIMESCALE = [
    "Within seconds", "Within tens of seconds", "Within a few minutes",
    "Longer than a few minutes", CANNOT,
]
CONFIDENCE_LEVELS = [1, 2, 3, 4, 5]

# Conditional activation: based ONLY on the expert's own answers.
ACTIVATION_ROLES = {"Active heat source", "Active cooling source"}
ACTIVATION_STATES = {"Off / inactive", "Standby"}

TRANSFER_MECHANISMS = ["Conduction", "Convection", "Radiation", "Mixed", CANNOT]
FLOW_DIRECTIONS = ["source_to_target", "target_to_source", "approximately_balanced", "cannot_determine"]
STRENGTHS = ["Weak", "Moderate", "Strong", CANNOT]

# Temperature reference scale drawn under temperature inputs (°C).
SCALE_MIN_C, SCALE_MAX_C = -30.0, 110.0
SCALE_TICKS = [(-20, "−20"), (0, "0 freeze"), (20, "20"), (45, "45 pain"), (70, "70"), (100, "100 boil")]
